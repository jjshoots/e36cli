"""Live data: polling loop, latest-value store, Rich dashboard.

The poller thread owns the transport (SPEC: single-threaded wire access) and
publishes into LiveStore; the render loop only reads the store, so dropped
frames never stall polling.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from rich.console import Console
from rich.live import Live
from rich.table import Table

from . import ds2, ms41

# Profile params are scattered across ~9 KB of RAM; bridging gaps up to this
# many bytes costs less wire time than extra request/response round trips
# (measured over the ms41.1 profile: 12 reads instead of 15).
PLAN_GAP = 16


def plan(profile: ms41.Profile, names: list[str] | None = None) -> list[ms41.ReadRequest]:
    return ms41.plan_reads(profile, gap_tolerance=PLAN_GAP, names=names)


@dataclass
class TimingStats:
    """Per-request latency + achieved poll rate, printed with --timing-debug."""

    requests: int = 0
    total_s: float = 0.0
    worst_s: float = 0.0
    polls: int = 0
    started: float = field(default_factory=time.monotonic)

    def record(self, dt: float) -> None:
        self.requests += 1
        self.total_s += dt
        self.worst_s = max(self.worst_s, dt)

    def summary(self) -> str:
        if not self.requests:
            return "timing: no requests"
        avg = self.total_s / self.requests * 1000
        elapsed = max(time.monotonic() - self.started, 1e-6)
        rate = self.polls / elapsed
        return (
            f"timing: {self.requests} requests, avg {avg:.1f} ms, "
            f"worst {self.worst_s * 1000:.1f} ms, {self.polls} polls ({rate:.1f} Hz)"
        )


def poll_once(
    client: ds2.DS2Client,
    profile: ms41.Profile,
    reads: list[ms41.ReadRequest] | None = None,
    stats: TimingStats | None = None,
) -> dict[str, ms41.Value]:
    """One full read of every profile param, batched per plan()."""
    values: dict[str, ms41.Value] = {}
    for req in reads if reads is not None else plan(profile):
        t0 = time.monotonic()
        resp = client.query(ds2.ADDR["DME"], ms41.build_read_payload(req))
        if stats is not None:
            stats.record(time.monotonic() - t0)
        values.update(ms41.decode_reads(profile, req, resp.data))
    if stats is not None:
        stats.polls += 1
    return values


class LiveStore:
    """Thread-safe latest-value store with per-param timestamps."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, tuple[ms41.Value, float]] = {}
        self.error: str | None = None

    def update(self, values: dict[str, ms41.Value]) -> None:
        now = time.monotonic()
        with self._lock:
            self.error = None
            for name, v in values.items():
                self._values[name] = (v, now)

    def set_error(self, msg: str) -> None:
        with self._lock:
            self.error = msg

    def snapshot(self) -> tuple[dict[str, tuple[ms41.Value, float]], str | None]:
        with self._lock:
            return dict(self._values), self.error


class Poller(threading.Thread):
    """Polls as fast as the wire allows (capped by `rate`), owns the transport."""

    def __init__(
        self,
        client: ds2.DS2Client,
        profile: ms41.Profile,
        store: LiveStore,
        rate: float = 10.0,
        stats: TimingStats | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.client = client
        self.profile = profile
        self.store = store
        self.min_period = 1.0 / rate if rate > 0 else 0.0
        self.stats = stats
        self.stop_event = threading.Event()
        self._plan = plan(profile)

    def run(self) -> None:
        while not self.stop_event.is_set():
            start = time.monotonic()
            try:
                self.store.update(poll_once(self.client, self.profile, self._plan, self.stats))
            except (ds2.DS2Error, Exception) as exc:  # keep polling through glitches
                self.store.set_error(str(exc))
            leftover = self.min_period - (time.monotonic() - start)
            if leftover > 0:
                self.stop_event.wait(leftover)

    def stop(self) -> None:
        self.stop_event.set()


def render_table(profile: ms41.Profile, store: LiveStore) -> Table:
    values, error = store.snapshot()
    now = time.monotonic()
    table = Table(title=f"e36 live — {profile.id}", caption="? = not verified on car")
    table.add_column("Param")
    table.add_column("Value", justify="right")
    table.add_column("Unit")
    for spec in profile.params:
        entry = values.get(spec.name)
        if entry is None:
            table.add_row(spec.label, "—", spec.unit)
            continue
        v, ts = entry
        shown = format_value(v)
        age = now - ts
        if age > 1.0:
            shown = f"[dim]{shown} ({age:.0f}s old)[/dim]"
        table.add_row(spec.label, shown, v.unit)
    if error:
        table.caption = f"[red]wire: {error}[/red]"
    return table


def format_value(v: ms41.Value) -> str:
    num = f"{v.value:.0f}" if float(v.value).is_integer() else f"{v.value:.2f}"
    return num if v.verified else f"{num} ?"


def run_dashboard(
    client: ds2.DS2Client,
    profile: ms41.Profile,
    console: Console,
    rate: float = 10.0,
    stats: TimingStats | None = None,
) -> None:
    """Dashboard until Ctrl-C. Render ~8 fps, decoupled from the poller."""
    store = LiveStore()
    poller = Poller(client, profile, store, rate=rate, stats=stats)
    poller.start()
    try:
        with Live(render_table(profile, store), console=console, refresh_per_second=8) as view:
            while True:
                time.sleep(0.125)
                view.update(render_table(profile, store))
    except KeyboardInterrupt:
        pass
    finally:
        poller.stop()
        poller.join(timeout=2.0)
