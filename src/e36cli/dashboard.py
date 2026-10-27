"""`e36 dashboard`: full-screen tile grid with per-param history sparklines.

An engine-HUD style view: one tile per parameter showing the current value,
the min/max of the visible window, and a unicode sparkline of recent history.
Polling reuses live.Poller unchanged (single wire consumer, DTC interleave,
guarded clear); this module only adds history recording and rendering.

Keys: q quit · c clear faults (type y to confirm) · p pause rendering ·
+/- grow/shrink the visible history window.
"""

from __future__ import annotations

import sys
import termios
import time
import tty
from collections import deque

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import live, ms41
from .panel import PanelController, _tty_keys

SPARK_GLYPHS = "▁▂▃▄▅▆▇█"

# Tiles narrower than this are unreadable; the grid drops columns instead.
MIN_TILE_WIDTH = 26
MAX_COLUMNS = 4

DEFAULT_HISTORY = 240
MIN_WINDOW = 10
WINDOW_STEP = 30


class HistoryStore(live.LiveStore):
    """LiveStore that also keeps a per-param ring buffer of (ts, value)."""

    def __init__(self, maxlen: int = DEFAULT_HISTORY) -> None:
        super().__init__()
        self.maxlen = maxlen
        self._history: dict[str, deque[tuple[float, float]]] = {}

    def update(self, values: dict[str, ms41.Value]) -> None:
        super().update(values)
        now = time.monotonic()
        with self._lock:
            for name, v in values.items():
                buf = self._history.get(name)
                if buf is None:
                    buf = self._history[name] = deque(maxlen=self.maxlen)
                buf.append((now, float(v.value)))

    def history(self, name: str, window: int | None = None) -> list[tuple[float, float]]:
        """The last `window` samples for `name` (all when window is None)."""
        with self._lock:
            buf = self._history.get(name)
            if not buf:
                return []
            samples = list(buf)
        if window is not None and window < len(samples):
            samples = samples[-window:]
        return samples


