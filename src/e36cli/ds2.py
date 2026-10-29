"""DS2 protocol client (BMW K-line, E36 era).

Byte-level facts sourced in research/ds2-protocol.md:
- frame = [addr][len][payload...][xor]; len counts the WHOLE frame
- checksum = XOR of all preceding bytes, initial 0
- response payload byte 0 is the status byte (0xA0 = OK)
- the K-line echoes every transmitted byte; the echo is read back and matched
Garbage/resync: the K-line carries noise (stray 0x00s, unsolicited frames), so
both the echo read and the response read scan-and-strip leading bytes until a
match / plausible header appears (garagediag-style resync), bounded by
Timing.resync_budget. A header whose frame fails its checksum re-enters the
hunt one byte later rather than discarding the buffer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .errors import E36Error
from .transport import Transport, TransportTimeout

MAX_PAYLOAD = 252  # 8-bit length byte counts the whole frame (3 overhead bytes)
_MIN_RESPONSE_LEN = 4  # addr, len, status, cksum

STATUS_OK = 0xA0

STATUS_MEANINGS = {
    0xA0: "ok",
    0xA1: "busy",
    0xA2: "invalid parameter",
    0xB0: "command rejected",
    0xFF: "unknown command",
}

# E36-era DS2 module addresses (research/ds2-protocol.md §3).
ADDR = {
    "GM": 0x00,
    "SZM": 0x08,
    "DME": 0x12,
    "CDC": 0x18,
    "EGS": 0x32,
    "EWS": 0x44,
    "MFL": 0x50,
    "ABS": 0x56,
    "IHKA": 0x5B,
    "PDC": 0x60,
    "RADIO": 0x68,
    "DSP": 0x6A,
    "IKE": 0x80,
    "MRS": 0xA4,
    "MID": 0xC0,
    "TEL": 0xC8,
    "LCM": 0xD0,
}

ADDR_NAMES = {v: k for k, v in ADDR.items()}


class DS2Error(E36Error):
    """Base for DS2 protocol failures."""


class EchoMismatch(DS2Error):
    """K-line echo differed from the transmitted frame (collision or wiring)."""

    def __init__(self, sent: bytes, got: bytes) -> None:
        super().__init__(f"echo mismatch: sent {hexstr(sent)}, read back {hexstr(got)}")
        self.sent = sent
        self.got = got


class ChecksumError(DS2Error):
    def __init__(self, raw: bytes) -> None:
        super().__init__(f"bad checksum in frame {hexstr(raw)}")
        self.raw = raw


class Timeout(DS2Error):
    """No valid response within the deadline. `.partial` holds stray bytes."""

    def __init__(self, msg: str, partial: bytes = b"") -> None:
        super().__init__(msg)
        self.partial = partial


class NakResponse(DS2Error):
    """Module answered with a non-OK status byte."""

    def __init__(self, addr: int, status: int) -> None:
        self.addr = addr
        self.status = status
        self.meaning = STATUS_MEANINGS.get(status, "unknown status")
        super().__init__(f"module 0x{addr:02X} answered status 0x{status:02X} ({self.meaning})")


def xor_checksum(data: bytes) -> int:
    cks = 0
    for b in data:
        cks ^= b
    return cks


def build_frame(addr: int, payload: bytes) -> bytes:
    if not 0 <= addr <= 0xFF:
        raise DS2Error(f"address out of range: {addr}")
    if len(payload) > MAX_PAYLOAD:
        raise DS2Error(f"payload too long: {len(payload)} > {MAX_PAYLOAD}")
    body = bytes([addr, len(payload) + 3]) + payload
    return body + bytes([xor_checksum(body)])


@dataclass(frozen=True)
class Frame:
    addr: int
    payload: bytes
    raw: bytes


def parse_frame(buf: bytes) -> Frame:
    if len(buf) < 3:
        raise DS2Error(f"frame too short: {hexstr(buf)}")
    if buf[1] != len(buf):
        raise DS2Error(f"length byte {buf[1]} != frame size {len(buf)}: {hexstr(buf)}")
    if xor_checksum(buf[:-1]) != buf[-1]:
        raise ChecksumError(buf)
    return Frame(addr=buf[0], payload=bytes(buf[2:-1]), raw=bytes(buf))


@dataclass(frozen=True)
class Response:
    frame: Frame

    @property
    def status(self) -> int:
        return self.frame.payload[0]

    @property
    def data(self) -> bytes:
        return self.frame.payload[1:]

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK


@dataclass
class Timing:
    """All wire timing knobs in one place (seconds)."""

    deadline: float = 0.3  # per-attempt response deadline
    retries: int = 2  # extra attempts after the first
    inter_frame_gap: float = 0.005  # min quiet time between requests (research: ~0 observed)
    busy_delay: float = 0.05  # wait before retrying after 0xA1 busy
    resync_budget: int = 64  # max bytes discarded while hunting a frame start


# Timing presets observed in the field (research §1.4): fault reads and
# especially clears are slow; everything else fits the default.
SLOW = Timing(deadline=0.8)
CLEAR = Timing(deadline=1.5, retries=0)


class DS2Client:
    """One-request-at-a-time DS2 client over a Transport."""

    def __init__(self, transport: Transport, timing: Timing | None = None) -> None:
        self.transport = transport
        self.timing = timing or Timing()
        self._last_io = 0.0

    def query(
        self,
        addr: int,
        payload: bytes,
        timing: Timing | None = None,
        max_response: int | None = None,
    ) -> Response:
        t = timing or self.timing
        request = build_frame(addr, payload)
        max_len = min(max_response, 0xFF) if max_response else 0xFF
        attempts = t.retries + 1
        last_err: DS2Error | None = None
        while attempts > 0:
            attempts -= 1
            self._respect_gap(t)
            try:
                resp = self._attempt(addr, request, t, max_len)
            except (Timeout, ChecksumError, EchoMismatch) as exc:
                last_err = exc
                continue
            if resp.status == 0xA1 and attempts > 0:  # busy: wait and retry
                time.sleep(t.busy_delay)
                last_err = NakResponse(addr, resp.status)
                continue
            if not resp.ok:
                raise NakResponse(addr, resp.status)
            return resp
        assert last_err is not None
        raise last_err

    def _respect_gap(self, t: Timing) -> None:
        wait = self._last_io + t.inter_frame_gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def _attempt(self, addr: int, request: bytes, t: Timing, max_len: int) -> Response:
        end = time.monotonic() + t.deadline
        self.transport.flush_input()
        self.transport.send(request)
        self._last_io = time.monotonic()
        try:
            self._consume_echo(request, end, t)
            frame = self._read_frame(addr, end, t, max_len)
        except TransportTimeout as exc:
            raise Timeout(str(exc), partial=exc.partial) from exc
        finally:
            self._last_io = time.monotonic()
        if not frame.payload:
            raise DS2Error(f"response has no status byte: {hexstr(frame.raw)}")
        return Response(frame)

    def _consume_echo(self, request: bytes, end: float, t: Timing) -> None:
        """Match-and-strip the K-line echo, tolerating leading noise bytes."""
        echo = bytearray(self.transport.recv(len(request), self._left(end)))
        dropped = 0
        while bytes(echo) != request:
            dropped += 1
            if dropped > t.resync_budget:
                raise EchoMismatch(request, bytes(echo))
            del echo[0]
            echo.extend(self.transport.recv(1, self._left(end)))

    def _read_frame(self, addr: int, end: float, t: Timing, max_len: int = 0xFF) -> Frame:
        """Read one valid frame from `addr`, resyncing past noise bytes.

        A plausible header is expected-address + length in [4, max_len]. If the
        framed bytes fail their checksum, the hunt re-enters one byte later
        (the header match may have been data coincidence); the budget caps
        total discarded bytes either way.
        """
        buf = bytearray()
        dropped = 0
        last_cks: ChecksumError | None = None

        def refill(n: int) -> None:
            # Once a checksum failure is on record, a dry wire means the
            # garbled frame was the response — surface the ChecksumError
            # (retryable) rather than a less informative Timeout.
            try:
                while len(buf) < n:
                    buf.extend(self.transport.recv(n - len(buf), self._left(end)))
            except TransportTimeout:
                if last_cks is not None:
                    raise last_cks from None
                raise

        def drop_one() -> None:
            nonlocal dropped
            dropped += 1
            if dropped > t.resync_budget:
                if last_cks is not None:
                    raise last_cks
                raise Timeout(
                    f"no frame from 0x{addr:02X} within resync budget",
                    partial=bytes(buf),
                )
            del buf[0]

        refill(2)
        while True:
            while buf[0] != addr or not _MIN_RESPONSE_LEN <= buf[1] <= max_len:
                drop_one()
                refill(2)
            refill(buf[1])
            try:
                return parse_frame(bytes(buf[: buf[1]]))
            except ChecksumError as exc:
                last_cks = exc
                drop_one()
                refill(2)

    @staticmethod
    def _left(end: float) -> float:
        return max(end - time.monotonic(), 0.001)


def hexstr(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def parse_hex(text: str) -> bytes:
    cleaned = text.replace(",", " ").replace("0x", " ").replace("0X", " ")
    parts = cleaned.split()
    try:
        if len(parts) == 1 and len(parts[0]) > 2:
            return bytes.fromhex(parts[0])
        return bytes(int(p, 16) for p in parts)
    except ValueError as exc:
        raise DS2Error(f"not valid hex: {text!r}") from exc
