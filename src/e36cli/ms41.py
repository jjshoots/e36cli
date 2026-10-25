"""MS41 data layer: ident parsing, profiles, batched RAM-read planning, decode.

Pure bytes-in / values-out — no transport or framing imports. Addresses and
scalings come from profile TOML files (see data/profiles/) with per-entry
provenance; nothing is verified on a real car until marked so.

Memory read wire format (research/ds2-protocol.md §4.5, [high]):
payload = 06 00 SEG HI LO CNT  — 24-bit big-endian address, CNT <= 0xF8.
RAM multi-byte values are little-endian (telegram batch reads differ — big-endian).
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .formula import compile_formula, decode_raw

MAX_READ_CHUNK = 0xF8
GENERIC_PROFILE_ID = "ms41-generic"

# Request payload builders (frame addr/len/checksum are the DS2 layer's job).
CMD_IDENT = bytes([0x00])
CMD_DTC_PREPARE = bytes([0x04, 0x00])   # returns operating-hours counter; may answer A1 busy
CMD_DTC_READ = bytes([0x04, 0x01])      # stored faults
CMD_DTC_READ_BARE = bytes([0x04])       # alternate form seen in garagediag
CMD_DTC_SHADOW = bytes([0x14, 0x01])    # shadow fault memory (11-byte records)
CMD_DTC_CLEAR = bytes([0x05])           # WRITE operation


class ProfileError(ValueError):
    """Profile data failed to load or validate."""


class DecodeError(ValueError):
    """A response payload didn't match the expected shape (short/long read)."""


@dataclass(frozen=True)
class Ident:
    """Parsed DS2 identification payload (42 ASCII bytes on MS41)."""

    raw: bytes
    ecu_id: str
    hw_index: str | None = None
    coding_index: str | None = None
    diag_index: str | None = None
    bus_index: str | None = None
    mfg_week: str | None = None
    mfg_year: str | None = None
    supplier: str | None = None
    sw_index: str | None = None
    change_index: str | None = None
    serial: str | None = None

    @property
    def isn(self) -> str | None:
        """EWS2 ISN = last 4 digits of the production serial (research §2, [medium])."""
        return self.serial[-4:] if self.serial else None


def parse_ident(data: bytes) -> Ident:
    """Parse the ident payload (bytes after the A0 status byte).

    Layout per research/ms41-data.md §2 [medium]. Tolerant: any length != 42
    yields only ecu_id (first 7 chars) with the raw payload preserved.
    """
    text = data.decode("ascii", errors="replace")
    ecu_id = text[:7]
    if len(data) != 42:
        return Ident(raw=data, ecu_id=ecu_id)
    return Ident(
        raw=data,
        ecu_id=ecu_id,
        hw_index=text[7:9],
        coding_index=text[9:11],
        diag_index=text[11:13],
        bus_index=text[13:15],
        mfg_week=text[15:17],
        mfg_year=text[17:19],
        supplier=text[19:29],
        sw_index=text[29:31],
        change_index=text[31:33],
        serial=text[33:42],
    )


@dataclass(frozen=True)
class ParamSpec:
    name: str
    label: str
    unit: str
    addr: int
    size: int
    formula: str
    source: str
    verified: bool = False
    verified_source: str = ""  # capture file / session that proved this param
    signed: bool = False
    endian: str = "little"  # raw 0x06 RAM reads are little-endian
    mask: int | None = None
    core: bool = False  # dashboard-core subset (default for live/log)
    _fn: Callable[[float], float] = field(repr=False, compare=False, default=None)  # type: ignore[assignment]

    def decode(self, data: bytes) -> "Value":
        raw = decode_raw(data, self.size, signed=self.signed, endian=self.endian)
        x = raw & self.mask if self.mask is not None else raw
        return Value(
            name=self.name,
            label=self.label,
            raw=raw,
            value=self._fn(float(x)),
            unit=self.unit,
            verified=self.verified,
        )


@dataclass(frozen=True)
class Value:
    name: str
    label: str
    raw: int
    value: float
    unit: str
    verified: bool


