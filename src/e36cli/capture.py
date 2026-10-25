"""Always-on wire capture: JSONL session files, readable back for replay.

Format (one JSON object per line):
    {"event": "session", "version": 1, "port": "...", "started": "<iso8601>"}
    {"t": <unix ts float>, "dir": "tx"|"rx", "data": "<hex>"}
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO

CAPTURE_VERSION = 1


def default_capture_dir() -> Path:
    return Path.home() / ".local" / "share" / "e36cli" / "captures"


class CaptureWriter:
    """Appends wire events to a session JSONL file, created lazily."""

    def __init__(self, port: str, directory: Path | None = None) -> None:
        self._port = port
        self._dir = directory if directory is not None else default_capture_dir()
        self._fh: IO[str] | None = None
        self._path: Path | None = None

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

    def record(self, direction: str, data: bytes) -> None:
        if direction not in ("tx", "rx"):
            raise ValueError(f"direction must be 'tx' or 'rx', got {direction!r}")
        if not data:
            return
        fh = self._open()
        fh.write(json.dumps({"t": time.time(), "dir": direction, "data": data.hex()}) + "\n")
        fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "CaptureWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@dataclass
class CaptureEvent:
    t: float
    dir: str  # "tx" | "rx"
    data: bytes


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
                if obj.get("event") == "session":
                    self.header = obj
                else:
                    self.events.append(
                        CaptureEvent(t=float(obj["t"]), dir=obj["dir"], data=bytes.fromhex(obj["data"]))
                    )
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
