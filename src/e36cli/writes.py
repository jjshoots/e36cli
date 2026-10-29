"""Guarded writes (SPEC invariant 2, STANDARDS.md STD-08).

The one module that knows which DS2 requests change ECU state, and the only
sender of the fault-clear command. Writes are never retried: a timeout after
the frame went out leaves the ECU state unknown, and resending a
state-changing frame is not ours to decide — so the outcome says "unknown"
and the faults are re-read to show what actually happened.
"""

from __future__ import annotations

import dataclasses
import enum
from dataclasses import dataclass

from . import ds2, ms41, policy
from . import dtc as dtcmod

# Asked before every fault clear, in the CLI and in the TUIs.
CLEAR_QUESTION = "Clear the DME fault memory? This is a write to the ECU."

# DME commands known to be reads (first payload byte). Anything else sent to
# the DME — 0x05 clear, 0x07 memory write, 0x0B telegram arming, unknown
# opcodes — is treated as a write.
DME_READS = {
    ms41.CMD_IDENT[0]: "ident",
    ms41.CMD_DTC_READ[0]: "fault memory read",
    0x06: "RAM read",
    ms41.CMD_DTC_SHADOW[0]: "shadow fault memory read",
}

# Every attempt of a write goes out once; never retry a possibly-applied write.
WRITE_TIMING = dataclasses.replace(ds2.CLEAR, retries=0)


class RawKind(enum.Enum):
    READ = "read"  # free: ident anywhere, known reads on the DME
    DME_WRITE = "write"  # guarded: confirmation, sent once
    REFUSED = "refused"  # non-DME, non-ident: never sent (SPEC hard rule)


def classify_raw(addr: int, payload: bytes) -> RawKind:
    """What sending `payload` to `addr` would be, for `e36 raw`'s guard."""
    if payload == ms41.CMD_IDENT:
        return RawKind.READ
    if addr != ds2.ADDR["DME"]:
        # Non-DME modules are ident-only: the cluster's command space holds an
        # odometer reset (research/cluster-and-service-reset.md §1c).
        return RawKind.REFUSED
    if payload and payload[0] in DME_READS:
        return RawKind.READ
    return RawKind.DME_WRITE


class ClearOutcome(enum.Enum):
    CLEARED = "cleared"  # the DME acknowledged the clear
    FAILED = "failed"  # the DME refused (NAK): nothing changed
    UNKNOWN = "unknown"  # no answer after the frame went out: may or may not have applied


@dataclass(frozen=True)
class ClearResult:
    outcome: ClearOutcome
    message: str
    faults: list[dtcmod.Dtc] | None  # re-read after the attempt; None if that failed too
    hours_now: float | None = None


def clear_faults(client: ds2.DS2Client) -> ClearResult:
    """Send the DME fault-clear once and re-read the fault memory.

    Callers must have confirmed with the user already (SPEC invariant 2).
    Raises only what the re-read can't absorb (a capture failure, a bug).
    """
    try:
        client.query(ds2.ADDR["DME"], ms41.CMD_DTC_CLEAR, timing=WRITE_TIMING)
    except ds2.NakResponse as exc:
        outcome, message = ClearOutcome.FAILED, f"clear refused by the DME: {exc}"
    except policy.LINK as exc:
        outcome = ClearOutcome.UNKNOWN
        message = f"no confirmation from the DME ({exc}); clear may or may not have applied"
    else:
        outcome, message = ClearOutcome.CLEARED, "fault memory cleared"
    try:
        faults, hours_now = dtcmod.fetch_faults(client)
    except policy.FAULT_POLL_NONFATAL as exc:
        return ClearResult(outcome, f"{message}; re-read failed: {exc}", None)
    if outcome is ClearOutcome.UNKNOWN:
        message += f"; re-read shows {len(faults)} stored fault(s)"
    return ClearResult(outcome, message, faults, hours_now)
