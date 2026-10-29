"""`e36 log` resilience: per-row flush, burst reopen, auto-reconnect on FTDI drops.

No hardware: a FlakySerial double sits under the REAL SerialTransport (so the
pyserial-SerialException → TransportError wrapping is exercised) and serves
bytes from a SimTransport around one shared SimulatedDME (the "car" outlives
every cable reopen, like the real one).
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
import serial
from typer.testing import CliRunner

from e36cli import cli, datalog, live, ms41
from e36cli.cli import CAPTURE_DIR_ENV, app
from e36cli.sim import SimTransport, SimulatedDME
from e36cli.transport import LatencyResult, SerialTransport

runner = CliRunner()

# the autouse fixture stubs datalog.latency_problem; keep the real one
_REAL_LATENCY_PROBLEM = datalog.latency_problem

FTDI_DROP = (
    "device reports readiness to read but returned no data "
    "(device disconnected or multiple access on port?)"
)


@pytest.fixture(autouse=True)
def fast_reconnect(tmp_path, monkeypatch):
    monkeypatch.setenv(CAPTURE_DIR_ENV, str(tmp_path / "captures"))
    monkeypatch.setattr(datalog, "RECONNECT_POLL_S", 0.0)
    # Never touch real sysfs from tests; record what the CLI asks for.
    calls: list[str] = []

    def fake_latency(port: str) -> str | None:
        calls.append(port)
        return None

    monkeypatch.setattr(datalog, "latency_problem", fake_latency)
    return calls


class FlakySerial:
    """pyserial double: raises SerialException after `fail_after` reads."""

    def __init__(self, dme: SimulatedDME, fail_after: int | None = None, junk: bytes = b""):
        self.sim = SimTransport(dme)
        self.fail_after = fail_after
        self.reads = 0
        self.timeout = None
        self.closed = False
        self._junk = junk  # stray bytes ahead of the first echo after open

    def write(self, data):
        if self.closed:
            raise serial.SerialException("write on closed port")
        self.sim.send(data)
        if self._junk:
            self.sim._queue[0:0] = self._junk
            self._junk = b""
        return len(data)

    def flush(self):
        pass

    def read(self, n):
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            raise serial.SerialException(FTDI_DROP)
        q = self.sim._queue
        chunk = bytes(q[:n])
        del q[:n]
        return chunk

    def reset_input_buffer(self):
        # A fresh open must not flush away junk injected *after* the send.
        self.sim._queue.clear()

    def close(self):
        self.closed = True


class FakePort:
    """Stands in for cli.make_transport: open #i fails per `plan[i]`."""

    def __init__(self, plan=(), junk_on_reopen: bytes = b"", on_open=None):
        self.dme = SimulatedDME()
        self.plan = list(plan)
        self.junk_on_reopen = junk_on_reopen
        self.on_open = on_open
        self.opens: list[str] = []
        self.serials: list[FlakySerial] = []

    def __call__(self, cfg, capture=None):
        i = len(self.opens)
        self.opens.append(cfg.port)
        if self.on_open is not None:
            self.on_open(i)
        fail_after = self.plan[i] if i < len(self.plan) else None
        ser = FlakySerial(self.dme, fail_after, junk=self.junk_on_reopen if i else b"")
        self.serials.append(ser)
        return SerialTransport(cfg.port, capture=capture, ser=ser)


@pytest.fixture
def port_node(tmp_path):
    node = tmp_path / "ttyFAKE0"
    node.write_text("")
    return node


def invoke(*args: str):
    return runner.invoke(app, list(args))


def read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    rows = list(csv.reader(path.open()))
    return rows[0], rows[1:]


def is_gap(row: list[str]) -> bool:
    return all(cell == "" for cell in row[1:])


# Reads per sample for the default (core) plan: ident + 1 poll is plenty to
# stay under; fail mid-way through the 4th sample of the first open.
def reads_for(samples: int) -> int:
    profile = ms41.load_profiles()["ms41.1"]
    n_requests = len(live.plan(profile, names=live.select_names(profile)))
    return 3 + n_requests * 3 * samples  # ~3 serial reads per request (+ ident)


