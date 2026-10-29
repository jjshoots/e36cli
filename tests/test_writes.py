"""Guarded writes: raw classification and the single fault-clear path (STD-08)."""

from __future__ import annotations

import pytest

from e36cli import ds2, ms41, writes
from e36cli.sim import SimDtc, SimTransport, SimulatedDME

FAST = ds2.Timing(deadline=0.05, retries=2, inter_frame_gap=0.0)
DME = 0x12


@pytest.mark.parametrize(
    ("addr", "payload", "kind"),
    [
        (DME, b"\x00", writes.RawKind.READ),
        (0x80, b"\x00", writes.RawKind.READ),  # ident is a read on every module
        (DME, b"\x04\x01", writes.RawKind.READ),
        (DME, b"\x06\x00\xda\x2a\x02", writes.RawKind.READ),
        (DME, b"\x14\x01", writes.RawKind.READ),
        (DME, b"\x05", writes.RawKind.DME_WRITE),
        (DME, b"\x07\x00\x00\x00\x01", writes.RawKind.DME_WRITE),
        (DME, b"\x0b\x01", writes.RawKind.DME_WRITE),
        (DME, b"", writes.RawKind.DME_WRITE),
        (0x80, b"\x04\x01", writes.RawKind.REFUSED),
        (0x44, b"\x05", writes.RawKind.REFUSED),
    ],
)
def test_classify_raw(addr, payload, kind):
    assert writes.classify_raw(addr, payload) is kind


def clear_sends(transport: SimTransport) -> int:
    return transport.sent.count(ds2.build_frame(DME, ms41.CMD_DTC_CLEAR))


class RecordingSim(SimTransport):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.sent: list[bytes] = []

    def send(self, data):
        self.sent.append(bytes(data))
        super().send(data)


def test_clear_acknowledged_rereads_faults():
    t = RecordingSim(SimulatedDME(dtcs=[SimDtc(code=100)]))
    result = writes.clear_faults(ds2.DS2Client(t, FAST))
    assert result.outcome is writes.ClearOutcome.CLEARED
    assert result.faults == []
    assert clear_sends(t) == 1


def test_clear_with_no_answer_is_unknown_and_never_retried():
    t = RecordingSim(SimulatedDME(dtcs=[SimDtc(code=100)]))
    t.inject("drop", at=0)  # the clear frame goes out, no response comes back
    result = writes.clear_faults(ds2.DS2Client(t, FAST))  # FAST allows retries...
    assert result.outcome is writes.ClearOutcome.UNKNOWN
    assert clear_sends(t) == 1  # ...but a write is sent exactly once
    assert result.faults is not None and "re-read shows" in result.message
