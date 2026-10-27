"""Panel: state-bit decode, controller state machine, clear-on-poller flow."""

from __future__ import annotations

import io
import time

from rich.console import Console

from e36cli import ds2, live, ms41
from e36cli.panel import PanelController, decode_state_bits, render_panel
from e36cli.sim import SimDtc, SimTransport, SimulatedDME


def make_client(dtcs=()):
    dme = SimulatedDME(dtcs=list(dtcs))
    return ds2.DS2Client(SimTransport(dme)), dme


def profile_ms411():
    return ms41.load_profiles()["ms41.1"]


# --- decode_state_bits ------------------------------------------------------


def test_state_bits_throttle_closed_is_inverted_bit0():
    assert "throttle closed" in decode_state_bits(0x00, None)
    assert "throttle closed" not in decode_state_bits(0x01, None)


def test_state_bits_documented_flags():
    s = decode_state_bits(0x02, 0x28)
    assert "full load" in s
    assert "part load" in s and "decel fuel cut" in s
    assert "0x02" in s and "0x28" in s


def test_state_bits_undocumented_bits_stay_raw_hex():
    s = decode_state_bits(0x81, None)  # bit7 undocumented, bit0 = not closed
    assert "0x81" in s
    assert "[" not in s  # no flag list invented


def test_state_bits_missing_params():
    assert decode_state_bits(None, None) == "state bits not in profile"


# --- controller -------------------------------------------------------------


class StubPoller:
    def __init__(self):
        self.cleared = 0

    def request_clear(self):
        self.cleared += 1


def test_controller_quit():
    c = PanelController(StubPoller())
    c.handle_key("q")
    assert c.quit


def test_controller_clear_requires_confirmation():
    stub = StubPoller()
    c = PanelController(stub)
    c.handle_key("c")
    assert c.state == "confirm" and stub.cleared == 0
    c.handle_key("y")
    assert c.state == "run" and stub.cleared == 1


def test_controller_any_other_key_cancels_confirm():
    stub = StubPoller()
    c = PanelController(stub)
    c.handle_key("c")
    c.handle_key("n")
    assert c.state == "run" and stub.cleared == 0
    # and 'q' inside confirm cancels rather than quitting
    c.handle_key("c")
    c.handle_key("q")
    assert not c.quit and stub.cleared == 0


# --- clear flow on the poller thread ---------------------------------------


def test_poller_clear_clears_sim_and_rereads():
    client, _dme = make_client(dtcs=[SimDtc(code=100), SimDtc(code=214)])
    store = live.LiveStore()
    poller = live.Poller(client, profile_ms411(), store, dtc_interval=1000.0)
    # Drive the internals synchronously: initial fault poll, then the clear.
    poller._poll_faults()
    faults, *_ = store.faults_snapshot()
    assert [f.code for f in faults] == [100, 214]
    poller._do_clear()
    msg, ok = store.clear_snapshot()
    assert ok and "cleared" in msg
    faults, *_ = store.faults_snapshot()
    assert faults == []  # immediate re-read happened


def test_poller_clear_via_thread_request():
    client, _ = make_client(dtcs=[SimDtc(code=52)])
    store = live.LiveStore()
    poller = live.Poller(client, profile_ms411(), store, rate=0, dtc_interval=1000.0)
    poller.start()
    try:
        deadline = time.monotonic() + 5
        while store.faults_snapshot()[0] is None and time.monotonic() < deadline:
            time.sleep(0.01)
        poller.request_clear()
        while store.clear_snapshot() is None and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        poller.stop()
        poller.join(timeout=2)
    result = store.clear_snapshot()
    assert result is not None and result[1] is True
    faults, *_ = store.faults_snapshot()
    assert faults == []


# --- render -----------------------------------------------------------------


def render_to_text(renderable) -> str:
    console = Console(file=io.StringIO(), width=120, force_terminal=False)
    console.print(renderable)
    return console.file.getvalue()


def test_render_panel_header_params_and_hints():
    client, _ = make_client()
    profile = profile_ms411()
    store = live.LiveStore()
    store.update(live.poll_once(client, profile))
    ident = ms41.parse_ident(client.query(ds2.ADDR["DME"], ms41.CMD_IDENT).data)
    controller = PanelController(StubPoller())
    text = render_to_text(render_panel(profile, ident, store, controller, 10.0))
    assert "1437806" in text  # ident header
    assert "Engine RPM" in text  # full param table
    assert "state:" in text
    assert "q quit" in text and "c clear" in text


def test_render_panel_confirm_prompt_and_clear_result():
    profile = profile_ms411()
    store = live.LiveStore()
    controller = PanelController(StubPoller())
    controller.handle_key("c")
    text = render_to_text(render_panel(profile, None, store, controller, 0.0))
    assert "CLEAR DME FAULT MEMORY?" in text
    store.set_clear_result("fault memory cleared", ok=True)
    controller.handle_key("x")  # cancel
    text = render_to_text(render_panel(profile, None, store, controller, 0.0))
    assert "fault memory cleared" in text
    assert "CLEAR DME FAULT MEMORY?" not in text