@dataclass(frozen=True)
class Profile:
    id: str
    description: str
    match_hw: tuple[str, ...]
    params: tuple[ParamSpec, ...]
    source_file: str = ""

    def param(self, name: str) -> ParamSpec:
        for p in self.params:
            if p.name == name:
                return p
        raise KeyError(name)

    @property
    def core_params(self) -> tuple[ParamSpec, ...]:
        return tuple(p for p in self.params if p.core)


@dataclass(frozen=True)
class ReadRequest:
    """One contiguous 0x06 memory read covering one or more params."""

    addr: int   # 24-bit absolute address
    count: int  # bytes to read
    params: tuple[tuple[ParamSpec, int], ...]  # (param, offset within this block)

    def __post_init__(self) -> None:
        if not 0 < self.count <= MAX_READ_CHUNK:
            raise ValueError(f"count {self.count} out of range (1..{MAX_READ_CHUNK:#x})")
        if not 0 <= self.addr <= 0xFFFFFF:
            raise ValueError(f"address {self.addr:#x} not a 24-bit address")


def data_dir() -> Path:
    """Locate the data/ tree: inside the installed package, else the repo root."""
    pkg = Path(__file__).with_name("data")
    if pkg.is_dir():
        return pkg
    repo = Path(__file__).resolve().parents[2] / "data"
    if repo.is_dir():
        return repo
    raise ProfileError("e36cli data directory not found (package data missing?)")


def _load_profile_file(path: Path) -> Profile:
    with path.open("rb") as fh:
        doc = tomllib.load(fh)
    try:
        head = doc["profile"]
        pid = head["id"]
        desc = head["description"]
    except KeyError as exc:
        raise ProfileError(f"{path.name}: missing [profile] field {exc}") from exc

    params: list[ParamSpec] = []
    seen: set[str] = set()
    for entry in doc.get("param", []):
        try:
            spec = _validate_param(entry)
        except (KeyError, ValueError, TypeError) as exc:
            raise ProfileError(f"{path.name}: bad param {entry.get('name', '?')!r}: {exc}") from exc
        if spec.name in seen:
            raise ProfileError(f"{path.name}: duplicate param {spec.name!r}")
        seen.add(spec.name)
        params.append(spec)

    return Profile(
        id=pid,
        description=desc,
        match_hw=tuple(head.get("match_hw", [])),
        params=tuple(params),
        source_file=str(path),
    )


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _validate_param(entry: dict) -> ParamSpec:
    """Build + fully validate one ParamSpec; every defect raises at load time."""
    spec = ParamSpec(
        name=entry["name"],
        label=entry.get("label", entry["name"]),
        unit=entry.get("unit", ""),
        addr=entry["addr"],
        size=entry["size"],
        formula=entry.get("formula", "x"),
        source=entry.get("source", ""),
        verified=entry.get("verified", False),
        verified_source=entry.get("verified_source", ""),
        signed=entry.get("signed", False),
        endian=entry.get("endian", "little"),
        mask=entry.get("mask"),
        core=entry.get("core", False),
    )
    if not isinstance(spec.name, str) or not spec.name:
        raise ValueError("name must be a non-empty string")
    if not _is_int(spec.addr) or not 0 <= spec.addr <= 0xFFFFFF:
        raise ValueError(f"addr must be a 24-bit integer, got {spec.addr!r}")
    if not _is_int(spec.size) or spec.size not in (1, 2, 4):
        raise ValueError(f"size must be 1, 2, or 4, got {spec.size!r}")
    if spec.endian not in ("big", "little"):
        raise ValueError(f"endian must be 'big' or 'little', got {spec.endian!r}")
    if spec.mask is not None and (not _is_int(spec.mask) or spec.mask < 0):
        raise ValueError(f"mask must be a non-negative integer, got {spec.mask!r}")
    if spec.mask is not None and spec.signed:
        raise ValueError("signed + mask is ambiguous (mask a sign-extended value?); pick one")
    if not isinstance(spec.signed, bool) or not isinstance(spec.verified, bool) or not isinstance(spec.core, bool):
        raise ValueError("signed/verified/core must be booleans")
    if not isinstance(spec.verified_source, str):
        raise ValueError(f"verified_source must be a string, got {spec.verified_source!r}")
    if spec.verified and not spec.verified_source:
        raise ValueError("verified = true requires verified_source (SPEC invariant 3)")
    fn = compile_formula(spec.formula)  # FormulaError is a ValueError
    # Probe the compiled formula over the raw range so bad arithmetic
    # (x / 0, overflow to inf) fails at load, not mid-poll.
    hi = float((1 << (spec.size * 8)) - 1)
    for xv in (0.0, 1.0, hi):
        try:
            y = fn(xv)
        except ArithmeticError as exc:
            raise ValueError(f"formula {spec.formula!r} fails at x={xv}: {exc}") from exc
        if not math.isfinite(y):
            raise ValueError(f"formula {spec.formula!r} is non-finite at x={xv}")
    object.__setattr__(spec, "_fn", fn)
    return spec


