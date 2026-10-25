"""CLI integration tests: every SPEC command exercised via CliRunner + --sim."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from e36cli import ds2, live, ms41
from e36cli.cli import CAPTURE_DIR_ENV, app

runner = CliRunner()


@pytest.fixture(autouse=True)
def capture_dir(tmp_path, monkeypatch):
    directory = tmp_path / "captures"
    monkeypatch.setenv(CAPTURE_DIR_ENV, str(directory))
    return directory


def invoke(*args: str, **kw):
    return runner.invoke(app, list(args), **kw)


# --- read commands -----------------------------------------------------------


def test_ident_shows_ecu_and_profile():
    result = invoke("--sim", "ident")
    assert result.exit_code == 0, result.output
    assert "1437806" in result.output
    assert "ms41.1" in result.output
    assert "2564" in result.output  # ISN from the sim ident serial


def test_scan_lists_dme_as_responder():
    result = invoke("--sim", "scan")
    assert result.exit_code == 0, result.output
    assert "DME" in result.output
    assert "1 module(s) responding" in result.output


def test_dtc_read_empty():
    result = invoke("--sim", "dtc", "read")
    assert result.exit_code == 0, result.output
    assert "No stored fault codes" in result.output


def test_dtc_read_seeded_codes(monkeypatch):
    monkeypatch.setenv("E36CLI_SIM_DTCS", "100,214")
    result = invoke("--sim", "dtc", "read")
    assert result.exit_code == 0, result.output
    assert "100" in result.output and "214" in result.output
    assert "unknown" not in result.output.lower()  # both are real table entries


def test_live_once_renders_params_with_unverified_marker():
    result = invoke("--sim", "live", "--once")
    assert result.exit_code == 0, result.output
    assert "Engine RPM" in result.output
    assert "?" in result.output  # nothing verified pre-garage
    assert "not verified" in result.output


def test_live_json_snapshot_parses():
    result = invoke("--sim", "live", "--json", "--all")
    assert result.exit_code == 0, result.output
    doc = json.loads(result.stdout)
    assert doc["profile"] == "ms41.1"
    assert doc["params"]["rpm"]["value"] == pytest.approx(800, abs=30)
    assert doc["params"]["rpm"]["verified"] is False
    assert set(doc["params"]) == {p.name for p in ms41.load_profiles()["ms41.1"].params}


def test_live_defaults_to_core_subset():
    result = invoke("--sim", "live", "--json")
    assert result.exit_code == 0, result.output
    doc = json.loads(result.stdout)
    core = {p.name for p in ms41.load_profiles()["ms41.1"].core_params}
    assert core  # the shipped profile marks a dashboard core
    assert set(doc["params"]) == core


def test_live_explicit_params_selection():
    result = invoke("--sim", "live", "--json", "--params", "rpm,coolant_temp")
    assert result.exit_code == 0, result.output
    doc = json.loads(result.stdout)
    assert set(doc["params"]) == {"rpm", "coolant_temp"}


def test_live_unknown_param_errors_cleanly():
    result = invoke("--sim", "live", "--json", "--params", "warp_core")
    assert result.exit_code == 1
    assert "unknown param" in result.output
    assert "Traceback" not in result.output


def test_timing_debug_reports_rate_to_stderr():
    result = invoke("--sim", "--timing-debug", "live", "--json")
    assert result.exit_code == 0, result.output
    assert "timing:" in result.output
    assert "requests" in result.output


# --- write guard -------------------------------------------------------------


def test_dtc_clear_requires_confirmation():
    result = invoke("--sim", "dtc", "clear", input="n\n")
    assert result.exit_code == 1
    assert "Aborted" in result.output


def test_dtc_clear_with_yes():
    result = invoke("--sim", "dtc", "clear", "--yes")
    assert result.exit_code == 0, result.output
    assert "cleared" in result.output.lower()


def test_dtc_clear_interactive_confirm():
    result = invoke("--sim", "dtc", "clear", input="y\n")
    assert result.exit_code == 0, result.output
    assert "cleared" in result.output.lower()


# --- logging -----------------------------------------------------------------


def test_log_csv(tmp_path):
    out = tmp_path / "idle.csv"
    result = invoke("--sim", "log", str(out), "--samples", "3", "--rate", "0")
    assert result.exit_code == 0, result.output
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 4  # header + 3 samples
    assert lines[0].startswith("t,")
    assert "rpm?" in lines[0]  # unverified params are marked in the header
    assert "Wrote 3 sample(s)" in result.output


def test_log_jsonl(tmp_path):
    out = tmp_path / "idle.jsonl"
    result = invoke("--sim", "log", str(out), "--samples", "2", "--rate", "0")
    assert result.exit_code == 0, result.output
    rows = [json.loads(line) for line in out.read_text().strip().splitlines()]
    assert len(rows) == 2
    assert rows[0]["params"]["rpm"]["value"] == pytest.approx(800, abs=30)
    assert rows[0]["params"]["rpm"]["verified"] is False


# --- raw + captures ----------------------------------------------------------


def test_raw_accepts_full_canonical_frame():
    result = invoke("--sim", "raw", "12", "04", "00", "16")
    assert result.exit_code == 0, result.output
    assert "TX  12 04 00 16" in result.output
    assert "status 0xA0" in result.output


def test_raw_accepts_bare_addr_payload():
    result = invoke("--sim", "raw", "12", "00")
    assert result.exit_code == 0, result.output
    assert "TX  12 04 00 16" in result.output  # frame built for you


def test_raw_rejects_bad_hex():
    result = invoke("--sim", "raw", "zz")
    assert result.exit_code == 1


def test_captures_lists_and_shows_sessions(capture_dir):
    assert invoke("--sim", "ident").exit_code == 0
    listing = invoke("captures")
    assert listing.exit_code == 0, listing.output
    assert "sim" in listing.output

    shown = invoke("captures", "--show", "1")
    assert shown.exit_code == 0, shown.output
    assert "tx" in shown.output and "12 04 00 16" in shown.output

    assert invoke("captures", "--show", "99").exit_code == 1


def test_sim_replay_fixture_roundtrip(capture_dir, tmp_path):
    assert invoke("--sim", "ident").exit_code == 0
    (session,) = capture_dir.glob("*.jsonl")
    fixture = tmp_path / "golden.jsonl"
    fixture.write_bytes(session.read_bytes())
    result = invoke("--sim-fixture", str(fixture), "ident")
    assert result.exit_code == 0, result.output
    assert "1437806" in result.output


# --- doctor + errors ---------------------------------------------------------


def test_doctor_without_hardware_reports_and_fails():
    result = invoke("--port", "/dev/nonexistent-e36", "doctor")
    assert result.exit_code == 1
    assert "not found" in result.output
    assert "captures dir" in result.output  # soft checks still ran


def test_unknown_profile_errors_cleanly():
    result = invoke("--sim", "--profile", "nope", "live", "--once")
    assert result.exit_code == 1
    assert "unknown profile" in result.output
    assert "Traceback" not in result.output


def test_missing_port_is_one_line_error_not_traceback():
    result = invoke("--port", "/dev/nonexistent-e36", "ident")
    assert result.exit_code == 1
    assert "error:" in result.output
    assert "Traceback" not in result.output


# --- performance budget ------------------------------------------------------


def wire_budget(reads) -> float:
    """Implied poll rate from byte math at 9600 baud, 8E1 (11 bits/byte ≈
    872 B/s). Counts BOTH directions the request occupies the single-wire
    K-line (TX + its echo), the response frame, and the inter-frame gap —
    review finding #2: omitting the echo and gap overstated the rate ~2x."""
    gap = ds2.Timing().inter_frame_gap
    wire_bytes = 0
    for req in reads:
        request = ds2.build_frame(ds2.ADDR["DME"], ms41.build_read_payload(req))
        wire_bytes += 2 * len(request) + (req.count + 4)
    seconds = wire_bytes / (9600 / 11) + len(reads) * gap
    return 1.0 / seconds