# --- CLI: reconnect ----------------------------------------------------------


def test_log_survives_ftdi_drop_with_gap_marker(tmp_path, port_node, monkeypatch, fast_reconnect):
    out = tmp_path / "drive.csv"
    snapshots: dict[int, str] = {}

    def on_open(i):  # proves per-row flush: rows are on disk mid-run
        if out.exists():
            snapshots[i] = out.read_text()

    fake = FakePort(plan=[reads_for(3) + 4], on_open=on_open)
    monkeypatch.setattr(cli, "make_transport", fake)
    result = invoke(
        "--port", str(port_node), "log", str(out), "--samples", "8", "--rate", "0", "--burst", "0"
    )
    assert result.exit_code == 0, result.output
    header, rows = read_csv(out)
    assert header[0] == "t"
    gaps = [i for i, r in enumerate(rows) if is_gap(r)]
    assert len(gaps) == 1
    real = [r for r in rows if not is_gap(r)]
    assert len(real) == 8  # --samples counts real rows only
    assert 0 < gaps[0] < len(rows) - 1  # rows before AND after the gap
    ts = [float(r[0]) for r in rows]
    assert ts == sorted(ts)  # t monotonic across the reconnect
    assert all(len(r) == len(header) for r in rows)  # gap row keeps column count
    assert len(fake.opens) == 2 and fake.opens[1] == str(port_node)
    assert fast_reconnect == [str(port_node)]  # latency re-applied on reconnect
    # flushed per row: when the reconnect reopened, pre-gap rows were on disk
    assert snapshots[1].count("\n") == 1 + gaps[0]
    assert "link error" in result.output and FTDI_DROP in result.output
    assert "reconnected on" in result.output
    assert "Wrote 8 sample(s)" in result.output


def test_log_jsonl_reconnect_event(tmp_path, port_node, monkeypatch):
    out = tmp_path / "drive.jsonl"
    fake = FakePort(plan=[reads_for(2) + 4])
    monkeypatch.setattr(cli, "make_transport", fake)
    result = invoke(
        "--port", str(port_node), "log", str(out), "--samples", "5", "--rate", "0", "--burst", "0"
    )
    assert result.exit_code == 0, result.output
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    events = [r for r in rows if r.get("event") == "reconnect"]
    samples = [r for r in rows if "params" in r]
    assert len(samples) == 5
    assert len(events) == 1
    ev = events[0]
    assert ev["port"] == str(port_node)
    assert ev["gap_s"] >= 0
    assert FTDI_DROP in ev["error"]
    ts = [r["t"] for r in rows]
    assert ts == sorted(ts)


def test_log_no_reconnect_fails_fast(tmp_path, port_node, monkeypatch):
    out = tmp_path / "drive.csv"
    fake = FakePort(plan=[reads_for(2) + 4])
    monkeypatch.setattr(cli, "make_transport", fake)
    result = invoke(
        "--port",
        str(port_node),
        "log",
        str(out),
        "--samples",
        "8",
        "--rate",
        "0",
        "--burst",
        "0",
        "--no-reconnect",
    )
    assert result.exit_code == 1
    assert FTDI_DROP in " ".join(result.output.split())  # the old one-line error
    assert len(fake.opens) == 1
    _, rows = read_csv(out)
    assert rows and not any(is_gap(r) for r in rows)  # what we got is kept


def test_log_waits_for_reenumerated_device(tmp_path, monkeypatch):
    # Configured node vanishes; the FTDI comes back as a different ttyUSBn.
    out = tmp_path / "drive.csv"
    fake = FakePort(plan=[reads_for(2) + 4])
    monkeypatch.setattr(cli, "make_transport", fake)
    answers = iter([None, None, "/dev/ttyUSB7"])
    monkeypatch.setattr(datalog, "find_port", lambda configured: next(answers))
    result = invoke("log", str(out), "--samples", "4", "--rate", "0", "--burst", "0")
    assert result.exit_code == 0, result.output
    assert fake.opens == ["/dev/ttyUSB0", "/dev/ttyUSB7"]
    assert "waiting for /dev/ttyUSB0" in result.output
    assert result.output.count("waiting for") == 1  # announced once, not per poll
    _, rows = read_csv(out)
    assert sum(is_gap(r) for r in rows) == 1


