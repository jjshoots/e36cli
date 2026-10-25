"""Simulator tests: byte-exact command handling through the real DS2Client,
fault injection → typed errors, determinism, and capture replay."""

from __future__ import annotations

import random

import pytest

from e36cli import ds2, ms41
from e36cli.capture import CaptureWriter
from e36cli.dtc import decode_dtc_response, decode_hours_counter
from e36cli.sim import SIM_IDENT, SimDtc, SimTransport, SimulatedDME

DME = ds2.ADDR["DME"]


def make_dme(**kw) -> SimulatedDME:
    kw.setdefault("clock", lambda: 0.0)
    kw.setdefault("rng", random.Random(42))
    return SimulatedDME(**kw)


def make_client(dme: SimulatedDME | None = None, **sim_kw) -> ds2.DS2Client:
    transport = SimTransport(dme or make_dme(), **sim_kw)
    # Fast timing for tests: the sim never sleeps, so gaps only slow us down.
    return ds2.DS2Client(transport, ds2.Timing(deadline=0.05, inter_frame_gap=0.0))


# --- command handling -------------------------------------------------------


def test_ident_byte_exact():
    resp = make_client().query(DME, ms41.CMD_IDENT)
    assert resp.ok
    assert resp.data == SIM_IDENT
    ident = ms41.parse_ident(resp.data)
    assert ident.ecu_id == "1437806"
    assert ms41.match_profile(ident).id == "ms41.1"


def test_dtc_read_empty_and_seeded():
    assert decode_dtc_response(make_client().query(DME, ms41.CMD_DTC_READ).data) == []

    dme = make_dme(dtcs=[SimDtc(code=100, status=0x60, frequency=3)])
    faults = decode_dtc_response(make_client(dme).query(DME, ms41.CMD_DTC_READ).data)
    assert len(faults) == 1
    assert faults[0].code == 100
    assert faults[0].present
    assert faults[0].frequency == 3
    assert "unknown" not in faults[0].description  # 100 is a real MS41 code


def test_dtc_prepare_hours_counter():
    dme = make_dme()
    dme.hours_counter = 2345
    resp = make_client(dme).query(DME, ms41.CMD_DTC_PREPARE)
    assert decode_hours_counter(resp.data) == pytest.approx(234.5)


def test_dtc_clear_honored():
    dme = make_dme(dtcs=[SimDtc(code=100)])
    client = make_client(dme)
    assert len(decode_dtc_response(client.query(DME, ms41.CMD_DTC_READ).data)) == 1
    assert client.query(DME, ms41.CMD_DTC_CLEAR).ok
    assert decode_dtc_response(client.query(DME, ms41.CMD_DTC_READ).data) == []


def test_ram_reads_decode_to_plausible_idle():
    dme = make_dme(ambient_c=20.0)
    client = make_client(dme)
    profile = dme.profile
    values: dict[str, ms41.Value] = {}
    for req in ms41.plan_reads(profile):
        resp = client.query(DME, ms41.build_read_payload(req))
        values.update(ms41.decode_reads(profile, req, resp.data))
    assert set(values) == {p.name for p in profile.params}
    assert values["rpm"].value == pytest.approx(800, abs=30)
    assert values["coolant_temp"].value == pytest.approx(20.0, abs=1.0)  # t=0: ambient
    assert values["battery"].value == pytest.approx(13.9, abs=0.2)
    assert not values["rpm"].verified  # nothing verified before a garage session


def test_coolant_warms_with_injected_clock():
    now = {"t": 0.0}
    dme = make_dme(clock=lambda: now["t"], ambient_c=20.0)
    client = make_client(dme)
    spec = dme.profile.param("coolant_temp")
    req = ms41.plan_reads(dme.profile, names=["coolant_temp"])[0]

    def read() -> float:
        resp = client.query(DME, ms41.build_read_payload(req))
        return ms41.decode_reads(dme.profile, req, resp.data)[spec.name].value

    cold = read()
    now["t"] = 600.0  # ten simulated minutes
    assert read() > cold
    now["t"] = 10_000.0
    assert read() == pytest.approx(90.0, abs=1.0)  # clamped at operating temp


def test_bad_ram_address_naks_invalid_parameter():
    with pytest.raises(ds2.NakResponse) as exc:
        make_client().query(DME, bytes([0x06, 0x00, 0x00, 0x10, 0x00, 0x10]))
    assert exc.value.status == 0xA2


