"""`e36 panel`: the everything-dashboard.

Ident header (read once), every profile param, decoded state bits, the faults
panel, and interactive keys: q = quit, c = clear DTCs (with an explicit in-TUI
confirmation). The clear itself runs on the Poller thread — the K-line is
single-master, so the panel never touches the wire directly.
"""

from __future__ import annotations

import select
import sys
import termios
import time
import tty
from typing import Callable

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.table import Table
from rich.text import Text

from . import live, ms41

# Only bits whose meaning research/ms41-data.md §3.6.1 documents are decoded;
# everything else renders as raw hex. "closed throttle" is the INVERSE of
# bit 0 (BimmerStein logger XML: "closed throttle inv").
ENGINE_STATE_BITS = {  # param engine_state_bits @ 0xFD24
    0x02: "full load",
}
OPERATING_STATE_BITS = {  # param operating_state_bits @ 0xFD14
    0x02: "cranking",
    0x08: "part load",
    0x20: "decel fuel cut",
}


def decode_state_bits(engine: int | None, operating: int | None) -> str:
    """Human-readable summary of the two state-bit bytes (documented bits only)."""
    parts: list[str] = []
    if engine is not None:
        flags = ["throttle closed"] if not engine & 0x01 else []
        flags += [name for bit, name in ENGINE_STATE_BITS.items() if engine & bit]
        parts.append(f"engine 0x{engine:02X}" + (f" [{', '.join(flags)}]" if flags else ""))
    if operating is not None:
        flags = [name for bit, name in OPERATING_STATE_BITS.items() if operating & bit]
        parts.append(f"operating 0x{operating:02X}" + (f" [{', '.join(flags)}]" if flags else ""))
    return " · ".join(parts) if parts else "state bits not in profile"


class PanelController:
    """Key handling + confirmation state machine (wire-free, fully testable).

    States: 'run' → ('c') → 'confirm' → ('y') clear requested / (other) 'run'.
    """

    def __init__(self, poller: live.Poller) -> None:
        self.poller = poller
        self.state = "run"
        self.quit = False

    def handle_key(self, key: str) -> None:
        if self.state == "confirm":
            if key.lower() == "y":
                self.poller.request_clear()
            self.state = "run"
            return
        if key.lower() == "q":
            self.quit = True
        elif key.lower() == "c":
            self.state = "confirm"


def render_panel(
    profile: ms41.Profile,
    ident: ms41.Ident | None,
    store: live.LiveStore,
    controller: PanelController,
    dtc_interval: float,
) -> RenderableType:
    parts: list[RenderableType] = []
    head = f"e36 panel — {profile.id} ({profile.description})"
    if ident is not None:
        head += f" · ECU {ident.ecu_id} · SW {ident.sw_index}"
    parts.append(Text(head, style="bold"))

    parts.append(live.render_table(profile, store))

    values, _ = store.snapshot()

    def raw_of(name: str) -> int | None:
        entry = values.get(name)
        return None if entry is None else int(entry[0].raw)

    bits = decode_state_bits(raw_of("engine_state_bits"), raw_of("operating_state_bits"))
    parts.append(Text(f"state: {bits}", style="cyan"))

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
        parts.append(Text("keys: q quit · c clear faults", style="dim"))
    return Group(*parts)


def _tty_keys() -> Callable[[], str | None]:
    """Non-blocking single-key reader for a cbreak-mode TTY."""

    def read_key() -> str | None:
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None

    return read_key


def run_panel(
    client,
    profile: ms41.Profile,
    ident: ms41.Ident | None,
    console: Console,
    rate: float = 10.0,
    dtc_interval: float = 10.0,
    stats: live.TimingStats | None = None,
) -> None:
    """Interactive panel until q/Ctrl-C. Raises live.LiveFatal if polling dies."""
    store = live.LiveStore()
    poller = live.Poller(
        client, profile, store, rate=rate, stats=stats, names=None, dtc_interval=dtc_interval
    )
    controller = PanelController(poller)
    poller.start()

    interactive = sys.stdin.isatty()
    old_attrs = None
    if interactive:
        old_attrs = termios.tcgetattr(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())
    read_key = _tty_keys() if interactive else lambda: None
    try:
        with Live(
            render_panel(profile, ident, store, controller, dtc_interval),
            console=console,
            refresh_per_second=8,
        ) as view:
            while poller.is_alive() and not controller.quit:
                time.sleep(0.125)
                key = read_key()
                if key:
                    controller.handle_key(key)
                view.update(render_panel(profile, ident, store, controller, dtc_interval))
    except KeyboardInterrupt:
        return
    finally:
        if old_attrs is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_attrs)
        poller.stop()
        poller.join(timeout=2.0)
    if poller.fatal:
        raise live.LiveFatal(poller.fatal)
