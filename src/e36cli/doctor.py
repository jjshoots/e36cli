"""Environment checks: port, permissions, FTDI latency, captures dir.

Runs fine with no hardware attached — a missing port is a finding, not a crash.
"""

from __future__ import annotations

import grp
import os
from dataclasses import dataclass
from pathlib import Path

from .capture import default_capture_dir
from .transport import set_ftdi_latency

UDEV_HINT = (
    'udev rule (then replug): echo \'SUBSYSTEM=="usb-serial", DRIVER=="ftdi_sio", '
    "ATTR{latency_timer}=\"1\"' | sudo tee /etc/udev/rules.d/99-e36cli.rules"
)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    hard: bool = True


def _check_port(port: str) -> list[Check]:
    checks: list[Check] = []
    if not Path(port).exists():
        checks.append(Check("port", False, f"{port} not found — cable unplugged?"))
        return checks
    checks.append(Check("port", True, f"{port} present"))
    if os.access(port, os.R_OK | os.W_OK):
        checks.append(Check("permissions", True, f"read/write access to {port}"))
    else:
        try:
            group = grp.getgrgid(os.stat(port).st_gid).gr_name
        except KeyError:
            group = "?"
        checks.append(
            Check(
                "permissions",
                False,
                f"no rw access to {port} (group '{group}'); "
                f"fix: sudo usermod -aG {group} $USER, then re-login",
            )
        )
    return checks


def _check_latency(port: str) -> Check:
    res = set_ftdi_latency(port, 1)
    if res.ok:
        detail = f"latency_timer = 1 ms ({res.sysfs_path})"
        if res.before_ms not in (None, 1):
            detail += f" (was {res.before_ms})"
        return Check("ftdi latency", True, detail, hard=False)
    return Check("ftdi latency", False, f"{res.error}. {UDEV_HINT}", hard=False)


def _check_pyserial() -> Check:
    try:
        import serial

        return Check("pyserial", True, f"version {serial.__version__}", hard=False)
    except ImportError as exc:  # pragma: no cover - deps are pinned
        return Check("pyserial", False, str(exc))


def _check_captures(directory: Path) -> Check:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".doctor-probe"
        probe.write_text("ok")
        probe.unlink()
        return Check("captures dir", True, f"{directory} writable", hard=False)
    except OSError as exc:
        return Check("captures dir", False, f"{directory}: {exc}")


def run_checks(port: str, capture_dir: Path | None = None, sim: bool = False) -> list[Check]:
    if sim:
        checks = [Check("transport", True, "simulated DME (hardware checks skipped)")]
    else:
        checks = _check_port(port)
        if checks[0].ok:
            checks.append(_check_latency(port))
    checks.append(_check_pyserial())
    checks.append(_check_captures(capture_dir or default_capture_dir()))
    return checks


def hard_failure(checks: list[Check]) -> bool:
    return any(not c.ok and c.hard for c in checks)
