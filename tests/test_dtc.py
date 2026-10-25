"""DTC decode: records, flags, freeze frame, edge cases."""

from __future__ import annotations

import pytest

from e36cli.dtc import (
    Dtc,
    DtcError,
    decode_dtc_response,
    decode_freeze_value,
    decode_hours_counter,
    describe,
)


def record(code, status=0x40, freq=3, logistics=1, freeze=b"\x10\x20\x30\x40", hours=0x0123):
    return bytes([code, status, freq, logistics]) + freeze + hours.to_bytes(2, "big")


def test_decode_two_stored_records():
    payload = bytes([2]) + record(8, status=0x60, hours=100) + record(83, status=0x80)
    dtcs = decode_dtc_response(payload)
    assert [d.code for d in dtcs] == [8, 83]
    maf, crank = dtcs
    assert maf.description == "Air Flow Meter (HFM)"
    assert maf.system == "Air Intake"
    assert maf.present is True and maf.sporadic is False
    assert "stored after debounce" in maf.flags
    assert maf.frequency == 3
    assert maf.freeze_raw == b"\x10\x20\x30\x40"
    assert maf.hours_raw == 100
    assert maf.hours_ago(current_counter=150) == pytest.approx(5.0)
    assert crank.description == "Crankshaft Sensor"
    assert crank.present is False and crank.sporadic is True


def test_unknown_code_fallback():
    (d,) = decode_dtc_response(bytes([1]) + record(4))  # 4 is unassigned
    assert d.description == "unknown fault code 4"
    assert d.system == "Unknown"


def test_empty_response_stock_padding():
    # stock MS41 returns count 0 plus a pad byte (research §4.1)
    assert decode_dtc_response(b"\x00\x00") == []
    assert decode_dtc_response(b"\x00") == []


def test_shadow_11_byte_records():
    e = record(10) + b"\x07"  # 11-byte entries divide evenly → derived size
    dtcs = decode_dtc_response(bytes([1]) + e)
    assert dtcs[0].code == 10
    assert dtcs[0].description == "Coolant Temperature Sensor"


def test_malformed_payload_raises():
    with pytest.raises(DtcError):
        decode_dtc_response(b"")
    with pytest.raises(DtcError):
        decode_dtc_response(bytes([3]) + record(8))  # count says 3, bytes for 1


def test_describe_known_and_unknown():
    assert describe(238) == ("Misfire Cyl 1", "Ignition")
    assert describe(7)[0] == "unknown fault code 7"


def test_freeze_value_decode():
    value, unit, label = decode_freeze_value(0x09, 120)  # battery: 120 * 0.102
    assert value == pytest.approx(12.24)
    assert unit == "V"
    assert "Battery" in label
    coolant = decode_freeze_value(0x18, 171)
    assert coolant[0] == pytest.approx(171 * 0.7471 - 48)
    assert decode_freeze_value(0x99, 1) is None


def test_hours_counter():
    # prepare response payload: bytes [3:5] big-endian, x0.1 h
    assert decode_hours_counter(bytes([0, 0, 0, 0x01, 0x23])) == pytest.approx(29.1)
    assert decode_hours_counter(b"\x00\x00") is None


def test_flags_enumeration():
    d = Dtc(code=1, description="x", system="y", status=0x47)
    assert set(d.flags) == {"short to B+", "short to ground", "open circuit", "currently present"}


def test_trailing_pad_bytes_tolerated():
    # count=2 with 23 record bytes: 2x10-byte records + 3 pad bytes must decode
    # as stored records, not error (review: ECUs pad; sizes vary per module).
    payload = bytes([2]) + record(100) + record(214) + b"\x00\x00\x00"
    faults = decode_dtc_response(payload)
    assert [f.code for f in faults] == [100, 214]


def test_dtc_carries_db_verified_flag():
    (fault,) = decode_dtc_response(bytes([1]) + record(100))
    assert fault.verified is False  # db is file-level verified=false pre-garage