def fit_series(values: list[float], width: int) -> list[float]:
    """Resample to at most `width` points (bucket means), preserving order."""
    if width <= 0:
        return []
    n = len(values)
    if n <= width:
        return list(values)
    out: list[float] = []
    for i in range(width):
        lo = i * n // width
        hi = max((i + 1) * n // width, lo + 1)
        bucket = values[lo:hi]
        out.append(sum(bucket) / len(bucket))
    return out


def sparkline(values: list[float], width: int) -> str:
    """Unicode sparkline of `values`, at most `width` glyphs wide.

    A flat series renders mid-height; empty input renders empty.
    """
    series = fit_series(values, width)
    if not series:
        return ""
    lo, hi = min(series), max(series)
    if hi == lo:
        return SPARK_GLYPHS[3] * len(series)
    span = hi - lo
    top = len(SPARK_GLYPHS) - 1
    return "".join(SPARK_GLYPHS[round((v - lo) / span * top)] for v in series)


def grid_columns(term_width: int, tiles: int) -> int:
    """How many tile columns fit: bounded by width, MAX_COLUMNS, tile count."""
    by_width = max(1, term_width // MIN_TILE_WIDTH)
    return max(1, min(by_width, MAX_COLUMNS, tiles))


class DashboardController(PanelController):
    """Panel keys (q/c/confirm) plus p pause and +/- history window."""

    def __init__(self, poller: live.Poller, window: int, max_window: int) -> None:
        super().__init__(poller)
        self.paused = False
        self.window = window
        self.max_window = max_window

    def handle_key(self, key: str) -> None:
        if self.state == "run":
            if key.lower() == "p":
                self.paused = not self.paused
                return
            if key == "+":
                self.window = min(self.window + WINDOW_STEP, self.max_window)
                return
            if key == "-":
                self.window = max(self.window - WINDOW_STEP, MIN_WINDOW)
                return
        super().handle_key(key)


def render_tile(
    spec: ms41.ParamSpec,
    entry: tuple[ms41.Value, float] | None,
    samples: list[tuple[float, float]],
    width: int,
    now: float | None = None,
) -> Panel:
    """One param square: label, big value, window min/max, sparkline."""
    now = time.monotonic() if now is None else now
    label = spec.label if spec.verified else f"{spec.label} ?"
    inner = max(width - 4, 1)  # panel borders + padding

    if entry is None:
        body: RenderableType = Text("—", style="dim", justify="center")
        return Panel(body, title=label, title_align="left", width=width)

    v, ts = entry
    value_line = Text(justify="center")
    value_line.append(live.format_value(v), style="bold bright_white")
    if v.unit:
        value_line.append(f" {v.unit}", style="dim")

    lines: list[RenderableType] = [value_line]
    series = [s[1] for s in samples]
    if series:
        lo, hi = min(series), max(series)
        lines.append(Text(sparkline(series, inner), style="cyan", justify="left"))
        lines.append(Text(f"min {lo:.4g}  max {hi:.4g}", style="dim", justify="center"))
    age = now - ts
    if age > 1.0:
        lines.append(Text(f"stale {age:.0f}s", style="dim yellow", justify="center"))
    return Panel(Group(*lines), title=label, title_align="left", width=width)


def render_grid(
    profile: ms41.Profile,
    store: HistoryStore,
    names: list[str] | None,
    window: int,
    term_width: int,
    now: float | None = None,
) -> Table:
    """The tile grid, re-laid-out for the current terminal width."""
    specs = profile.params if names is None else tuple(p for p in profile.params if p.name in names)
    cols = grid_columns(term_width, len(specs) or 1)
    tile_width = max(term_width // cols, MIN_TILE_WIDTH)
    values, _ = store.snapshot()
    grid = Table.grid()
    for _ in range(cols):
        grid.add_column()
    row: list[RenderableType] = []
    for spec in specs:
        row.append(
            render_tile(
                spec,
                values.get(spec.name),
                store.history(spec.name, window),
                tile_width,
                now=now,
            )
        )
        if len(row) == cols:
            grid.add_row(*row)
            row = []
    if row:
        grid.add_row(*row)
    return grid


def render_screen(
    profile: ms41.Profile,
    store: HistoryStore,
    controller: DashboardController,
    stats: live.TimingStats,
    port: str,
    names: list[str] | None,
    dtc_interval: float,
    term_width: int,
) -> RenderableType:
    parts: list[RenderableType] = []
    elapsed = max(time.monotonic() - stats.started, 1e-6)
    rate = stats.polls / elapsed
    head = (
        f"e36 dashboard — {profile.id} · {port} · {rate:.1f} Hz · "
        f"window {controller.window} · {time.strftime('%H:%M:%S')}"
    )
    if controller.paused:
        head += " · [yellow]PAUSED[/yellow]"
    parts.append(Text.from_markup(head, style="bold"))
    parts.append(render_grid(profile, store, names, controller.window, term_width))
    if dtc_interval > 0:
        parts.append(live.render_faults(store, dtc_interval))
    clear = store.clear_snapshot()
    if clear is not None:
        msg, ok = clear
        parts.append(Text(msg, style="green" if ok else "red"))
    if controller.state == "confirm":
        parts.append(
            Text(
                "CLEAR DME FAULT MEMORY? This is a write to the ECU. press y to "
                "confirm, any other key to cancel",
                style="bold white on red",
            )
        )
    else:
        parts.append(
            Text("keys: q quit · c clear faults · p pause · +/- history window", style="dim")
        )
    return Group(*parts)


def run_dashboard_screen(
    client,
    profile: ms41.Profile,
    console: Console,
    port: str,
    rate: float = 10.0,
    dtc_interval: float = 10.0,
    names: list[str] | None = None,
    history: int = DEFAULT_HISTORY,
    stats: live.TimingStats | None = None,
    frames: int | None = None,
) -> None:
    """Full-screen dashboard until q/Ctrl-C.

    `frames` renders that many frames then exits (CI/testing). Raises
    live.LiveFatal if the poller gives up, so the CLI exits non-zero.
    """
    stats = stats or live.TimingStats()
    store = HistoryStore(maxlen=history)
    poller = live.Poller(
        client, profile, store, rate=rate, stats=stats, names=names, dtc_interval=dtc_interval
    )
    controller = DashboardController(poller, window=history, max_window=history)
    poller.start()

    interactive = frames is None and sys.stdin.isatty()
    old_attrs = None
    if interactive:
        old_attrs = termios.tcgetattr(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())
    read_key = _tty_keys() if interactive else lambda: None

    def frame() -> RenderableType:
        return render_screen(
            profile, store, controller, stats, port, names, dtc_interval, console.size.width
        )

    rendered = 0
    try:
        with Live(frame(), console=console, refresh_per_second=8, screen=interactive) as view:
            while poller.is_alive() and not controller.quit:
                time.sleep(0.125)
                key = read_key()
                if key:
                    controller.handle_key(key)
                if not controller.paused:
                    view.update(frame())
                rendered += 1
                if frames is not None and rendered >= frames:
                    break
    except KeyboardInterrupt:
        return
    finally:
        if old_attrs is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_attrs)
        poller.stop()
        poller.join(timeout=2.0)
    if poller.fatal:
        raise live.LiveFatal(poller.fatal)
