"""Failure policy: how each error class is treated, defined once (STD-03).

The single source for SPEC's "Failure policy" and "`e36 log` policy"
paragraphs — change them together. Where two callers deliberately differ (the
live poller rides out a NAK, `e36 log` stops on one) the difference is two
named tuples side by side, not two hand-written `except` lists.

Not listed anywhere, so always fatal: `CaptureError` (a run that cannot record
its wire traffic must stop, SPEC invariant 1) and anything that is not an
`E36Error` (a bug: keep the traceback).
"""

from __future__ import annotations

from . import ds2, ms41
from . import dtc as dtcmod
from .errors import E36Error
from .transport import TransportError

ErrorTypes = tuple[type[BaseException], ...]

# The wire or the port misbehaved; the same request may succeed next time.
# (SerialTransport wraps every pyserial/termios failure into TransportError;
# the DS2 client has already spent its retries on the three DS2 ones.)
LINK: ErrorTypes = (TransportError, ds2.Timeout, ds2.ChecksumError, ds2.EchoMismatch)

# Live poller param polls: transient — keep polling, give up after
# MAX_CONSECUTIVE_FAILURES in a row. A busy DME may NAK mid-poll, so NAK
# counts as transient here.
POLL_TRANSIENT: ErrorTypes = (*LINK, ds2.NakResponse)

# Interleaved fault polls never stop the poller: a failed or undecodable read
# keeps the last-known fault list with a "read failed" note.
FAULT_POLL_NONFATAL: ErrorTypes = (*POLL_TRANSIENT, dtcmod.DtcError, ms41.DecodeError)

# `e36 log`: close the port, wait for the device, reopen and resume. A NAK or
# a decode/profile error is deterministic — reopening cannot fix it — so fatal.
LOG_RECONNECT: ErrorTypes = LINK

# `e36 scan`: an address with no coherent answer is reported "silent". A dead
# port (TransportError) is NOT silence — it aborts the scan.
SCAN_SILENT: ErrorTypes = (ds2.Timeout, ds2.ChecksumError, ds2.EchoMismatch)

# CLI: every deliberate error becomes one red line and exit 1.
USER_FACING: ErrorTypes = (E36Error,)
