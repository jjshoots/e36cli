import json

from e36cli.capture import CaptureReader, CaptureWriter, list_sessions


def test_lazy_creation(tmp_path):
    w = CaptureWriter("/dev/ttyUSB0", directory=tmp_path)
    assert w.path is None
    assert list(tmp_path.iterdir()) == []
    w.record("tx", b"\x12\x04\x00")
    assert w.path is not None and w.path.exists()
    w.close()


def test_round_trip(tmp_path):
    with CaptureWriter("/dev/ttyUSB0", directory=tmp_path) as w:
        w.record("tx", b"\x12\x04\x00\x16")
        w.record("rx", b"\x12\x04\x00\x16")  # echo
        w.record("rx", b"\xa0")
        w.record("tx", b"")  # empty: dropped
        path = w.path

    r = CaptureReader(path)
    assert r.header["event"] == "session"
    assert r.header["port"] == "/dev/ttyUSB0"
    assert r.header["version"] == 1
    assert [(e.dir, e.data) for e in r.events] == [
        ("tx", b"\x12\x04\x00\x16"),
        ("rx", b"\x12\x04\x00\x16"),
        ("rx", b"\xa0"),
    ]
    assert r.events[0].t <= r.events[-1].t
    assert r.malformed == 0


def test_hex_encoding_on_disk(tmp_path):
    with CaptureWriter("p", directory=tmp_path) as w:
        w.record("tx", b"\xde\xad\xbe\xef")
        path = w.path
    lines = [json.loads(ln) for ln in path.read_text().splitlines()]
    assert lines[1]["data"] == "deadbeef"
    assert lines[1]["dir"] == "tx"


def test_malformed_lines_tolerated(tmp_path):
    with CaptureWriter("p", directory=tmp_path) as w:
        w.record("rx", b"\x01")
        path = w.path
    with path.open("a") as fh:
        fh.write("not json\n")
        fh.write('{"t": 1, "dir": "rx", "data": "zz"}\n')  # bad hex
    r = CaptureReader(path)
    assert len(r.events) == 1
    assert r.malformed == 2


def test_list_sessions(tmp_path):
    with CaptureWriter("/dev/ttyUSB0", directory=tmp_path) as w:
        w.record("tx", b"\x12\x04")
        w.record("rx", b"\xa0\xa1\xa2")

    sessions = list_sessions(tmp_path)
    assert len(sessions) == 1
    s = sessions[0]
    assert s.port == "/dev/ttyUSB0"
    assert s.n_events == 2
    assert s.bytes_tx == 2
    assert s.bytes_rx == 3


def test_list_sessions_missing_dir(tmp_path):
    assert list_sessions(tmp_path / "nope") == []
