"""DS2 protocol client tests against a scripted fake transport."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from e36cli import ds2
from e36cli.ds2 import (
    ADDR,
    ChecksumError,
    DS2Client,
    DS2Error,
    EchoMismatch,
    NakResponse,
    Timeout,
    Timing,
    build_frame,
    hexstr,
    parse_frame,
    parse_hex,
    xor_checksum,
)
from e36cli.transport import TransportTimeout

FAST = Timing(deadline=0.05, retries=2, inter_frame_gap=0.0, busy_delay=0.0)

IDENT_REQUEST = bytes.fromhex("12040016")  # canonical: research/ds2-protocol.md §2.1


def response_frame(addr: int, status: int, data: bytes = b"") -> bytes:
    return build_frame(addr, bytes([status]) + data)


class FakeTransport:
    """Scripted transport: echoes sends (optionally mangled), then plays one
    scripted rx chunk per send."""

    def __init__(self, responses, echo=True, mangle_echo=False):
        self.responses = list(responses)
        self.echo = echo
        self.mangle_echo = mangle_echo
        self.sent: list[bytes] = []
        self.rx = bytearray()

    def send(self, data: bytes) -> None:
        self.sent.append(bytes(data))
        if self.echo:
            e = bytearray(data)
            if self.mangle_echo:
                e[0] ^= 0xFF
            self.rx.extend(e)
        if self.responses:
            self.rx.extend(self.responses.pop(0))

    def recv(self, n: int, deadline: float) -> bytes:
        if len(self.rx) < n:
            partial = bytes(self.rx)
            self.rx.clear()
            raise TransportTimeout(f"wanted {n}, had {len(partial)}", partial=partial)
        out = bytes(self.rx[:n])
        del self.rx[:n]
        return out

    def flush_input(self) -> None:
        # Real flush happens before send; scripted bytes arrive after. Only
        # drop leftovers from a previous exchange.
        self.rx.clear()

    def close(self) -> None:
        pass


# --- framing -----------------------------------------------------------------


def test_build_frame_canonical_ident():
    assert build_frame(0x12, b"\x00") == IDENT_REQUEST


def test_build_frame_status_group():
    # 17-param status group request: 12 05 0B 03 1F (research §2.1)
    assert build_frame(0x12, b"\x0b\x03") == bytes.fromhex("12050B031F")


def test_parse_frame_real_trace():
    # Captured MS41.1 response: 12 07 A0 21 00 01 95 (research §2.2)
    f = parse_frame(bytes.fromhex("1207A021000195"))
    assert f.addr == 0x12
    assert f.payload == bytes.fromhex("A0210001")


def test_parse_frame_rejects_bad_checksum():
    raw = bytearray(bytes.fromhex("1207A021000195"))
    raw[-1] ^= 0x01
    with pytest.raises(ChecksumError):
        parse_frame(bytes(raw))


def test_parse_frame_rejects_wrong_length_byte():
    raw = bytes([0x12, 0x05, 0x00, 0x17])  # claims 5 bytes, is 4
    with pytest.raises(DS2Error):
        parse_frame(raw)


def test_parse_frame_rejects_short_buffer():
    with pytest.raises(DS2Error):
        parse_frame(b"\x12\x03")


def test_build_frame_rejects_oversize_payload():
    with pytest.raises(DS2Error):
        build_frame(0x12, bytes(253))


def test_build_frame_rejects_bad_address():
    with pytest.raises(DS2Error):
        build_frame(0x100, b"\x00")


@given(addr=st.integers(0, 0xFF), payload=st.binary(min_size=0, max_size=252))
def test_frame_round_trip(addr, payload):
    f = parse_frame(build_frame(addr, payload))
    assert f.addr == addr
    assert f.payload == payload


@given(data=st.binary(min_size=1, max_size=64))
def test_xor_checksum_self_cancels(data):
    assert xor_checksum(data + bytes([xor_checksum(data)])) == 0


# --- client happy path -------------------------------------------------------


def test_query_ident_happy_path():
    ident = response_frame(0x12, 0xA0, b"1437806")
    tp = FakeTransport([ident])
    resp = DS2Client(tp, FAST).query(0x12, b"\x00")
    assert tp.sent == [IDENT_REQUEST]
    assert resp.ok and resp.status == 0xA0
    assert resp.data == b"1437806"


def test_query_strips_echo_before_response():
    tp = FakeTransport([response_frame(0x12, 0xA0, b"\x01")])
    resp = DS2Client(tp, FAST).query(0x12, b"\x00")
    assert resp.data == b"\x01"  # echo bytes not mistaken for the response


# --- client fault handling ---------------------------------------------------


def test_echo_mismatch_raises():
    tp = FakeTransport([response_frame(0x12, 0xA0)], mangle_echo=True)
    with pytest.raises(EchoMismatch):
        DS2Client(tp, FAST).query(0x12, b"\x00")


def test_corrupt_checksum_then_clean_retry_succeeds():
    bad = bytearray(response_frame(0x12, 0xA0, b"\x42"))
    bad[-1] ^= 0x01
    tp = FakeTransport([bytes(bad), response_frame(0x12, 0xA0, b"\x42")])
    resp = DS2Client(tp, FAST).query(0x12, b"\x00")
    assert resp.data == b"\x42"
    assert len(tp.sent) == 2


def test_truncated_response_times_out_with_partial():
    tp = FakeTransport([response_frame(0x12, 0xA0, b"\x01\x02")[:4]], echo=True)
    with pytest.raises(Timeout):
        DS2Client(tp, Timing(deadline=0.05, retries=0, inter_frame_gap=0.0)).query(
            0x12, b"\x00"
        )


def test_silent_wire_times_out_after_retries():
    tp = FakeTransport([], echo=False)
    client = DS2Client(tp, FAST)
    with pytest.raises(Timeout):
        client.query(0x12, b"\x00")
    assert len(tp.sent) == FAST.retries + 1


def test_busy_then_ok():
    tp = FakeTransport(
        [response_frame(0x12, 0xA1), response_frame(0x12, 0xA0, b"\x07")]
    )
    resp = DS2Client(tp, FAST).query(0x12, b"\x0b\x03")
    assert resp.data == b"\x07"


def test_busy_exhausting_retries_raises_nak():
    tp = FakeTransport([response_frame(0x12, 0xA1)] * 3)
    with pytest.raises(NakResponse) as exc_info:
        DS2Client(tp, FAST).query(0x12, b"\x00")
    assert exc_info.value.status == 0xA1


@pytest.mark.parametrize(
    "status,meaning",
    [(0xA2, "invalid parameter"), (0xB0, "command rejected"), (0xFF, "unknown command")],
)
def test_nak_statuses_mapped(status, meaning):
    tp = FakeTransport([response_frame(0x12, status)])
    with pytest.raises(NakResponse) as exc_info:
        DS2Client(tp, FAST).query(0x12, b"\x04")
    assert exc_info.value.status == status
    assert exc_info.value.meaning == meaning


def test_unknown_status_byte_is_nak_with_unknown_meaning():
    tp = FakeTransport([response_frame(0x12, 0x5A)])
    with pytest.raises(NakResponse) as exc_info:
        DS2Client(tp, FAST).query(0x12, b"\x00")
    assert exc_info.value.meaning == "unknown status"


def test_garbage_before_response_is_resynced_past():
    # Noise (0x00 break bytes + junk) ahead of a valid frame: client should
    # drop bytes until the expected address + plausible length line up.
    noise = b"\x00\x00\xfe"
    tp = FakeTransport([noise + response_frame(0x12, 0xA0, b"\x09")])
    resp = DS2Client(tp, FAST).query(0x12, b"\x00")
    assert resp.data == b"\x09"


def test_resync_budget_bounds_junk_scan():
    junk = bytes(200)  # all zeros, never a valid header for 0x12
    tp = FakeTransport([junk])
    t = Timing(deadline=0.05, retries=0, inter_frame_gap=0.0, resync_budget=16)
    with pytest.raises(Timeout):
        DS2Client(tp, t).query(0x12, b"\x00")


# --- helpers -----------------------------------------------------------------


def test_addr_table():
    assert ADDR["DME"] == 0x12
    assert ADDR["EWS"] == 0x44
    assert ADDR["IKE"] == 0x80
    assert ds2.ADDR_NAMES[0x12] == "DME"


def test_hexstr_and_parse_hex_round_trip():
    data = bytes.fromhex("12050B031F")
    assert parse_hex(hexstr(data)) == data
    assert parse_hex("12050b031f") == data
    assert parse_hex("0x12 0x05 0x0B 0x03 0x1F") == data


def test_parse_hex_rejects_garbage():
    with pytest.raises(DS2Error):
        parse_hex("zz qq")