def load_profiles(directory: Path | None = None) -> dict[str, Profile]:
    directory = directory or (data_dir() / "profiles")
    profiles: dict[str, Profile] = {}
    for path in sorted(directory.glob("*.toml")):
        profile = _load_profile_file(path)
        if profile.id in profiles:
            raise ProfileError(f"duplicate profile id {profile.id!r} in {path.name}")
        profiles[profile.id] = profile
    if not profiles:
        raise ProfileError(f"no profiles found in {directory}")
    return profiles


def match_profile(ident: Ident | str, profiles: dict[str, Profile] | None = None) -> Profile:
    """Select a profile by ident ECU-ID (exact match_hw entry), else generic."""
    profiles = profiles or load_profiles()
    ecu_id = ident if isinstance(ident, str) else ident.ecu_id
    for profile in profiles.values():
        if ecu_id in profile.match_hw:
            return profile
    try:
        return profiles[GENERIC_PROFILE_ID]
    except KeyError:
        raise ProfileError(f"no profile matches ECU id {ecu_id!r} and no generic fallback") from None


def plan_reads(
    profile: Profile,
    max_chunk: int = MAX_READ_CHUNK,
    gap_tolerance: int = 8,
    names: list[str] | None = None,
) -> list[ReadRequest]:
    """Group param addresses into minimal contiguous 0x06 reads.

    Adjacent/overlapping spans merge; a gap <= gap_tolerance is bridged (the
    wasted bytes cost less than another ~10-byte round trip at 960 B/s). A span
    never exceeds max_chunk.
    """
    if not 0 < max_chunk <= MAX_READ_CHUNK:
        raise ValueError(f"max_chunk must be in 1..{MAX_READ_CHUNK:#x}")
    chosen = [p for p in profile.params if names is None or p.name in names]
    if names is not None:
        missing = set(names) - {p.name for p in chosen}
        if missing:
            raise KeyError(f"unknown params: {sorted(missing)}")
    if not chosen:
        return []

    requests: list[ReadRequest] = []
    block: list[ParamSpec] = []
    block_start = block_end = 0

    def flush() -> None:
        if not block:
            return
        count = block_end - block_start
        params = tuple((p, p.addr - block_start) for p in block)
        requests.append(ReadRequest(addr=block_start, count=count, params=params))

    for p in sorted(chosen, key=lambda p: (p.addr, p.size)):
        p_end = p.addr + p.size
        if not block:
            block, block_start, block_end = [p], p.addr, p_end
            continue
        new_end = max(block_end, p_end)
        if p.addr - block_end <= gap_tolerance and new_end - block_start <= max_chunk:
            block.append(p)
            block_end = new_end
        else:
            flush()
            block, block_start, block_end = [p], p.addr, p_end
    flush()
    return requests


def build_read_payload(req: ReadRequest) -> bytes:
    """`06 00 SEG HI LO CNT` — mode 0x00 = read; 24-bit big-endian address."""
    return bytes([
        0x06,
        0x00,
        (req.addr >> 16) & 0xFF,
        (req.addr >> 8) & 0xFF,
        req.addr & 0xFF,
        req.count,
    ])


def decode_reads(profile: Profile, req: ReadRequest, data: bytes) -> dict[str, Value]:
    """Decode a 0x06 response payload (the CNT data bytes) back into param values."""
    if len(data) != req.count:
        raise DecodeError(f"expected {req.count} bytes for read @{req.addr:#x}, got {len(data)}")
    out: dict[str, Value] = {}
    for param, offset in req.params:
        out[param.name] = param.decode(data[offset : offset + param.size])
    return out
