"""Replay-golden tests against real captures from the car in car/ (session 1,
2026-10-25, E36 M52B25 with ECU ID 1429373, engine idling).

These are the ground-truth regression tests: the fixture bytes came off the
K-line, so a failure here means the decode stack no longer matches reality.
"""

from __future__ import annotations

import csv
import json
import re
import statistics
from pathlib import Path

import pytest
from typer.testing import CliRunner

from e36cli import dtc as dtcmod
from e36cli.capture import CaptureReader
from e36cli.cli import CAPTURE_DIR_ENV, app
from e36cli.ms41 import load_profiles

FIXTURES = Path(__file__).parents[1] / "car" / "captures"

runner = CliRunner()


@pytest.fixture(autouse=True)
def capture_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(CAPTURE_DIR_ENV, str(tmp_path / "captures"))


def replay(fixture: str, *args: str):
    return runner.invoke(app, ["--sim-fixture", str(FIXTURES / fixture), *args])


def test_car_ident_matches_1429373_profile():
    result = replay("car-ident.jsonl", "ident")
    assert result.exit_code == 0, result.output
    assert "1429373" in result.output
    assert "ms41.0-1429373" in result.output
    assert "04/96" in result.output  # build week/year
    assert "0000" in result.output  # ISN = serial tail
    assert "generic fallback" not in result.output  # profile now matches


def test_car_dtc_read_codes_flags_and_ages():
    result = replay("car-dtc.jsonl", "dtc", "read")
    assert result.exit_code == 0, result.output
    assert "3 stored fault" in result.output
    for code in ("217", "25", "52"):
        assert re.search(rf"\b{code}\b", result.output)
    # frequencies seen on the car
    for freq in ("1", "13", "41"):
        assert re.search(rf"\b{freq}\b", result.output)
    assert "currently" in result.output  # all three were currently present
    # ages from hours stamps 0x42F7/0x42F7/0x42F9 vs counter 0x43F2
    assert "25.1" in result.output
    assert "24.9" in result.output


def test_car_dtc_payload_decodes_to_exact_records():
    """Decode the raw payload bytes from the capture directly (no CLI)."""
    events = CaptureReader(FIXTURES / "car-dtc.jsonl").events
    rx = b"".join(e.data for e in events if e.dir == "rx")
    # stored-faults response frame: 12 23 A0 <34 payload bytes> ck
    m = rx.find(b"\x12\x23\xa0")
    assert m >= 0
    payload = rx[m + 3 : m + 3 + 0x23 - 4]  # frame len 0x23 minus addr/len/status...
    faults = dtcmod.decode_dtc_response(payload)
    assert [f.code for f in faults] == [217, 25, 52]
    assert [f.frequency for f in faults] == [1, 13, 41]
    assert all(f.present for f in faults)
    assert faults[0].status == 0x78 and faults[1].status == 0x74 and faults[2].status == 0x64
    assert [f.hours_raw for f in faults] == [0x42F7, 0x42F7, 0x42F9]
    # hours counter from the prepare response: 0x43F2 -> ages 25.1/25.1/24.9 h
    ages = [f.hours_ago(0x43F2) for f in faults]
    assert ages == pytest.approx([25.1, 25.1, 24.9])


def test_car_live_once_json_values_are_the_recorded_physics():
    result = replay(
        "car-live-once.jsonl",
        "live",
        "--once",
        "--json",
        "--params",
        "rpm,maf,iat,coolant_temp,vss,ignition_advance,vanos_angle,tps",
    )
    assert result.exit_code == 0, result.output
    doc = json.loads(result.output)
    assert doc["profile"] == "ms41.0-1429373"
    p = doc["params"]
    # exact expectations derived from the capture payload bytes
    assert p["rpm"]["value"] == pytest.approx(705.0)  # raw C1 02 LE
    assert p["maf"]["value"] == pytest.approx(53 * 0.25)  # 13.25 kg/h
    assert p["iat"]["value"] == pytest.approx(119 * 0.747 - 48)  # 40.893 C
    assert p["coolant_temp"]["value"] == pytest.approx(163 * 0.747 - 48)  # 73.761 C
    assert p["vss"]["value"] == 0.0
    assert p["tps"]["value"] == 0.0
    assert p["ignition_advance"]["value"] == pytest.approx(128 * 0.373 - 23.6)  # 24.144
    assert p["vanos_angle"]["value"] == pytest.approx(50 * 0.3745)  # 18.725
    # the 7 garage-verified params no longer carry the unverified marker
    for name in ("rpm", "maf", "iat", "coolant_temp", "vss", "tps", "vanos_angle"):
        assert p[name]["verified"] is True, name
    # 0xE989 was "verified" from this same static raw 128 — demoted after session 3
    assert p["ignition_advance"]["verified"] is False


def test_car_live_once_table_has_no_unverified_marker_on_promoted_params():
    result = replay(
        "car-live-once.jsonl",
        "live",
        "--once",
        "--params",
        "rpm,maf,iat,coolant_temp,vss,ignition_advance,vanos_angle,tps",
    )
    assert result.exit_code == 0, result.output
    assert "705" in result.output
    # promoted params render without '?'
    rpm_line = next(ln for ln in result.output.splitlines() if "Engine RPM" in ln)
    assert "?" not in rpm_line


# --- garage session 3, 2026-10-29: key on, engine off, cold (car/research/session3-coldstart.md)


def koeo_replayable_params() -> str:
    """Every 1429373 param the KOEO --all capture can answer.

    operating_state_bits (0xFD14) was dropped from the profile after the
    capture, so engine_state_bits (0xFD24) now plans as a different 0x06 read
    than the one recorded; everything else replays byte-for-byte.
    """
    profile = load_profiles()["ms41.0-1429373"]
    return ",".join(p.name for p in profile.params if p.name != "engine_state_bits")


