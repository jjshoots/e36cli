"""Simulated MS41 DME behind a Transport, for tests and `--sim` runs.

SimTransport serves the same byte stream a real K-line would — including the
echo of every transmitted byte — so framing, echo verification, resync, and
retries exercise identically to real hardware (SPEC invariant 4).

The behavior model encodes our *beliefs* from research/ms41-data.md; only real
captures prove correctness. Replay mode serves a recorded session verbatim.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import ds2
from .capture import CaptureReader, CaptureWriter
from .ms41 import ParamSpec, Profile, load_profiles
from .transport import TransportTimeout

DME_ADDR = ds2.ADDR["DME"]

# Realistic MS41.1 ident (HW 1437806), same layout as the RomRaider capture
# in research/ms41-data.md §2.
SIM_IDENT = b"143780611013021229600001158526000962142564"

# RAM window the sim considers readable (covers 0xDAxx/0xE9xx param clusters).
RAM_LO, RAM_HI = 0xC000, 0x10000

FAULT_KINDS = ("drop", "delay", "corrupt", "truncate", "garbage")


@dataclass
class SimDtc:
    code: int
    status: int = 0x60  # stored + currently present
    frequency: int = 1
    logistics: int = 0
    freeze: bytes = b"\x00\x00\x00\x00"
    hours_raw: int = 1200  # x0.1 h


def _invert(spec: ParamSpec, target: float) -> int:
    """Raw value whose decoded physical value is ~target (formulas are linear)."""
    f0 = spec._fn(0.0)
    slope = spec._fn(1.0) - f0
    raw = 0 if slope == 0 else round((target - f0) / slope)
    if spec.mask is not None:
        return max(0, min(raw, spec.mask))
    bits = spec.size * 8
    lo, hi = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if spec.signed else (0, (1 << bits) - 1)
    return max(lo, min(raw, hi))


class SimulatedDME:
    """Command-level model of an idling MS41.1. `clock` is injectable for tests."""

    def __init__(
        self,
        profile: Profile | None = None,
        dtcs: list[SimDtc] | None = None,
        clock: Callable[[], float] | None = None,
        rng: random.Random | None = None,
        ambient_c: float = 20.0,
    ) -> None:
        if profile is None:
            profile = load_profiles()["ms41.1"]
        self.profile = profile
        self.dtcs = list(dtcs) if dtcs is not None else []
        self._clock = clock if clock is not None else _default_clock()
        self._t0 = self._clock()
        self._rng = rng if rng is not None else random.Random(0)
        self.ambient_c = ambient_c
        self.hours_counter = 1500  # x0.1 h, serves cmd 04 00

    # -- value model ---------------------------------------------------------

    def _physical(self, name: str, t: float) -> float:
        r = self._rng
        if name == "rpm":
            return 800 + r.uniform(-25, 25)
        if name == "coolant_temp":
            return min(90.0, self.ambient_c + 0.2 * t)
        if name == "iat":
            return self.ambient_c + 5 + r.uniform(-0.5, 0.5)
        if name == "battery":
            return 13.9 + r.uniform(-0.05, 0.05)
        if name == "maf":
            return 9.0 + r.uniform(-0.5, 0.5)
        if name == "maf_volts":
            return 1.6 + r.uniform(-0.05, 0.05)
        if name.startswith("o2_"):
            return 0.45 + r.uniform(-0.35, 0.35)
        if name == "tps":
            return 0.8
        if name == "tps_volts":
            return 0.65
        if name == "ignition_advance":
            return 12 + r.uniform(-1, 1)
        if name == "vanos_angle":
            return 110.0
        if name == "injector_pw":
            return 3.5
        if name == "idle_valve":
            return 30.0
        if name == "load":
            return 2.4
        if name.startswith(("stft", "ltft")):
            return 1.0 if "ft" in name else 0.0
        return 0.0  # trims/knock/vss/bit fields: quiet idle

    def _ram_snapshot(self) -> dict[int, int]:
        t = self._clock() - self._t0
        ram: dict[int, int] = {}
        for spec in self.profile.params:
            raw = _invert(spec, self._physical(spec.name, t))
            data = raw.to_bytes(spec.size, spec.endian, signed=spec.signed)
            for i, b in enumerate(data):
                ram[spec.addr + i] = b
        return ram

    # -- command handling ----------------------------------------------------

    def handle(self, addr: int, payload: bytes) -> bytes | None:
        """Response payload (status byte + data), or None for silence."""
        if addr != DME_ADDR or not payload:
            return None
        cmd = payload[0]
        if cmd == 0x00:
            return bytes([ds2.STATUS_OK]) + SIM_IDENT
        if cmd == 0x04:
            sub = payload[1] if len(payload) > 1 else 0x01
            if sub == 0x00:  # prepare: operating-hours counter at data[3:5] BE
                return bytes([ds2.STATUS_OK, 0, 0, 0]) + self.hours_counter.to_bytes(2, "big")
            return bytes([ds2.STATUS_OK]) + self._dtc_records()
        if cmd == 0x14:
            return bytes([ds2.STATUS_OK, 0x00])  # shadow memory: empty
        if cmd == 0x05:
            self.dtcs.clear()
            return bytes([ds2.STATUS_OK])
        if cmd == 0x06:
            return self._read_memory(payload)
        return bytes([0xFF])  # unknown command

    def _dtc_records(self) -> bytes:
        out = bytearray([len(self.dtcs)])
        if not self.dtcs:
            out.append(0x00)  # stock empty response pads: `00 00`
        for d in self.dtcs:
            out += bytes([d.code, d.status, d.frequency, d.logistics])
            out += d.freeze[:4].ljust(4, b"\x00")
            out += d.hours_raw.to_bytes(2, "big")
        return bytes(out)

    def _read_memory(self, payload: bytes) -> bytes:
        if len(payload) != 6 or payload[1] != 0x00:
            return bytes([0xA2])
        address = int.from_bytes(payload[2:5], "big")
        count = payload[5]
        if count == 0 or not (RAM_LO <= address and address + count <= RAM_HI):
            return bytes([0xA2])
        ram = self._ram_snapshot()
        return bytes([ds2.STATUS_OK]) + bytes(ram.get(address + i, 0x00) for i in range(count))


def _default_clock() -> Callable[[], float]:
    import time

    return time.monotonic


@dataclass
class _Fault:
    kind: str
    at: int | None = None  # request ordinal (0-based)
    p: float = 0.0  # probability per request (seeded rng)
    used: bool = False


class SimTransport:
    """Transport-compatible wrapper around a SimulatedDME or a capture replay.

    send() parses the frame, queues echo + response bytes; recv() serves the
    queue and raises TransportTimeout when it runs dry (a silent wire).
    """

    def __init__(
        self,
        dme: SimulatedDME | None = None,
        replay: CaptureReader | None = None,
        rng: random.Random | None = None,
        capture: CaptureWriter | None = None,
    ) -> None:
        if dme is None and replay is None:
            dme = SimulatedDME()
        self.dme = dme
        self._pairs = _replay_pairs(replay) if replay is not None else None
        self._rng = rng if rng is not None else random.Random(0)
        self._capture = capture
        self._queue = bytearray()
        self._faults: list[_Fault] = []
        self._n_requests = 0

    @classmethod
    def from_capture(cls, path: Path) -> "SimTransport":
        return cls(dme=None, replay=CaptureReader(path))

    def inject(self, kind: str, at: int | None = None, p: float = 0.0) -> None:
        if kind not in FAULT_KINDS:
            raise ValueError(f"unknown fault {kind!r}; choose from {FAULT_KINDS}")
        self._faults.append(_Fault(kind, at=at, p=p))

    def _pick_fault(self) -> str | None:
        for f in self._faults:
            if f.at is not None and not f.used and f.at == self._n_requests:
                f.used = True
                return f.kind
            if f.at is None and f.p > 0 and self._rng.random() < f.p:
                return f.kind
        return None

    # -- Transport protocol ----------------------------------------------------

    def send(self, data: bytes) -> None:
        if self._capture is not None:
            self._capture.record("tx", data)
        fault = self._pick_fault()
        self._n_requests += 1

        if self._pairs is not None:  # replay: recorded rx already includes echo
            self._queue.extend(_replay_lookup(self._pairs, data))
            return

        self._queue.extend(data)  # the K-line echo
        try:
            frame = ds2.parse_frame(data)
        except ds2.DS2Error:
            return  # malformed request: a real module stays silent
        payload = self.dme.handle(frame.addr, frame.payload) if self.dme else None
        if payload is None:
            return
        response = ds2.build_frame(frame.addr, payload)
        if fault in ("drop", "delay"):
            return  # no response bytes: recv starves and times out
        if fault == "corrupt":
            response = response[:-1] + bytes([response[-1] ^ 0xFF])
        elif fault == "truncate":
            response = response[:-2]
        elif fault == "garbage":
            response = bytes([0xEE] * 5) + response
        self._queue.extend(response)

    def recv(self, n: int, deadline: float) -> bytes:
        if len(self._queue) < n:
            partial = bytes(self._queue)
            self._queue.clear()
            if partial and self._capture is not None:
                self._capture.record("rx", partial)
            raise TransportTimeout(
                f"sim wire silent: wanted {n} bytes, had {len(partial)}", partial
            )
        out = bytes(self._queue[:n])
        del self._queue[:n]
        if self._capture is not None:
            self._capture.record("rx", out)
        return out

    def flush_input(self) -> None:
        self._queue.clear()

    def close(self) -> None:
        if self._capture is not None:
            self._capture.close()


def _replay_pairs(reader: CaptureReader) -> list[list]:
    """Pair each tx frame with the rx bytes that followed it (echo included)."""
    pairs: list[list] = []  # [tx_bytes, rx_bytearray, used]
    for ev in reader.events:
        if ev.dir == "tx":
            pairs.append([ev.data, bytearray(), False])
        elif pairs:
            pairs[-1][1].extend(ev.data)
    return pairs


def _replay_lookup(pairs: list[list], request: bytes) -> bytes:
    for pair in pairs:  # prefer the first unused exact match (preserves order)
        if not pair[2] and pair[0] == request:
            pair[2] = True
            return bytes(pair[1])
    for pair in pairs:  # fall back to reusing any exact match
        if pair[0] == request:
            return bytes(pair[1])
    return b""  # not in the recording: silence
