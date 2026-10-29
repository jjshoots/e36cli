import time

import pytest

from e36cli.capture import CaptureReader, CaptureWriter
from e36cli.transport import (
    SerialTransport,
    Transport,
    TransportTimeout,
    ftdi_latency_sysfs_path,
    set_ftdi_latency,
)


class FakeSerial:
    """Scripted serial double: each read() returns the next chunk (or b'')."""

    def __init__(self, chunks=()):
        self.chunks = list(chunks)
        self.written = bytearray()
        self.timeout = None
        self.timeouts_seen = []
        self.input_flushed = 0
        self.closed = False

    def write(self, data):
        self.written.extend(data)
        return len(data)

    def flush(self):
        pass

    def read(self, n):
        self.timeouts_seen.append(self.timeout)
        if self.chunks:
            chunk = self.chunks.pop(0)
            return chunk[:n]
        # emulate a blocking read that times out
        time.sleep(min(self.timeout or 0, 0.005))
        return b""

    def reset_input_buffer(self):
        self.input_flushed += 1

    def close(self):
        self.closed = True


def make_transport(chunks=(), capture=None):
    fake = FakeSerial(chunks)
    t = SerialTransport("/dev/fake", capture=capture, ser=fake)
    return t, fake


def test_satisfies_protocol():
    t, _ = make_transport()
    assert isinstance(t, Transport)


def test_send_writes_bytes():
    t, fake = make_transport()
    t.send(b"\x12\x04\x00\x16")
    assert bytes(fake.written) == b"\x12\x04\x00\x16"


def test_recv_assembles_dribbled_bytes():
    t, _ = make_transport(chunks=[b"\x12", b"", b"\x04\x00", b"\x16"])
    assert t.recv(4, deadline=1.0) == b"\x12\x04\x00\x16"


def test_recv_timeout_raises_with_partial():
    t, _ = make_transport(chunks=[b"\x12"])
    start = time.monotonic()
    with pytest.raises(TransportTimeout) as exc_info:
        t.recv(4, deadline=0.05)
    assert time.monotonic() - start < 1.0  # no runaway wait
    assert exc_info.value.partial == b"\x12"


def test_recv_shrinks_remaining_timeout():
    t, fake = make_transport(chunks=[b"\x01", b"\x02"])
    t.recv(2, deadline=0.5)
    assert len(fake.timeouts_seen) == 2
    assert all(ts is not None and 0 < ts <= 0.5 for ts in fake.timeouts_seen)
    assert fake.timeouts_seen[1] <= fake.timeouts_seen[0]


def test_flush_and_close_delegate():
    t, fake = make_transport()
    t.flush_input()
    t.close()
    assert fake.input_flushed == 1
    assert fake.closed


def test_capture_hook_records_tx_and_rx(tmp_path):
    cap = CaptureWriter("/dev/fake", directory=tmp_path)
    t, _ = make_transport(chunks=[b"\xa0", b"\x01"], capture=cap)
    t.send(b"\x12\x04\x00\x16")
    t.recv(2, deadline=1.0)
    cap.close()

    r = CaptureReader(cap.path)
    assert [(e.dir, e.data) for e in r.events] == [
        ("tx", b"\x12\x04\x00\x16"),
        ("rx", b"\xa0"),
        ("rx", b"\x01"),
    ]


def test_ftdi_sysfs_path():
    assert str(ftdi_latency_sysfs_path("/dev/ttyUSB0")) == (
        "/sys/bus/usb-serial/devices/ttyUSB0/latency_timer"
    )


def test_set_ftdi_latency_missing_device():
    res = set_ftdi_latency("/dev/ttyUSB99")
    assert res.error is not None
    assert not res.ok


def test_set_ftdi_latency_roundtrip(tmp_path, monkeypatch):
    sysfs = tmp_path / "ttyUSB0" / "latency_timer"
    sysfs.parent.mkdir()
    sysfs.write_text("16\n")
    monkeypatch.setattr("e36cli.transport.ftdi_latency_sysfs_path", lambda dev: sysfs)
    res = set_ftdi_latency("/dev/ttyUSB0")
    assert res.before_ms == 16
    assert res.after_ms == 1
    assert res.ok


def test_set_ftdi_latency_already_set(tmp_path, monkeypatch):
    sysfs = tmp_path / "latency_timer"
    sysfs.write_text("1\n")
    monkeypatch.setattr("e36cli.transport.ftdi_latency_sysfs_path", lambda dev: sysfs)
    res = set_ftdi_latency("/dev/ttyUSB0")
    assert res.ok and res.before_ms == 1


def test_flush_input_wraps_non_oserror_as_transport_error():
    """termios.error (not an OSError) must not escape flush_input (seen live
    when the USB device vanished mid-session, car/research/1429373-probe.md)."""
    import pytest

    from e36cli.transport import SerialTransport, TransportError

    class TermiosLikeError(Exception):
        pass

    class FakeSer:
        timeout = 0.1

        def reset_input_buffer(self):
            raise TermiosLikeError(5, "Input/output error")

        def close(self):
            pass

    tr = SerialTransport("/dev/fake", ser=FakeSer())
    with pytest.raises(TransportError):
        tr.flush_input()