def test_car_koeo_live_all_cold_engine_off():
    result = replay(
        "car-koeo-live-all.jsonl",
        "live",
        "--once",
        "--json",
        "--no-dtc",
        "--params",
        koeo_replayable_params(),
    )
    assert result.exit_code == 0, result.output
    doc = json.loads(result.output)
    assert doc["profile"] == "ms41.0-1429373"
    p = doc["params"]
    assert p["rpm"]["value"] == 0.0
    assert p["maf"]["value"] == 0.0
    # cold engine at ambient: coolant and IAT agree (raw 104 both) -> low-end temp scaling
    assert p["coolant_temp"]["value"] == pytest.approx(104 * 0.747 - 48)  # 29.688 C
    assert p["iat"]["value"] == pytest.approx(104 * 0.747 - 48)
    assert p["battery"]["value"] == pytest.approx(114 * 0.10196)  # 11.62 V KOEO
    # stft both banks parked at the 0x8000 zero point with the engine off
    assert p["stft_b1"]["raw"] == 32768
    assert p["stft_b2"]["raw"] == 32768
    # session-3 profile corrections (car/research/session3-coldstart.md §4)
    assert p["ignition_angle"]["raw"] == 0  # 0xE98D: nothing computed engine off
    assert p["knock_retard_global"]["value"] == 0.0  # raw 0 = no retard
    # front O2 inverted ADC span: both banks rest near the lean rail (~4.89 "V")
    assert p["o2_front_b1"]["value"] == pytest.approx(100 - (25576 & 0x3FF) * 100 / 1023)
    assert p["o2_front_b2"]["value"] == pytest.approx(100 - (29673 & 0x3FF) * 100 / 1023)
    assert p["o2_front_b1"]["value"] < 5 and p["o2_front_b2"]["value"] < 5
    assert p["lambda_integrator_b2"]["value"] == pytest.approx(4543 / 4096 * 100 - 100)
    assert p["load"]["value"] == 0.0
    for gone in ("ltft_b1", "ltft_b2", "knock_retard", "operating_state_bits"):
        assert gone not in p


def test_car_koeo_dtc_ages_advanced_frequencies_unchanged():
    result = replay("car-koeo-dtc.jsonl", "dtc", "read")
    assert result.exit_code == 0, result.output
    assert "3 stored fault" in result.output
    for code in ("217", "25", "52"):
        assert re.search(rf"\b{code}\b", result.output)
    # hours counter 0x43F8 (was 0x43F2 on 2026-10-25): ages 25.7/25.7/25.5 h
    assert "25.7" in result.output
    assert "25.5" in result.output


def test_car_koeo_scan_ews_and_gm_answer():
    result = replay("car-koeo-scan.jsonl", "scan")
    assert result.exit_code == 0, result.output
    assert "88 36 22 77" in result.output  # EWS 0x44 ident
    assert "88 36 94 82" in result.output  # GM 0x00 ident
    assert "3 module(s) responding" in result.output


# --- session-3 evidence behind the 1429373 profile corrections (cold start log,
# decoded with the pre-correction profile; raw recovered from the old formulas)


def coldstart_rows() -> list[dict[str, str]]:
    with (FIXTURES / "car-coldstart.csv").open() as fh:
        return list(csv.DictReader(fh))


def test_coldstart_e989_is_static_and_e98d_moves():
    rows = coldstart_rows()
    # old ignition_advance column (0xE989): one value through KOEO, crank and idle
    assert {r["ignition_advance"] for r in rows} == {"24.14"}
    # old knock_retard column (0xE98D, now ignition_angle): raw 0 engine off,
    # several distinct values once running
    raw_e98d = [round(float(r["knock_retard?"]) / 0.375 + 128) for r in rows]
    running = [raw for raw, r in zip(raw_e98d, rows, strict=True) if float(r["rpm"]) > 0]
    assert all(raw == 0 for raw, r in zip(raw_e98d, rows, strict=True) if float(r["rpm"]) == 0)
    assert len(set(running)) >= 4


def test_coldstart_load_scaling_tracks_maf_per_stroke():
    profile = load_profiles()["ms41.0-1429373"]
    load = profile.param("load")
    ratios = []
    for r in coldstart_rows():
        rpm, maf = float(r["rpm"]), float(r["maf"])
        if rpm > 600:
            raw = round(float(r["load?"]) / 0.021195)  # pre-correction formula
            mg_per_stroke = maf * 1e6 / (rpm * 60 * 3)  # 6 cyl, 4-stroke
            ratios.append(load.decode(raw.to_bytes(2, "little")).value / mg_per_stroke)
    assert len(ratios) > 40
    assert statistics.median(ratios) == pytest.approx(1.0, abs=0.05)
    assert all(0.85 < x < 1.2 for x in ratios)


def test_car_captures_have_redacted_serial():
    """The DME ident serial (payload bytes 33..42; its tail is taken to be the
    EWS ISN) must be zeroed in every committed capture — see car/README.md."""
    idents = 0
    for path in FIXTURES.glob("*.jsonl"):
        rx = b"".join(e.data for e in CaptureReader(path).events if e.dir == "rx")
        start = rx.find(b"\x12\x2e\xa0")
        while start >= 0:
            frame = rx[start : start + 0x2E]
            assert frame[3 + 33 : 3 + 42] == b"000000000", path.name
            idents += 1
            start = rx.find(b"\x12\x2e\xa0", start + 1)
    assert idents >= 6
