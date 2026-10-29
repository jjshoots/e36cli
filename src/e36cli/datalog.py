"""`e36 log` engine: per-row-flushed sample writer + burst/reconnect loop.

Field facts behind this module (car/research/session3-coldstart.md §2): the
FT232RL drops mid-stream with pyserial's "device reports readiness to read but
returned no data", the device node vanishes and re-enumerates (same or a new
/dev/ttyUSBn) or stays gone until replugged; bursts of 40 samples with a fresh
port open per burst survived where a continuous stream died.

Layering (SPEC): the reconnect policy lives HERE, in the CLI/poller layer. The
DS2 client and the transports know nothing about it — on every (re)open we
simply build a fresh `DS2Client` around a fresh transport; the client already
flushes input and strips the K-line echo (tolerating leading noise) on every
request, so a fresh open needs no special handling.
"""

from __future__ import annotations

import csv
import glob
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO

from . import ds2, live, ms41
from .transport import Transport, TransportError, close_quietly, set_ftdi_latency

# Seconds between device-node checks / reopen attempts while the link is down.
RECONNECT_POLL_S = 0.5

# Default prophylactic reopen period (samples). Session 3: 13 consecutive
# 40-sample bursts survived on a cable that died under continuous streaming.
DEFAULT_BURST = 40

# Errors that mean "the link is sick", worth a close + reopen: the transport
# layer's own errors (SerialTransport wraps every pyserial/termios failure into
# TransportError), plus the retryable DS2 errors the client already retried
# and gave up on. NakResponse / decode / profile errors are deterministic, and
# a CaptureError (disk full, unwritable dir) must stop the run: reopening the
# port cannot fix any of them, so they stay fatal.
LINK_ERRORS: tuple[type[BaseException], ...] = (
    TransportError,
    ds2.Timeout,
    ds2.ChecksumError,
    ds2.EchoMismatch,
)


class SampleWriter:
    """CSV/JSONL sample sink; flushes after every row so `tail -f` works and a
    crash or a killed burst never leaves a 0-byte file.

    Gap markers (after an outage, written just before the first new sample):
      CSV   a row with `t` (time the link failed) and every param column empty
            — same column count as a sample, so csv/pandas consumers keep
            working; plotting tools break the line at the empty row.
      JSONL {"event": "reconnect", "t": ..., "gap_s": ..., "port": ..., "error": ...}
    """

    def __init__(self, fh: IO[str], specs: list[ms41.ParamSpec], as_csv: bool) -> None:
        self.fh = fh
        self.names = [p.name for p in specs]
        self._csv = csv.writer(fh) if as_csv else None
        if self._csv is not None:
            self._csv.writerow(["t", *(p.name if p.verified else f"{p.name}?" for p in specs)])
            self.fh.flush()

    def sample(self, t: float, values: dict[str, ms41.Value]) -> None:
        if self._csv is not None:
            self._csv.writerow(
                [f"{t:.3f}"] + [f"{values[n].value:.4g}" if n in values else "" for n in self.names]
            )
        else:
            params = {n: {"value": v.value, "verified": v.verified} for n, v in values.items()}
            row = {"t": round(t, 3), "params": params}
            self.fh.write(json.dumps(row) + "\n")
        self.fh.flush()

    def gap(self, t: float, gap_s: float, port: str, error: str) -> None:
        if self._csv is not None:
            self._csv.writerow([f"{t:.3f}", *([""] * len(self.names))])
        else:
            event = {
                "event": "reconnect",
                "t": round(t, 3),
                "gap_s": round(gap_s, 3),
                "port": port,
                "error": error,
            }
            self.fh.write(json.dumps(event) + "\n")
        self.fh.flush()


def find_port(
    configured: str,
    exists: Callable[[str], bool] = lambda p: Path(p).exists(),
    candidates: Callable[[], list[str]] = lambda: sorted(glob.glob("/dev/ttyUSB*")),
) -> str | None:
    """Which device node to (re)open, or None to keep waiting.

    The configured port wins if present. If it is gone and it is a
    /dev/ttyUSB* node (the FTDI may re-enumerate under a new number), accept
    any /dev/ttyUSB* — but only if exactly one exists; ambiguity means wait.
    """
    if exists(configured):
        return configured
    if configured.startswith("/dev/ttyUSB"):
        found = candidates()
        if len(found) == 1:
            return found[0]
    return None


Opener = Callable[[str], Transport]


