# e36cli — Specification (single source of truth)

A high-performance Linux CLI for diagnosing a BMW E36 (M52B25 w/ MS41.x "2.8" DME)
over DS2 on K-line, via a VAG KKL 409.1 cable (FTDI FT232RL) at `/dev/ttyUSB0`.

This file is the contract. Implementation agents: read this fully before writing
code. If reality (the car, or research findings) contradicts this spec, update the
spec in the same change.

## Non-negotiable invariants

1. **Capture everything.** Every byte TX/RX on a real serial port is appended to a
   session capture file (JSONL, timestamped) under `~/.local/share/e36cli/captures/`.
   No flag disables this. Captures are the seed corpus for the simulator.
2. **Reads are free, writes are guarded.** Commands that modify ECU state
   (`dtc clear`, future activations/adaptation resets) require `--yes` or an
   interactive confirmation. Component activation must refuse if engine RPM > 0.
3. **Provenance on every constant.** Every RAM offset, scaling factor, command
   byte, and DTC text in profile data carries `source` and `verified` fields.
   Unverified parameters render with a `?` marker in all output.
4. **The simulator is a Transport.** All code above the transport layer must be
   byte-for-byte indifferent to sim vs real port. Every CLI command must run
   against `--sim`.
5. **Wire discipline.** Single-threaded access to the transport; one in-flight
   request; echo consumed and validated before reading the response; reads driven
   by expected byte counts with deadline, never fixed sleeps.

## Protocol layer (DS2) — see research/ds2-protocol.md for sourced details

- Serial: 9600 baud, 8E1, over K-line. Full echo of transmitted bytes (consume+verify).
- Frame: `[addr] [len] [payload...] [cksum]` where `len` = total frame length
  including addr/len/cksum, and cksum = XOR of all preceding bytes.
- Response: same framing, from the module address. Status byte semantics
  (ACK/NAK/busy) per research doc.
- DME address: 0x12. Other E36 module addresses enumerated in research doc.
- Timeouts/retries: per-request deadline (default 300 ms), up to 2 retries on
  checksum/timeout, with inter-frame gap respected. All tunable in one place
  (`ds2.Timing` dataclass).
- Errors are typed: `EchoMismatch`, `ChecksumError`, `Timeout`, `NakResponse` —
  all subclasses of `DS2Error`.

## Data layer (MS41) — see research/ms41-data.md

- `ident` parses the identification response into fields (part no, HW/SW version,
  coding index). The parsed SW version selects a **profile**.
- Profiles are TOML files in `data/profiles/` (shipped as package data), schema:

```toml
[profile]
id = "ms41.1-stock"
description = "MS41.1 stock (M52B28)"
match_sw = ["..."]        # ident substrings that select this profile

[[param]]
name = "coolant_temp"
label = "Coolant"
unit = "°C"
addr = 0x0000             # or group/offset per the actual read mechanism
size = 1
formula = "x * 0.75 - 48"  # safe arithmetic on raw value x (no eval of arbitrary code)
source = "https://..."
verified = false
```

- Formula strings support only: `x`, numeric literals, `+ - * /`, parentheses,
  and signed/endian handling via `size`/`signed`/`endian` fields. Parsed once at
  profile load into a closure (no `eval`).
- DTC database: `data/dtc_ms41.toml` (code -> text), same provenance fields.
- Unknown profile → fall back to `ms41-generic` with only universally-agreed
  params, and warn.

## Command surface (v1 — complete list, no additions without spec change)

| Command | Does | Writes? |
|---|---|---|
| `e36 doctor` | Check port presence, permissions (dialout), FTDI latency timer, udev hints | no |
| `e36 ident` | Read + parse DME identification, show matched profile | no |
| `e36 scan` | Probe known E36 module addresses, list responders | no |
| `e36 dtc read` | Read + decode fault codes | no |
| `e36 dtc clear` | Clear fault codes | **yes** |
| `e36 live` | Rich live dashboard of profile params (default ~10 Hz) | no |
| `e36 live --once` / `--json` | Single snapshot, human or JSON | no |
| `e36 log OUT.csv` | Stream samples to CSV/JSONL until Ctrl-C | no |
| `e36 raw HEX...` | Send arbitrary frame, print hex response (the probe tool) | caution |
| `e36 captures` | List/show capture sessions | no |

Global options: `--port PATH` (default `/dev/ttyUSB0`), `--sim [FIXTURE]`
(simulated transport, optional capture replay), `--profile ID` (override
auto-match), `--timing-debug` (per-request latency stats to stderr).

## Performance targets

- Full param set refresh ≥ 10 Hz on real hardware (batch RAM reads into the
  fewest frames the protocol allows; budget: 9600 baud ≈ 960 B/s).
- `e36 live` render decoupled from polling (poller thread → latest-value store →
  Rich refresh at 4–10 fps). Dropped frames are fine; stale data must show age
  if > 1 s.
- doctor sets/reports FTDI `latency_timer` (1 ms) via
  `/sys/bus/usb-serial/devices/<dev>/latency_timer`.

## Simulator (`src/e36cli/sim.py`)

- `SimTransport` implements the same `Transport` protocol as the serial one,
  including echo bytes, so the full stack (framing, echo verification, retries)
  exercises identically.
- Behavior model: a `SimulatedDME` with the profile's params backed by a value
  model (idle-ish engine: RPM ~800 with jitter, coolant warming over time),
  correct ident response, a configurable DTC store, honoring clear.
- Fault injection hooks: drop response, corrupt checksum, truncate frame, delay
  past deadline, garbage bytes between frames — used by the transport test matrix.
- Replay mode: feed a capture JSONL; responses come verbatim from the recording
  (request matched by frame bytes).

## Testing contract

- `uv run pytest` green, no hardware, no network. Target: fast (< 10 s).
- Layers: pure unit tests (framing, checksum, formula parsing, DTC decode),
  property tests (round-trip encode/decode, checksum, hypothesis if cheap),
  transport matrix vs fault-injecting sim, CLI integration tests via
  `typer.testing.CliRunner` with `--sim` covering EVERY command in the table.
- Fixtures in `tests/fixtures/`: hand-built frames now; real captures get added
  after the first garage session and become regression goldens.

## Layout

```
pyproject.toml            # uv-managed; console script `e36`
SPEC.md                   # this file
CLAUDE.md                 # agent spin-up notes
GARAGE.md                 # scripted live-session protocol
research/                 # sourced findings (ds2-protocol.md, ms41-data.md)
data/profiles/*.toml      # per-SW-version param maps (package data)
data/dtc_ms41.toml
src/e36cli/
  transport.py  ds2.py  ms41.py  dtc.py  sim.py  capture.py
  cli.py  live.py  doctor.py
tests/
```

Python ≥ 3.11. Deps: `pyserial`, `typer`, `rich`. Dev: `pytest`, `hypothesis`.
No async framework — the wire is 960 B/s; threads suffice.

## Open items (filled from research / garage sessions)

- [ ] Exact MS41 live-data read mechanism (status group vs RAM read) + offsets
- [ ] Ident response field layout for MS41.x
- [ ] DTC read/clear command bytes + response layout
- [ ] Status byte semantics (ACK/NAK values)
- [ ] Verified-on-car markers (all `verified = false` until garage session 1)
