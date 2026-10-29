"""Dashboard: history buffer, sparkline, grid layout, controller, CLI smoke."""

from __future__ import annotations

import time

import pytest
from typer.testing import CliRunner

from e36cli import ds2, live, ms41
from e36cli.cli import app
from e36cli.dashboard import (
    MIN_WINDOW,
    SPARK_GLYPHS,
    DashboardController,
    HistoryStore,
    fit_series,
    grid_columns,
    render_tile,
    sparkline,
)
from e36cli.sim import SimDtc, SimTransport, SimulatedDME


def profile_ms411():
    return ms41.load_profiles()["ms41.1"]


def value(name="rpm", v=800.0):
    return ms41.Value(
        name=name, label="Engine RPM", raw=int(v), value=v, unit="rpm", verified=False
    )


# --- HistoryStore -----------------------------------------------------------


def test_history_appends_per_param():
    store = HistoryStore(maxlen=10)
    store.update({"rpm": value(v=700.0)})
    store.update({"rpm": value(v=720.0)})
    samples = store.history("rpm")
    assert [s[1] for s in samples] == [700.0, 720.0]
    assert all(isinstance(s[0], float) for s in samples)


def test_history_ring_buffer_wraps():
    store = HistoryStore(maxlen=3)
    for v in (1.0, 2.0, 3.0, 4.0, 5.0):
        store.update({"rpm": value(v=v)})
    assert [s[1] for s in store.history("rpm")] == [3.0, 4.0, 5.0]


def test_history_window_slices_latest():
    store = HistoryStore(maxlen=10)
    for v in (1.0, 2.0, 3.0, 4.0):
        store.update({"rpm": value(v=v)})
    assert [s[1] for s in store.history("rpm", window=2)] == [3.0, 4.0]
    assert [s[1] for s in store.history("rpm", window=99)] == [1.0, 2.0, 3.0, 4.0]


def test_history_unknown_param_is_empty():
    assert HistoryStore().history("nope") == []


def test_history_store_still_serves_latest_values():
    store = HistoryStore()
    store.update({"rpm": value(v=750.0)})
    values, error = store.snapshot()
    assert values["rpm"][0].value == 750.0
    assert error is None


# --- fit_series / sparkline -------------------------------------------------


def test_fit_series_passthrough_when_short():
    assert fit_series([1.0, 2.0], 5) == [1.0, 2.0]


def test_fit_series_downsamples_with_bucket_means():
    out = fit_series([0.0, 2.0, 4.0, 6.0], 2)
    assert out == [1.0, 5.0]


def test_fit_series_zero_width():
    assert fit_series([1.0, 2.0], 0) == []


def test_sparkline_maps_min_to_lowest_and_max_to_highest():
    s = sparkline([0.0, 1.0], 10)
    assert s == SPARK_GLYPHS[0] + SPARK_GLYPHS[-1]


def test_sparkline_known_series():
    # evenly spaced 0..7 over 8 glyph levels: one of each
    s = sparkline([float(i) for i in range(8)], 8)
    assert s == SPARK_GLYPHS


def test_sparkline_flatline_renders_mid_height():
    s = sparkline([5.0] * 4, 10)
    assert s == SPARK_GLYPHS[3] * 4


def test_sparkline_empty():
    assert sparkline([], 10) == ""


def test_sparkline_respects_width():
    assert len(sparkline([float(i) for i in range(100)], 15)) == 15


# --- grid layout ------------------------------------------------------------


def test_grid_columns_narrow_terminal_single_column():
    assert grid_columns(25, tiles=8) == 1


def test_grid_columns_scales_with_width():
    assert grid_columns(26 * 2, tiles=8) == 2
    assert grid_columns(26 * 3, tiles=8) == 3


def test_grid_columns_capped_at_max():
    assert grid_columns(1000, tiles=20) == 4


def test_grid_columns_never_exceeds_tile_count():
    assert grid_columns(1000, tiles=2) == 2
    assert grid_columns(1000, tiles=1) == 1


# --- tile rendering ---------------------------------------------------------


def spec_of(profile, name):
    return next(p for p in profile.params if p.name == name)


def render_to_text(renderable, width=40):
    from io import StringIO

    from rich.console import Console

    console = Console(file=StringIO(), width=width, legacy_windows=False)
    console.print(renderable)
    return console.file.getvalue()


def test_tile_without_data_shows_placeholder():
    spec = spec_of(profile_ms411(), "rpm")
    out = render_to_text(render_tile(spec, None, [], 30))
    assert "—" in out
    assert "?" in out  # unverified label marker


