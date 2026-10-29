"""The failure policy table (src/e36cli/policy.py) pinned against SPEC's
"Failure policy" and "`e36 log` policy" paragraphs (STANDARDS.md STD-03)."""

from __future__ import annotations

import pytest

from e36cli import ds2, live, ms41, policy
from e36cli import dtc as dtcmod
from e36cli.capture import CaptureError
from e36cli.errors import E36Error
from e36cli.formula import FormulaError
from e36cli.transport import TransportError, TransportTimeout

N = ["poll_transient", "fault_nonfatal", "log_reconnect", "scan_silent"]

# error -> (poller param poll transient, fault poll non-fatal, log reconnects, scan "silent")
TABLE = [
    (TransportError("gone"), (True, True, True, False)),
    (TransportTimeout("slow"), (True, True, True, False)),
    (ds2.Timeout("no answer"), (True, True, True, True)),
    (ds2.ChecksumError(b"\x12\x04\x00\x00"), (True, True, True, True)),
    (ds2.EchoMismatch(b"\x12", b"\x13"), (True, True, True, True)),
    (ds2.NakResponse(0x12, 0xA1), (True, True, False, False)),
    (dtcmod.DtcError("bad record"), (False, True, False, False)),
    (ms41.DecodeError("short read"), (False, True, False, False)),
    (ms41.ProfileError("bad profile"), (False, False, False, False)),
    (ms41.UnknownParamError("warp_core"), (False, False, False, False)),
    (FormulaError("x / 0"), (False, False, False, False)),
    (CaptureError("disk full"), (False, False, False, False)),
    (live.LiveFatal("poller died"), (False, False, False, False)),
    (RuntimeError("bug"), (False, False, False, False)),
]


@pytest.mark.parametrize(("exc", "expected"), TABLE, ids=lambda v: type(v).__name__)
def test_policy_table(exc, expected):
    got = tuple(
        isinstance(exc, t)
        for t in (
            policy.POLL_TRANSIENT,
            policy.FAULT_POLL_NONFATAL,
            policy.LOG_RECONNECT,
            policy.SCAN_SILENT,
        )
    )
    assert dict(zip(N, got, strict=True)) == dict(zip(N, expected, strict=True))


@pytest.mark.parametrize(("exc", "_"), TABLE, ids=lambda v: type(v).__name__)
def test_every_deliberate_error_is_user_facing_and_bugs_are_not(exc, _):
    assert isinstance(exc, policy.USER_FACING) == (not isinstance(exc, RuntimeError))
    assert isinstance(exc, E36Error) == isinstance(exc, policy.USER_FACING)


def test_capture_error_is_never_retried():
    for name in ("LINK", "POLL_TRANSIENT", "FAULT_POLL_NONFATAL", "LOG_RECONNECT", "SCAN_SILENT"):
        assert not issubclass(CaptureError, getattr(policy, name)), name
