"""Byte transport layer. SPEC invariants: capture everything, no fixed sleeps.

`recv(n, deadline)` takes a *duration* in seconds; internally it loops on the
underlying read with the remaining time as the timeout, so a slow dribble of
bytes succeeds while a silent wire raises `TransportTimeout` promptly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from .capture import CaptureWriter


class TransportError(Exception):
    """Base for transport-level failures."""


class TransportTimeout(TransportError):
    """Deadline expired before `n` bytes arrived. `.partial` holds what did."""

    def __init__(self, msg: str, partial: bytes = b"") -> None:
        super().__init__(msg)
        self.partial = partial


@runtime_checkable
class Transport(Protocol):
    def send(self, data: bytes) -> None: ...

    def recv(self, n: int, deadline: float) -> bytes: ...

    def flush_input(self) -> None: ...

    def close(self) -> None: ...


class SerialTransport:
    """pyserial-backed Transport. 9600 8E1 by default (DS2 on K-line).

    `ser` lets tests inject a fake serial object; it must expose `write`,
    `read`, `flush`, `reset_input_buffer`, `close`, and a writable `timeout`.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        parity: str = "E",
        capture: CaptureWriter | None = None,
        ser: object | None = None,
    ) -> None:
        self.port = port
        self._capture = capture
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
        if self._capture is not None:
            self._capture.record("tx", data)
        try:
            self._ser.write(data)
            self._ser.flush()
        except OSError as exc:
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
            self._ser.timeout = remaining
            try:
                chunk = self._ser.read(n - len(buf))
            except OSError as exc:  # pyserial SerialException is an OSError:
                # disconnected cable or a second process reading the same port
                raise TransportError(f"{self.port}: {exc}") from exc
            if chunk:
                if self._capture is not None:
                    self._capture.record("rx", bytes(chunk))
                buf.extend(chunk)
        return bytes(buf)

    def flush_input(self) -> None:
        try:
            self._ser.reset_input_buffer()
        except Exception as exc:  # termios.error is NOT an OSError: it escapes
            # the OSError wrappers when the USB device vanishes mid-session
            # (seen live 2026-10-25, research/1429373-probe.md)
            raise TransportError(f"{self.port}: {exc}") from exc

    def close(self) -> None:
        self._ser.close()
        if self._capture is not None:
            self._capture.close()


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
        return LatencyResult(None, None, None, error=f"{sysfs} not found (not an FTDI usb-serial device?)")
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