def test_tile_shows_value_minmax_and_sparkline():
    spec = spec_of(profile_ms411(), "rpm")
    now = time.monotonic()
    entry = (value(v=800.0), now)
    samples = [(now - 2, 700.0), (now - 1, 750.0), (now, 800.0)]
    out = render_to_text(render_tile(spec, entry, samples, 30, now=now))
    assert "800" in out
    assert "min 700" in out and "max 800" in out
    assert any(g in out for g in SPARK_GLYPHS)
    assert "stale" not in out


def test_tile_marks_stale_data():
    spec = spec_of(profile_ms411(), "rpm")
    now = time.monotonic()
    entry = (value(v=800.0), now - 5.0)
    out = render_to_text(render_tile(spec, entry, [(now - 5.0, 800.0)], 30, now=now))
    assert "stale 5s" in out


# --- controller -------------------------------------------------------------


class StubPoller:
    def __init__(self):
        self.cleared = 0

    def request_clear(self):
        self.cleared += 1


def make_controller(window=240):
    return DashboardController(StubPoller(), window=window, max_window=240)


def test_controller_pause_toggles():
    c = make_controller()
    c.handle_key("p")
    assert c.paused
    c.handle_key("p")
    assert not c.paused


def test_controller_window_grow_shrink_clamped():
    c = make_controller(window=60)
    c.handle_key("-")
    assert c.window == 30
    c.handle_key("-")
    assert c.window == MIN_WINDOW
    for _ in range(20):
        c.handle_key("+")
    assert c.window == 240


def test_controller_inherits_clear_confirm_flow():
    c = make_controller()
    c.handle_key("c")
    assert c.state == "confirm"
    c.handle_key("p")  # anything but y cancels; p must NOT toggle pause here
    assert c.state == "run"
    assert not c.paused
    assert c.poller.cleared == 0
    c.handle_key("c")
    c.handle_key("y")
    assert c.poller.cleared == 1
    c.handle_key("q")
    assert c.quit


def test_controller_clear_via_poller_with_sim():
    dme = SimulatedDME(dtcs=[SimDtc(25), SimDtc(52)])
    client = ds2.DS2Client(SimTransport(dme))
    profile = profile_ms411()
    store = HistoryStore()
    poller = live.Poller(client, profile, store, rate=50.0, dtc_interval=0.05)
    controller = DashboardController(poller, window=240, max_window=240)
    poller.start()
    try:
        deadline = time.monotonic() + 5.0
        while store.faults is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert store.faults and len(store.faults) == 2
        controller.handle_key("c")
        controller.handle_key("y")
        while store.clear_snapshot() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        msg, ok = store.clear_snapshot()
        assert ok, msg
        while store.faults and time.monotonic() < deadline:
            time.sleep(0.02)
        assert store.faults == []
    finally:
        poller.stop()
        poller.join(timeout=2.0)


# --- CLI smoke ---------------------------------------------------------------


runner = CliRunner()


def test_dashboard_cli_sim_renders_frames_non_tty(tmp_path, monkeypatch):
    monkeypatch.setenv("E36CLI_CAPTURE_DIR", str(tmp_path))
    monkeypatch.setenv("E36CLI_SIM_DTCS", "25")
    result = runner.invoke(app, ["--sim", "dashboard", "--frames", "4"])
    assert result.exit_code == 0, result.output
    assert "e36 dashboard" in result.output
    assert "keys:" in result.output


def test_dashboard_cli_unknown_param_one_line_error(tmp_path, monkeypatch):
    monkeypatch.setenv("E36CLI_CAPTURE_DIR", str(tmp_path))
    result = runner.invoke(app, ["--sim", "dashboard", "--frames", "1", "--params", "bogus"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output


def test_dashboard_cli_all_params_and_history(tmp_path, monkeypatch):
    monkeypatch.setenv("E36CLI_CAPTURE_DIR", str(tmp_path))
    result = runner.invoke(
        app, ["--sim", "dashboard", "--frames", "2", "--all", "--history", "50", "--no-dtc"]
    )
    assert result.exit_code == 0, result.output
    assert "stored fault" not in result.output


@pytest.mark.parametrize("history", ["0", "-1"])
def test_dashboard_rejects_nonpositive_history(history):
    from typer.testing import CliRunner

    from e36cli.cli import app

    result = CliRunner().invoke(app, ["--sim", "dashboard", "--history", history, "--frames", "1"])
    assert result.exit_code == 2  # usage error, before any poller exists