class DataLogger:
    """Poll → write loop with prophylactic burst reopen and auto-reconnect.

    Owns the transport handed to it (and every one it opens); `close()` is
    idempotent and safe on any exit path, including Ctrl-C while waiting for
    the device to come back. `written` / `reconnects` stay readable after a
    KeyboardInterrupt.
    """

    def __init__(
        self,
        opener: Opener,
        transport: Transport,
        port: str,
        profile: ms41.Profile,
        reads: list[ms41.ReadRequest],
        writer: SampleWriter,
        *,
        samples: int = 0,
        rate: float = 10.0,
        burst: int = DEFAULT_BURST,
        reconnect: bool = True,
        stats: live.TimingStats | None = None,
        latency_check: Callable[[str], str | None] | None = None,
        warn: Callable[[str], None] = lambda msg: None,
        find: Callable[[str], str | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.opener = opener
        self.transport: Transport | None = transport
        self.client: ds2.DS2Client | None = ds2.DS2Client(transport)
        self.configured_port = port
        self.port = port
        self.profile = profile
        self.reads = reads
        self.writer = writer
        self.samples = samples
        self.min_period = 1.0 / rate if rate > 0 else 0.0
        self.burst = burst
        self.reconnect = reconnect
        self.stats = stats
        self.latency_check = latency_check
        self.warn = warn
        # Resolved at construction (not def) time so tests can monkeypatch.
        self.find = find if find is not None else find_port
        self.clock = clock
        self.sleep = sleep if sleep is not None else time.sleep
        self.written = 0
        self.reconnects = 0
        self.reopens = 0  # prophylactic burst reopens

    # -- link management ------------------------------------------------------

    def close(self) -> None:
        if self.transport is not None:
            close_quietly(self.transport)  # a dead device may refuse even close()
        self.transport = None
        self.client = None

    def _open(self, port: str) -> None:
        self.transport = self.opener(port)
        self.client = ds2.DS2Client(self.transport)
        self.port = port

    def _wait_for_device(self) -> str:
        """Block until a usable device node exists. Ctrl-C propagates."""
        announced = False
        while True:
            port = self.find(self.configured_port)
            if port is not None:
                return port
            if not announced:
                self.warn(
                    f"{_stamp()} waiting for {self.configured_port} to reappear "
                    "(replug the cable if it does not; Ctrl-C to stop)"
                )
                announced = True
            self.sleep(RECONNECT_POLL_S)

    # -- main loop ------------------------------------------------------------

    def run(self) -> int:
        t0 = self.clock()
        last_t = 0.0  # t of the last real sample (0 before the first)
        down_t: float | None = None  # t when the current outage began
        down_err = ""
        since_open = 0
        while self.samples <= 0 or self.written < self.samples:
            try:
                if self.client is None:
                    port = self._wait_for_device()
                    self._open(port)
                    if self.latency_check is not None:
                        problem = self.latency_check(port)
                        if problem:
                            self.warn(f"{_stamp()} warning: FTDI latency timer: {problem}")
                    since_open = 0
                elif self.burst > 0 and since_open >= self.burst:
                    self.close()
                    self.reopens += 1
                    self._open(self.port)  # quick: no waiting unless it is gone
                    since_open = 0
                start = self.clock()
                assert self.client is not None
                values = live.poll_once(self.client, self.profile, self.reads, stats=self.stats)
            except LINK_ERRORS as exc:
                if not self.reconnect:
                    raise
                self.close()
                if down_t is None:
                    down_t = max(self.clock() - t0, last_t)
                    down_err = str(exc)
                    self.warn(
                        f"{_stamp()} warning: link error on {self.port}: {exc} — "
                        "closing port and reconnecting"
                    )
                self.sleep(RECONNECT_POLL_S)
                continue
            t = self.clock() - t0
            if down_t is not None:
                gap_s = t - last_t
                self.writer.gap(down_t, gap_s, self.port, down_err)
                self.reconnects += 1
                self.warn(f"{_stamp()} reconnected on {self.port} after a {gap_s:.1f} s gap")
                down_t = None
            self.writer.sample(t, values)
            last_t = t
            self.written += 1
            since_open += 1
            leftover = self.min_period - (self.clock() - start)
            if leftover > 0:
                self.sleep(leftover)
        return self.written


def latency_problem(port: str) -> str | None:
    """Re-verify/re-apply the FTDI latency timer (doctor's helper); a message
    if it is not 1 ms afterwards, else None. Never raises.

    The sysfs node is keyed by the kernel name, so a symlinked --port
    (/dev/serial/by-id/..., a udev alias) is resolved to its ttyUSBn first.
    """
    res = set_ftdi_latency(os.path.realpath(port), 1)
    return None if res.ok else (res.error or f"latency_timer = {res.after_ms} ms, want 1")


def _stamp() -> str:
    return time.strftime("%H:%M:%S")