def test_log_ctrl_c_while_waiting_exits_cleanly(tmp_path, port_node, monkeypatch):
    out = tmp_path / "drive.csv"
    fake = FakePort(plan=[reads_for(2) + 4])
    monkeypatch.setattr(cli, "make_transport", fake)
    calls = {"n": 0}

    def gone_then_ctrl_c(configured):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        raise KeyboardInterrupt

    monkeypatch.setattr(datalog, "find_port", gone_then_ctrl_c)
    result = invoke("--port", str(port_node), "log", str(out), "--rate", "0", "--burst", "0")
    assert result.exit_code == 0, result.output
    assert "Wrote 2 sample(s)" in result.output
    assert fake.serials[0].closed
    _, rows = read_csv(out)
    assert len(rows) == 2 and not any(is_gap(r) for r in rows)


# --- CLI: burst reopen -------------------------------------------------------


def test_log_burst_reopens_every_n_samples(tmp_path, port_node, monkeypatch, fast_reconnect):
    out = tmp_path / "burst.csv"
    # stray byte ahead of the echo on every fresh open: the DS2 client's
    # tolerant echo strip must eat it
    fake = FakePort(junk_on_reopen=b"\x00")
    monkeypatch.setattr(cli, "make_transport", fake)
    result = invoke(
        "--port", str(port_node), "log", str(out), "--samples", "10", "--rate", "0", "--burst", "3"
    )
    assert result.exit_code == 0, result.output
    assert len(fake.opens) == 4  # initial + after samples 3, 6, 9
    assert all(s.closed for s in fake.serials[:-1])
    assert fake.serials[-1].closed  # closed on exit too
    _, rows = read_csv(out)
    assert len(rows) == 10 and not any(is_gap(r) for r in rows)  # contiguous
    ts = [float(r[0]) for r in rows]
    assert ts == sorted(ts)
    assert fast_reconnect == []  # burst reopen is quick: no latency/wait dance
    assert "link error" not in result.output


def test_log_burst_zero_never_reopens(tmp_path, port_node, monkeypatch):
    fake = FakePort()
    monkeypatch.setattr(cli, "make_transport", fake)
    out = tmp_path / "x.csv"
    result = invoke(
        "--port", str(port_node), "log", str(out), "--samples", "7", "--rate", "0", "--burst", "0"
    )
    assert result.exit_code == 0, result.output
    assert len(fake.opens) == 1


def test_log_one_capture_session_across_reopens(tmp_path, port_node, monkeypatch):
    monkeypatch.setattr(cli, "make_transport", FakePort(plan=[reads_for(2) + 4]))
    out = tmp_path / "x.csv"
    result = invoke(
        "--port", str(port_node), "log", str(out), "--samples", "6", "--rate", "0", "--burst", "2"
    )
    assert result.exit_code == 0, result.output
    assert len(list((tmp_path / "captures").glob("*.jsonl"))) == 1


def test_log_sim_with_burst_still_works(tmp_path):
    out = tmp_path / "sim.csv"
    result = invoke("--sim", "log", str(out), "--samples", "5", "--rate", "0", "--burst", "2")
    assert result.exit_code == 0, result.output
    _, rows = read_csv(out)
    assert len(rows) == 5


def test_log_rejects_negative_burst(tmp_path):
    result = invoke("--sim", "log", str(tmp_path / "x.csv"), "--burst", "-1")
    assert result.exit_code == 1
    assert "--burst" in result.output


def test_log_help_documents_burst_and_reconnect():
    result = invoke("log", "--help")
    assert result.exit_code == 0
    text = " ".join(result.output.split())
    assert "--burst" in text and "--no-reconnect" in text
    assert "gap" in text


