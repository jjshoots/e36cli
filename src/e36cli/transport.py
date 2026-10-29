"""Byte transport layer. SPEC invariants: capture everything, no fixed sleeps.

`recv(n, deadline)` takes a *duration* in seconds; internally it loops on the
underlying read with the remaining time as the timeout, so a slow dribble of
bytes succeeds while a silent wire raises `TransportTimeout` promptly.

Transports move bytes and know nothing about capture: `CapturingTransport`
wraps one and is the single place wire traffic is recorded (STD-02). The CLI's
transport factory always applies it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from .capture import CaptureSink
from .errors import E36Error


class TransportError(E36Error):
    """Base for transport-level failures. `.partial` holds bytes received
    before the failure, so the capture layer can still record them."""

    def __init__(self, msg: str, partial: bytes = b"") -> None:
        super().__init__(msg)
        self.partial = partial


class TransportTimeout(TransportError):
    """Deadline expired before `n` bytes arrived. `.partial` holds what did."""


@runtime_checkable
class Transport(Protocol):
    def send(self, data: bytes) -> None: ...

    def recv(self, n: int, deadline: float) -> bytes: ...

    def flush_input(self) -> bytes:
        """Drop pending input; return the dropped bytes."""
        ...

    def close(self) -> None: ...


class CapturingTransport:
    """Records every byte `inner` sends, receives or discards, and closes the
    capture with it (SPEC invariant 1). The only place capture happens."""

    def __init__(self, inner: Transport, capture: CaptureSink) -> None:
        self._inner = inner
        self._capture = capture

    def send(self, data: bytes) -> None:
        self._capture.record("tx", data)
        self._inner.send(data)

    def recv(self, n: int, deadline: float) -> bytes:
        try:
            data = self._inner.recv(n, deadline)
        except TransportError as exc:
            self._capture.record("rx", exc.partial)
            raise
        self._capture.record("rx", data)
        return data

    def flush_input(self) -> bytes:
        dropped = self._inner.flush_input()
        self._capture.record("rx", dropped, discarded=True)
        return dropped

    def close(self) -> None:
        try:
            self._inner.close()
        finally:
            self._capture.close()


def close_quietly(transport: Transport) -> E36Error | None:
    """Close without letting a close failure mask the error that got us here
    (STD-05): pyserial raises on close() after the USB device vanished.
    Returns the swallowed error for callers that want to mention it."""
    try:
        transport.close()
    except E36Error as exc:
        return exc
    return None


class SerialTransport:
    """pyserial-backed Transport. 9600 8E1 by default (DS2 on K-line).

    `ser` lets tests inject a fake serial object; it must expose `write`,
    `read`, `flush`, `in_waiting`, `reset_input_buffer`, `close`, and a
    writable `timeout`.

    Every pyserial call is wrapped into `TransportError` with `except
    Exception`: on a vanished USB device pyserial raises SerialException (an
    OSError) or a bare termios.error (NOT an OSError — seen live 2026-10-25,
    car/research/1429373-probe.md), from reads, tcdrain and tcgetattr alike.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        parity: str = "E",
        ser: object | None = None,
    ) -> None:
        self.port = port
        if ser is not None:
            self._ser = ser
        else:
            import serial  # deferred so tests never need an open port

            try:
                self._ser = serial.Serial(
                    port=port,
                    baudrate=baudrate,
                    bytesize=serial.EIGHTBITS,
                    parity=parity,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.1,
                    exclusive=True,  # K-line is single-master: refuse a second opener
                )
            except (OSError, serial.SerialException) as exc:
                raise TransportError(f"cannot open {port}: {exc}") from exc

    def send(self, data: bytes) -> None:
        try:
            self._ser.write(data)
            self._ser.flush()  # tcdrain: termios.error on a vanished device
        except Exception as exc:  # see class docstring
            raise TransportError(f"{self.port}: {exc}") from exc

    def recv(self, n: int, deadline: float) -> bytes:
        end = time.monotonic() + deadline
        buf = bytearray()
        while len(buf) < n:
            remaining = end - time.monotonic()
            if remaining <= 0:
                partial = bytes(buf)
                raise TransportTimeout(
                    f"wanted {n} bytes, got {len(partial)} within {deadline:.3f}s", partial
                )
            try:
                # pyserial re-runs tcgetattr/flock on every timeout change, and
                # read() fails on a disconnected cable or a second process
                # reading the same port (see class docstring)
                self._ser.timeout = remaining
                chunk = self._ser.read(n - len(buf))
            except Exception as exc:
                raise TransportError(f"{self.port}: {exc}", bytes(buf)) from exc
            buf.extend(chunk)
        return bytes(buf)

    def flush_input(self) -> bytes:
        try:
            pending = self._ser.in_waiting
            dropped = bytes(self._ser.read(pending)) if pending else b""
            self._ser.reset_input_buffer()
        except Exception as exc:  # see class docstring
            raise TransportError(f"{self.port}: {exc}") from exc
        return dropped

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception as exc:  # see class docstring
            raise TransportError(f"{self.port}: close failed: {exc}") from exc


@dataclass
class LatencyResult:
    """Outcome of reading/setting the FTDI latency timer via sysfs."""

    sysfs_path: Path | None
    before_ms: int | None
    after_ms: int | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.after_ms == 1


def ftdi_latency_sysfs_path(dev_path: str) -> Path:
    name = Path(dev_path).name  # /dev/ttyUSB0 -> ttyUSB0
    return Path("/sys/bus/usb-serial/devices") / name / "latency_timer"


def set_ftdi_latency(dev_path: str, ms: int = 1) -> LatencyResult:
    """Best-effort set of the FTDI latency timer; never raises."""
    sysfs = ftdi_latency_sysfs_path(dev_path)
    try:
        before = int(sysfs.read_text().strip())
    except FileNotFoundError:
        return LatencyResult(
            None, None, None, error=f"{sysfs} not found (not an FTDI usb-serial device?)"
        )
    except (OSError, ValueError) as exc:
        return LatencyResult(sysfs, None, None, error=str(exc))
    if before == ms:
        return LatencyResult(sysfs, before, before)
    try:
        sysfs.write_text(f"{ms}\n")
        after = int(sysfs.read_text().strip())
        return LatencyResult(sysfs, before, after)
    except PermissionError:
        return LatencyResult(
            sysfs,
            before,
            before,
            error=f"no permission to write {sysfs}; fix: echo {ms} | sudo tee {sysfs} "
            f"(or add a udev rule — see `e36 doctor`)",
        )
    except (OSError, ValueError) as exc:
        return LatencyResult(sysfs, before, None, error=str(exc))
