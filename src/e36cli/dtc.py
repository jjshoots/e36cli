"""MS41 DTC decode: fault records, status flags, freeze-frame values.

Response layout (research/ms41-data.md §4, [medium-high]): payload after the A0
status byte is `<count>` then `count` fixed-size records — 10 bytes for stored
faults (cmd 04 01), 11 for shadow memory (cmd 14 01). Entry size is derived from
the payload length when possible (garagediag observes it varies per module).

Stored record: [0]=code [1]=status flags [2]=frequency [3]=logistics counter
[4:8]=freeze-frame raw bytes [8:10]=operating-hours stamp (BE, x0.1h).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .ms41 import data_dir

STORED_RECORD_SIZE = 10

_FLAG_BITS = (
    (0x01, "short to B+"),
    (0x02, "short to ground"),
    (0x04, "open circuit"),
    (0x10, "emissions relevant"),
    (0x20, "stored after debounce"),
    (0x40, "currently present"),
    (0x80, "sporadic"),
)


class DtcError(ValueError):
    """DTC response could not be decoded."""


@dataclass(frozen=True)
class FreezeFrameScale:
    id: int
    label: str
    unit: str
    a: float
    b: float

    def decode(self, raw: int) -> float:
        return raw * self.a + self.b


@dataclass(frozen=True)
class Dtc:
    code: int
    description: str
    system: str
    status: int
    frequency: int | None = None
    logistics: int | None = None
    freeze_raw: bytes = b""
    hours_raw: int | None = None  # operating-hours stamp, x0.1 h; age needs the current counter

    @property
    def present(self) -> bool:
        return bool(self.status & 0x40)

    @property
    def sporadic(self) -> bool:
        return bool(self.status & 0x80)

    @property
    def flags(self) -> tuple[str, ...]:
        return tuple(name for bit, name in _FLAG_BITS if self.status & bit)

    def hours_ago(self, current_counter: int) -> float | None:
        """Age in hours given the current operating-hours counter (cmd 04 00)."""
        if self.hours_raw is None:
            return None
        return (current_counter - self.hours_raw) * 0.1


@lru_cache(maxsize=1)
def _db(path_str: str | None = None) -> dict:
    path = Path(path_str) if path_str else data_dir() / "dtc_ms41.toml"
    with path.open("rb") as fh:
        return tomllib.load(fh)


def describe(code: int) -> tuple[str, str]:
    """(description, system) for a code; unknown codes get a stable fallback."""
    entry = _db().get("codes", {}).get(str(code))
    if entry is None:
        return (f"unknown fault code {code}", "Unknown")
    return (entry["text"], entry.get("system", ""))


def freeze_frame_scales() -> dict[int, FreezeFrameScale]:
    return {
        row["id"]: FreezeFrameScale(
            id=row["id"], label=row["label"], unit=row["unit"], a=row["a"], b=row["b"]
        )
        for row in _db().get("freeze_frame", [])
    }


def decode_freeze_value(env_id: int, raw: int) -> tuple[float, str, str] | None:
    """Decode one freeze-frame byte given its environment ID → (value, unit, label)."""
    scale = freeze_frame_scales().get(env_id)
    if scale is None:
        return None
    return (scale.decode(raw), scale.unit, scale.label)


def decode_dtc_response(data: bytes) -> list[Dtc]:
    """Decode a DTC read payload (bytes after the A0 status byte).

    Handles the stock empty response `00 00` (count 0 + pad), 10-byte stored
    records, 11-byte shadow records, and — like garagediag — derives the entry
    size from the payload when it divides evenly.
    """
    if not data:
        raise DtcError("empty DTC payload")
    count = data[0]
    rest = data[1:]
    if count == 0:
        return []
    if rest and len(rest) % count == 0:
        size = len(rest) // count
    else:
        size = STORED_RECORD_SIZE
    if size < 2 or len(rest) < count * size:
        raise DtcError(f"malformed DTC payload: count={count}, {len(rest)} record bytes")

    out: list[Dtc] = []
    for i in range(count):
        e = rest[i * size : (i + 1) * size]
        description, system = describe(e[0])
        out.append(
            Dtc(
                code=e[0],
                description=description,
                system=system,
                status=e[1],
                frequency=e[2] if size > 2 else None,
                logistics=e[3] if size > 3 else None,
                freeze_raw=bytes(e[4:8]) if size >= 8 else b"",
                hours_raw=int.from_bytes(e[8:10], "big") if size >= 10 else None,
            )
        )
    return out


def decode_hours_counter(data: bytes) -> float | None:
    """Operating-hours counter from the prepare response (cmd 04 00): bytes [3:5] BE x0.1 h."""
    if len(data) < 5:
        return None
    return int.from_bytes(data[3:5], "big") * 0.1