def test_unknown_command_naks_ff():
    with pytest.raises(ds2.NakResponse) as exc:
        make_client().query(DME, bytes([0x77]))
    assert exc.value.status == 0xFF


def test_other_addresses_silent():
    with pytest.raises(ds2.Timeout):
        make_client().query(ds2.ADDR["ABS"], b"\x00", timing=ds2.Timing(deadline=0.02, retries=0))


def test_determinism_same_seed_same_bytes():
    def run() -> bytes:
        dme = SimulatedDME(clock=lambda: 7.0, rng=random.Random(7))
        client = make_client(dme)
        out = b""
        for req in ms41.plan_reads(dme.profile):
            out += client.query(DME, ms41.build_read_payload(req)).data
        return out

    assert run() == run()


# --- fault injection ---------------------------------------------------------


def frame_req() -> tuple[int, bytes]:
    return DME, ms41.CMD_IDENT


@pytest.mark.parametrize("kind", ["drop", "delay", "truncate"])
def test_starving_faults_timeout_then_retry_succeeds(kind):
    transport = SimTransport(make_dme())
    transport.inject(kind, at=0)
    client = ds2.DS2Client(transport, ds2.Timing(deadline=0.02, inter_frame_gap=0.0))
    assert client.query(*frame_req()).data == SIM_IDENT  # retry recovered

    transport2 = SimTransport(make_dme())
    transport2.inject(kind, at=0)
    strict = ds2.DS2Client(transport2, ds2.Timing(deadline=0.02, retries=0, inter_frame_gap=0.0))
    with pytest.raises(ds2.Timeout):
        strict.query(*frame_req())


def test_corrupt_checksum_retried_then_strict_raises():
    transport = SimTransport(make_dme())
    transport.inject("corrupt", at=0)
    client = ds2.DS2Client(transport, ds2.Timing(deadline=0.02, inter_frame_gap=0.0))
    assert client.query(*frame_req()).data == SIM_IDENT

    transport2 = SimTransport(make_dme())
    transport2.inject("corrupt", at=0)
    strict = ds2.DS2Client(transport2, ds2.Timing(deadline=0.02, retries=0, inter_frame_gap=0.0))
    with pytest.raises(ds2.ChecksumError):
        strict.query(*frame_req())


def test_garbage_resynced_within_single_attempt():
    transport = SimTransport(make_dme())
    transport.inject("garbage", at=0)
    strict = ds2.DS2Client(transport, ds2.Timing(deadline=0.05, retries=0, inter_frame_gap=0.0))
    assert strict.query(*frame_req()).data == SIM_IDENT


def test_probabilistic_faults_seeded():
    transport = SimTransport(make_dme(), rng=random.Random(1))
    transport.inject("drop", p=0.5)
    client = ds2.DS2Client(transport, ds2.Timing(deadline=0.02, retries=3, inter_frame_gap=0.0))
    # With retries the stream stays usable despite a lossy wire.
    for _ in range(5):
        assert client.query(*frame_req()).data == SIM_IDENT


def test_unknown_fault_kind_rejected():
    with pytest.raises(ValueError):
        SimTransport(make_dme()).inject("gremlins")


# --- replay ------------------------------------------------------------------


def test_replay_serves_recorded_session_verbatim(tmp_path):
    writer = CaptureWriter("sim", tmp_path)
    live = ds2.DS2Client(
        SimTransport(make_dme(dtcs=[SimDtc(code=100)]), capture=writer),
        ds2.Timing(deadline=0.05, inter_frame_gap=0.0),
    )
    ident_data = live.query(DME, ms41.CMD_IDENT).data
    dtc_data = live.query(DME, ms41.CMD_DTC_READ).data
    writer.close()

    (capture_file,) = tmp_path.glob("*.jsonl")
    replay = ds2.DS2Client(
        SimTransport.from_capture(capture_file), ds2.Timing(deadline=0.05, inter_frame_gap=0.0)
    )
    assert replay.query(DME, ms41.CMD_IDENT).data == ident_data
    assert replay.query(DME, ms41.CMD_DTC_READ).data == dtc_data
    with pytest.raises(ds2.Timeout):  # not in the recording → silence
        replay.query(DME, bytes([0x06, 0x00, 0x00, 0xDA, 0x2A, 0x02]), timing=ds2.Timing(deadline=0.02, retries=0))
