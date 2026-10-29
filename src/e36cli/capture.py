"""Always-on wire capture: JSONL session files, readable back for replay.

Format (one JSON object per line):
    {"event": "session", "version": 1, "port": "...", "started": "<iso8601>"}
    {"t": <unix ts float>, "dir": "tx"|"rx", "data": "<hex>"}
    {"t": ..., "dir": "rx", "data": "<hex>", "discarded": true}

`discarded` marks bytes that were on the wire but thrown away unread (pending
input flushed before a request: late responses, noise). They are recorded
because SPEC invariant 1 is "every byte", and they are exactly the bytes that
diagnose a flaky K-line; replay ignores them.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Protocol

from .errors import E36Error

CAPTURE_VERSION = 1


class CaptureError(E36Error):
    """The capture could not be written. Always fatal: a run that cannot record
    its wire traffic must stop (SPEC invariant 1), never retry or reconnect."""


class CaptureSink(Protocol):
    """Where wire events go. `CaptureWriter` is the only real implementation."""

    def record(self, direction: str, data: bytes, *, discarded: bool = False) -> None: ...

    def close(self) -> None: ...


def default_capture_dir() -> Path:
    return Path.home() / ".local" / "share" / "e36cli" / "captures"


class CaptureWriter:
    """Appends wire events to a session JSONL file, created lazily.

    One writer = one session file: after close() the writer is spent, and a
    late record() raises instead of silently starting a second file.
    """

    def __init__(self, port: str, directory: Path | None = None) -> None:
        self._port = port
        self._dir = directory if directory is not None else default_capture_dir()
        self._fh: IO[str] | None = None
        self._path: Path | None = None
        self._closed = False

    @property
    def path(self) -> Path | None:
        """Path of the session file, or None if no event has been recorded yet."""
        return self._path

    def _open(self) -> IO[str]:
        if self._fh is None:
            self._dir.mkdir(parents=True, exist_ok=True)
            started = datetime.now()
            path = self._dir / started.strftime("%Y%m%d-%H%M%S.jsonl")
            if path.exists():  # same-second session restart
                path = self._dir / started.strftime("%Y%m%d-%H%M%S-%f.jsonl")
            self._path = path
            self._fh = path.open("a", encoding="ascii")
            header = {
                "event": "session",
                "version": CAPTURE_VERSION,
                "port": self._port,
                "started": started.isoformat(timespec="seconds"),
            }
            self._fh.write(json.dumps(header) + "\n")
            self._fh.flush()
        return self._fh

    def record(self, direction: str, data: bytes, *, discarded: bool = False) -> None:
        if direction not in ("tx", "rx"):
            raise ValueError(f"direction must be 'tx' or 'rx', got {direction!r}")
        if self._closed:
            raise CaptureError(f"capture {self._path or self._dir} recorded after close")
        if not data:
            return
        event: dict[str, object] = {"t": time.time(), "dir": direction, "data": data.hex()}
        if discarded:
            event["discarded"] = True
        try:
            fh = self._open()
            fh.write(json.dumps(event) + "\n")
            fh.flush()
        except OSError as exc:
            raise CaptureError(f"cannot write capture in {self._dir}: {exc}") from exc

    def close(self) -> None:
        self._closed = True
        if self._fh is not None:
            fh, self._fh = self._fh, None
            try:
                fh.close()
            except OSError as exc:
                raise CaptureError(f"cannot close capture {self._path}: {exc}") from exc

    def __enter__(self) -> CaptureWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class KeepOpenCapture:
    """CaptureSink proxy whose close() is a no-op.

    Transports close their capture on close(); `e36 log` reopens the port many
    times but wants ONE capture session file for the whole run. The owner
    closes the real writer at the very end.
    """

    def __init__(self, inner: CaptureSink) -> None:
        self.inner = inner

    def record(self, direction: str, data: bytes, *, discarded: bool = False) -> None:
        self.inner.record(direction, data, discarded=discarded)

    def close(self) -> None:
        pass


@dataclass
class CaptureEvent:
    t: float
    dir: str  # "tx" | "rx"
    data: bytes
    discarded: bool = False


@dataclass
class CaptureReader:
    """Parses a capture JSONL file. Tolerates (and counts) malformed lines."""

    path: Path
    header: dict = field(init=False, default_factory=dict)
    events: list[CaptureEvent] = field(init=False, default_factory=list)
    malformed: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        for line in Path(self.path).read_text(encoding="ascii", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    raise TypeError("not an object")
                if obj.get("event") == "session":
                    self.header = obj
                elif obj["dir"] in ("tx", "rx"):
                    self.events.append(
                        CaptureEvent(
                            t=float(obj["t"]),
                            dir=obj["dir"],
                            data=bytes.fromhex(obj["data"]),
                            discarded=obj.get("discarded") is True,
                        )
                    )
                else:
                    raise ValueError(f"unknown dir {obj['dir']!r}")
            except (ValueError, KeyError, TypeError):
                self.malformed += 1


@dataclass
class SessionInfo:
    path: Path
    started: str
    port: str
    n_events: int
    bytes_tx: int
    bytes_rx: int


def list_sessions(directory: Path | None = None) -> list[SessionInfo]:
    directory = directory if directory is not None else default_capture_dir()
    sessions: list[SessionInfo] = []
    if not directory.is_dir():
        return sessions
    for path in sorted(directory.glob("*.jsonl")):
        reader = CaptureReader(path)
        sessions.append(
            SessionInfo(
                path=path,
                started=str(reader.header.get("started", "?")),
                port=str(reader.header.get("port", "?")),
                n_events=len(reader.events),
                bytes_tx=sum(len(e.data) for e in reader.events if e.dir == "tx"),
                bytes_rx=sum(len(e.data) for e in reader.events if e.dir == "rx"),
            )
        )
    return sessions
