"""`e36 panel`: the everything-dashboard.

Ident header (read once), every profile param, decoded state bits, the faults
panel, and interactive keys: q = quit, c = clear DTCs (with an explicit in-TUI
confirmation). The clear itself runs on the Poller thread — the K-line is
single-master, so the panel never touches the wire directly.
"""

from __future__ import annotations

import sys

from rich.console import Console, Group, RenderableType
from rich.text import Text

from . import ds2, live, ms41, writes

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
        self.paused = False  # the panel never pauses; run_session asks

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

    parts += render_clear_status(store, controller, "keys: q quit · c clear faults")
    return Group(*parts)


def render_clear_status(
    store: live.LiveStore, controller: PanelController, keys_hint: str
) -> list[RenderableType]:
    """Last clear outcome + the confirmation banner (or the key hint).

    Shared by panel and dashboard so the write-path wording lives once.
    """
    parts: list[RenderableType] = []
    clear = store.clear_snapshot()
    if clear is not None:
        msg, ok = clear
        parts.append(Text(msg, style="green" if ok else "red"))
    if controller.state == "confirm":
        banner = f"{writes.CLEAR_QUESTION} Press y to confirm, any other key to cancel."
        parts.append(Text(banner.upper(), style="bold white on red"))
    else:
        parts.append(Text(keys_hint, style="dim"))
    return parts


def run_panel(
    client: ds2.DS2Client,
    profile: ms41.Profile,
    ident: ms41.Ident | None,
    console: Console,
    rate: float = 10.0,
    dtc_interval: float = 10.0,
    stats: live.TimingStats | None = None,
    frames: int | None = None,
) -> None:
    """Interactive panel until q/Ctrl-C (or `frames` rendered frames: CI/testing).

    Raises live.LiveFatal if polling dies.
    """
    store = live.LiveStore()
    poller = live.Poller(
        client, profile, store, rate=rate, stats=stats, names=None, dtc_interval=dtc_interval
    )
    controller = PanelController(poller)
    live.run_session(
        poller,
        lambda: render_panel(profile, ident, store, controller, dtc_interval),
        console,
        controller=controller,
        interactive=frames is None and sys.stdin.isatty(),
        frames=frames,
    )