# --- units -------------------------------------------------------------------


def test_sample_writer_flushes_every_row(tmp_path):
    profile = ms41.load_profiles()["ms41.1"]
    specs = list(profile.params[:2])
    path = tmp_path / "f.csv"
    with path.open("w", newline="") as fh:
        w = datalog.SampleWriter(fh, specs, as_csv=True)
        assert path.stat().st_size > 0  # header on disk immediately
        size = path.stat().st_size
        w.sample(0.5, {})
        assert path.stat().st_size > size  # row on disk before close
        size = path.stat().st_size
        w.gap(1.0, 2.0, "/dev/ttyUSB0", "boom")
        assert path.stat().st_size > size
    lines = path.read_text().splitlines()
    assert lines[-1] == "1.000,,"


def test_sample_writer_jsonl_flushes_and_marks_gap():
    class CountingIO(io.StringIO):
        flushes = 0

        def flush(self):
            CountingIO.flushes += 1
            super().flush()

    fh = CountingIO()
    w = datalog.SampleWriter(fh, [], as_csv=False)
    w.sample(0.0, {})
    w.gap(0.1, 55.3, "/dev/ttyUSB1", "gone")
    assert CountingIO.flushes == 2
    ev = json.loads(fh.getvalue().splitlines()[1])
    assert ev == {
        "event": "reconnect",
        "t": 0.1,
        "gap_s": 55.3,
        "port": "/dev/ttyUSB1",
        "error": "gone",
    }


def test_find_port_prefers_configured():
    assert datalog.find_port("/dev/ttyUSB0", exists=lambda p: True) == "/dev/ttyUSB0"


def test_find_port_falls_back_to_single_ttyusb():
    got = datalog.find_port(
        "/dev/ttyUSB0", exists=lambda p: False, candidates=lambda: ["/dev/ttyUSB1"]
    )
    assert got == "/dev/ttyUSB1"


def test_find_port_waits_when_ambiguous_or_none():
    two = lambda: ["/dev/ttyUSB1", "/dev/ttyUSB2"]  # noqa: E731
    assert datalog.find_port("/dev/ttyUSB0", exists=lambda p: False, candidates=two) is None
    assert datalog.find_port("/dev/ttyUSB0", exists=lambda p: False, candidates=list) is None


def test_find_port_no_fallback_for_non_ttyusb_paths():
    got = datalog.find_port(
        "/dev/serial/by-id/usb-FTDI", exists=lambda p: False, candidates=lambda: ["/dev/ttyUSB1"]
    )
    assert got is None


def test_logger_nak_is_still_fatal():
    # Deterministic DS2 errors (NAK) are not link errors: reopening can't fix them.
    from e36cli import ds2

    profile = ms41.load_profiles()["ms41.1"]
    dme = SimulatedDME()
    t = SimTransport(dme)
    bad = [ms41.ReadRequest(addr=0x0100, count=2, params=())]  # outside the sim's RAM window
    w = datalog.SampleWriter(io.StringIO(), [], as_csv=True)
    logger = datalog.DataLogger(
        lambda port: t, t, "sim", profile, bad, w, samples=1, rate=0, sleep=lambda s: None
    )
    with pytest.raises(ds2.NakResponse):
        logger.run()


# --- review regressions --------------------------------------------------------


def test_log_sim_replay_link_error_stays_fatal(tmp_path, monkeypatch):
    # A replay missing a frame used to hang forever "waiting for /dev/ttyUSB0".
    def no_waiting(configured):
        raise AssertionError("sim must never wait for a device node")

    monkeypatch.setattr(datalog, "find_port", no_waiting)
    fixture = Path(__file__).parents[1] / "car" / "captures" / "car-ident.jsonl"
    out = tmp_path / "r.csv"
    result = invoke("--sim-fixture", str(fixture), "log", str(out), "--samples", "2")
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit)  # clean fail(), not a crash
    assert "sim wire silent" in result.output
    assert "waiting for" not in result.output and "link error" not in result.output


