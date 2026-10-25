"""Replay-golden tests against real captures from the car (garage session 1,
2026-10-25, E36 M52B25 with ECU ID 1429373, engine idling).

These are the ground-truth regression tests: the fixture bytes came off the
K-line, so a failure here means the decode stack no longer matches reality.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from e36cli import dtc as dtcmod
from e36cli.capture import CaptureReader
from e36cli.cli import CAPTURE_DIR_ENV, app

FIXTURES = Path(__file__).parent / "fixtures"

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
    result = replay("car-live-once.jsonl", "live", "--once", "--json")
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
    # the 8 garage-verified params no longer carry the unverified marker
    for name in ("rpm", "maf", "iat", "coolant_temp", "vss", "tps", "ignition_advance", "vanos_angle"):
        assert p[name]["verified"] is True, name


def test_car_live_once_table_has_no_unverified_marker_on_promoted_params():
    result = replay("car-live-once.jsonl", "live", "--once")
    assert result.exit_code == 0, result.output
    assert "705" in result.output
    # promoted params render without '?'
    rpm_line = next(l for l in result.output.splitlines() if "Engine RPM" in l)
    assert "?" not in rpm_line