def test_poll_wire_budget_full_set():
    """The 29 params span ~9 KB of RAM: 12 batched 0x06 reads ≈ 1.3 Hz at the
    physical limit (echo + gaps included). 10+ Hz needs the 0x0B batch
    telegram (research/ms41-data.md §3.7) — not yet implemented. This pins
    the floor so plan regressions are caught."""
    profile = ms41.load_profiles()["ms41.1"]
    reads = live.plan(profile)
    assert len(reads) <= 12  # 29 params must not mean 29 round trips
    assert wire_budget(reads) >= 1.0


def test_poll_wire_budget_core_subset():
    """The shipped dashboard-core subset (live/log default) must sustain a
    usable refresh rate."""
    profile = ms41.load_profiles()["ms41.1"]
    core = [p.name for p in profile.core_params]
    assert core
    assert wire_budget(live.plan(profile, names=core)) >= 2.5


def test_doctor_sim_skips_hardware_and_passes():
    result = invoke("--sim", "doctor")
    assert result.exit_code == 0, result.output
    assert "simulated" in result.output
    assert "not found" not in result.output


def test_sim_dtcs_env_invalid_is_one_line_error(monkeypatch):
    monkeypatch.setenv("E36CLI_SIM_DTCS", "100,banana")
    result = invoke("--sim", "dtc", "read")
    assert result.exit_code == 1
    assert "E36CLI_SIM_DTCS" in result.output
    assert "Traceback" not in result.output


def test_dtc_read_marks_unverified_descriptions(monkeypatch):
    monkeypatch.setenv("E36CLI_SIM_DTCS", "100")
    result = invoke("--sim", "dtc", "read")
    assert result.exit_code == 0, result.output
    assert "?" in result.output  # db is file-level verified = false pre-garage
    assert "not verified" in result.output


def test_dtc_read_shows_fault_age(monkeypatch):
    # Sim hours counter is 1500 (150.0 h), fault stamp 1200 -> 30.0 h ago.
    monkeypatch.setenv("E36CLI_SIM_DTCS", "214")
    result = invoke("--sim", "dtc", "read")
    assert result.exit_code == 0, result.output
    assert "Age (h)" in result.output
    assert "30.0" in result.output
