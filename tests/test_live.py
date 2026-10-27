"""Poller/LiveStore tests against the simulated DME (review finding #8)."""

from __future__ import annotations

import time

import pytest

from e36cli import ds2, live, ms41
from e36cli.sim import SimDtc, SimTransport, SimulatedDME

FAST = ds2.Timing(deadline=0.05, retries=0, inter_frame_gap=0.0)


def make_client() -> ds2.DS2Client:
    return ds2.DS2Client(SimTransport(SimulatedDME()), FAST)


def profile() -> ms41.Profile:
    return ms41.load_profiles()["ms41.1"]


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_poller_publishes_values_and_stops_cleanly():
    store = live.LiveStore()
    poller = live.Poller(make_client(), profile(), store, rate=0)
    poller.start()
    assert wait_for(lambda: store.snapshot()[0])
    poller.stop()
    poller.join(timeout=2.0)
    assert not poller.is_alive()
    assert poller.fatal is None
    values, _ = store.snapshot()
    assert values["rpm"][0].value == pytest.approx(800, abs=30)


def test_poller_recovers_from_transient_fault():
    transport = SimTransport(SimulatedDME())
    transport.inject("drop", at=0)  # first request times out, then clean
    store = live.LiveStore()
    poller = live.Poller(ds2.DS2Client(transport, FAST), profile(), store, rate=0)
    poller.start()
    assert wait_for(lambda: store.snapshot()[0])
    poller.stop()
    poller.join(timeout=2.0)
    assert poller.fatal is None


def test_poller_gives_up_after_consecutive_wire_failures():
    transport = SimTransport(SimulatedDME())
    transport.inject("drop", p=1.0)  # every request starves
    store = live.LiveStore()
    poller = live.Poller(ds2.DS2Client(transport, FAST), profile(), store, rate=0, max_failures=3)
    poller.start()
    poller.join(timeout=10.0)
    assert not poller.is_alive()  # died on its own, nobody called stop()
    assert poller.fatal is not None
    assert "3 consecutive" in poller.fatal
    assert store.fatal == poller.fatal


def test_poller_dies_immediately_on_programming_error(monkeypatch):
    store = live.LiveStore()
    poller = live.Poller(make_client(), profile(), store, rate=0)

    def poisoned(*a, **k):
        raise TypeError("decode bug")

    monkeypatch.setattr(live, "poll_once", poisoned)
    poller.start()
    poller.join(timeout=5.0)
    assert not poller.is_alive()
    assert poller.fatal is not None and "TypeError" in poller.fatal


def test_render_table_filters_to_selected_names():
    store = live.LiveStore()
    p = profile()
    client = make_client()
    store.update(live.poll_once(client, p, live.plan(p)))
    table = live.render_table(p, store, names=["rpm", "coolant_temp"])
    assert table.row_count == 2


def test_poller_interleaves_fault_reads_with_params():
    dme = SimulatedDME(dtcs=[SimDtc(code=25), SimDtc(code=52)])
    store = live.LiveStore()
    poller = live.Poller(
        ds2.DS2Client(SimTransport(dme), FAST), profile(), store, rate=0, dtc_interval=0.01
    )
    poller.start()
    assert wait_for(lambda: store.faults_snapshot()[0] is not None)
    faults, hours_now, ts, error, _ = store.faults_snapshot()
    assert [f.code for f in faults] == [25, 52]
    assert hours_now is not None  # sim serves the prepare/hours counter
    assert error is None
    # Params keep flowing around the interleaved DTC reads.
    assert wait_for(lambda: store.snapshot()[0])
    _, ts0 = store.snapshot()[0]["rpm"]
    assert wait_for(lambda: store.snapshot()[0]["rpm"][1] > ts0)
    # And faults refresh again after the interval.
    assert wait_for(lambda: store.faults_snapshot()[2] > ts)
    poller.stop()
    poller.join(timeout=2.0)
    assert poller.fatal is None


def test_poller_fault_read_failure_is_transient(monkeypatch):
    def boom(client, timing=None, with_hours=True):
        raise ds2.Timeout("dtc wire dry")

    monkeypatch.setattr("e36cli.dtc.fetch_faults", boom)
    store = live.LiveStore()
    poller = live.Poller(make_client(), profile(), store, rate=0, dtc_interval=0.01)
    poller.start()
    assert wait_for(lambda: store.faults_snapshot()[3] is not None)
    assert "dtc wire dry" in store.faults_snapshot()[3]
    assert wait_for(lambda: store.snapshot()[0])  # params unaffected
    poller.stop()
    poller.join(timeout=2.0)
    assert poller.fatal is None  # transient: dashboard stays alive
    assert store.fatal is None


def test_poller_without_dtc_interval_never_fetches_faults():
    store = live.LiveStore()
    poller = live.Poller(make_client(), profile(), store, rate=0, dtc_interval=0.0)
    poller.start()
    assert wait_for(lambda: store.snapshot()[0])
    poller.stop()
    poller.join(timeout=2.0)
    assert store.faults_snapshot() == (None, None, None, None, None)


def test_render_faults_states():
    store = live.LiveStore()
    # Never fetched: placeholder, not a table.
    assert "reading" in live.render_faults(store, 10.0).plain
    # Clean memory.
    store.update_faults([], None)
    assert "No stored faults" in live.render_faults(store, 10.0).plain
    # With faults: a table whose title counts them.
    from e36cli import dtc as dtcmod

    store.update_faults(
        [dtcmod.Dtc(code=25, description="Lambda heater", system="Lambda", status=0x60)], 120.0
    )
    table = live.render_faults(store, 10.0)
    assert "1 stored fault(s)" in str(table.title)
    # Stale + failed reads surface as a note alongside the last-known list.
    store.set_faults_error("wire dry")
    from rich.console import Console

    out = Console(width=120)
    with out.capture() as cap:
        out.print(live.render_faults(store, 1e-6))  # anything is stale at this interval
    assert "read failed" in cap.get() and "last updated" in cap.get()
    assert "25" in cap.get()  # last-known fault list is kept


def test_select_names_precedence():
    p = profile()
    assert live.select_names(p, False, "rpm, maf") == ["rpm", "maf"]
    assert live.select_names(p, True, None) is None
    core = live.select_names(p, False, None)
    assert core == [s.name for s in p.core_params]