class DeadOnCloseSerial(FlakySerial):
    """After the drop, pyserial raises on close() too (dead USB device)."""

    def close(self):
        self.closed = True
        if self.fail_after is not None and self.reads > self.fail_after:
            raise serial.SerialException("close on vanished device")


class TermiosOnTimeoutSerial(FlakySerial):
    """pyserial's timeout setter re-runs tcgetattr: a vanished device raises
    termios.error there (NOT an OSError) before read() is ever reached."""

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, value):
        import termios

        failing = self.fail_after is not None and self.reads >= self.fail_after
        if value is not None and failing:  # (__init__ sets None)
            raise termios.error(5, "Input/output error")
        self._timeout = value


class SerialPort(FakePort):
    def __init__(self, ser_cls, plan=()):
        super().__init__(plan=plan)
        self.ser_cls = ser_cls

    def __call__(self, cfg, capture=None):
        i = len(self.opens)
        self.opens.append(cfg.port)
        fail_after = self.plan[i] if i < len(self.plan) else None
        ser = self.ser_cls(self.dme, fail_after)
        self.serials.append(ser)
        return SerialTransport(cfg.port, capture=capture, ser=ser)


def test_log_ident_drop_with_raising_close_is_a_clean_error(tmp_path, port_node, monkeypatch):
    # USB drops during the ident query and close() then raises too: the user
    # must see the original one-line error, not a SerialException traceback.
    monkeypatch.setattr(cli, "make_transport", SerialPort(DeadOnCloseSerial, plan=[0]))
    result = invoke("--port", str(port_node), "log", str(tmp_path / "x.csv"), "--samples", "2")
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)  # not a SerialException traceback
    assert FTDI_DROP in " ".join(result.output.split())


def test_log_reconnect_survives_raising_close(tmp_path, port_node, monkeypatch):
    fake = SerialPort(DeadOnCloseSerial, plan=[reads_for(2) + 4])
    monkeypatch.setattr(cli, "make_transport", fake)
    out = tmp_path / "x.csv"
    result = invoke(
        "--port", str(port_node), "log", str(out), "--samples", "5", "--rate", "0", "--burst", "0"
    )
    assert result.exit_code == 0, result.output
    assert len(fake.opens) == 2
    _, rows = read_csv(out)
    assert sum(not is_gap(r) for r in rows) == 5 and sum(is_gap(r) for r in rows) == 1


def test_log_reconnects_on_termios_error_from_timeout_setter(tmp_path, port_node, monkeypatch):
    fake = SerialPort(TermiosOnTimeoutSerial, plan=[reads_for(2) + 4])
    monkeypatch.setattr(cli, "make_transport", fake)
    out = tmp_path / "x.csv"
    result = invoke(
        "--port", str(port_node), "log", str(out), "--samples", "5", "--rate", "0", "--burst", "0"
    )
    assert result.exit_code == 0, result.output
    assert len(fake.opens) == 2
    assert "Input/output error" in result.output
    _, rows = read_csv(out)
    assert sum(is_gap(r) for r in rows) == 1


def test_serial_recv_wraps_termios_error_from_timeout_setter():
    from e36cli.transport import TransportError

    ser = TermiosOnTimeoutSerial(SimulatedDME(), fail_after=0)
    t = SerialTransport("/dev/ttyUSB0", ser=ser)
    with pytest.raises(TransportError, match="Input/output error"):
        t.recv(1, 0.1)


def test_latency_problem_resolves_symlinked_port(tmp_path, monkeypatch):
    real = tmp_path / "ttyUSB3"
    real.write_text("")
    alias = tmp_path / "usb-FTDI_FT232R_USB_UART-if00-port0"
    alias.symlink_to(real)
    seen: list[str] = []

    def fake_set(dev_path, ms=1):
        seen.append(dev_path)
        return LatencyResult(None, 1, 1)

    monkeypatch.setattr(datalog, "set_ftdi_latency", fake_set)
    assert _REAL_LATENCY_PROBLEM(str(alias)) is None
    assert seen == [str(real)]
