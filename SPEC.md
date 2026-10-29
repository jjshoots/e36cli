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
   (`dtc clear`, the panel's `c` key, future activations/adaptation resets)
   require `--yes` or an interactive confirmation. Component activation must
   refuse if engine RPM > 0. Non-DME modules are strictly read-only (ident
   probes only) — never clear/write to IKE/ABS/EWS; the cluster command space
   contains an odometer reset (research/cluster-and-service-reset.md §1c).
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
id = "ms41.1"
description = "MS41.1 (US OBD-II M52)"
match_hw = ["1437806"]    # ident ECU-ID exact match selects this profile

[[param]]
name = "coolant_temp"
label = "Coolant"
unit = "°C"
addr = 0xDA5A             # 24-bit RAM address, read via cmd 0x06
size = 1
formula = "x * 0.75 - 48"  # safe arithmetic on raw value x (no eval of arbitrary code)
source = "https://..."
verified = false
core = true               # optional: dashboard-core subset (live/log default)
# optional: signed, endian ("little" default), mask (signed+mask is rejected)
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
| `e36 scan` | Probe known module addresses (ident only, read-only); shows raw ident bytes; silent IKE/ABS/EWS noted as "may require ADS interface" | no |
| `e36 panel` | Everything-dashboard: ident header, all params, decoded state bits, faults; keys: `q` quit, `c` clear faults (in-TUI `y` confirmation — guarded write on the poller thread) | **c key** |
| `e36 sia` | Guided pin-7→pin-19 service-interval reset walkthrough (oil/inspection; count LED flashes, 7/23; `--timer` countdown). Software cluster reset is a researched NO-GO: see research/cluster-and-service-reset.md | no (no wire traffic) |
| `e36 dtc read` | Read + decode fault codes | no |
| `e36 dtc clear` | Clear fault codes | **yes** |
| `e36 live` | Rich live dashboard (core param set by default; `--all`, `--params a,b`, `--rate`) plus a stored-faults panel (polled every `--dtc-interval` s, default 10; `--no-dtc` hides) | no |
| `e36 live --once` / `--json` | Single snapshot, human or JSON; includes faults (`--no-dtc` skips; JSON gets a `faults` array, or `faults_error` on a failed read) | no |
| `e36 dashboard` | Full-screen tile grid with per-param history sparklines (same selection/DTC flags; `--history N` ring-buffer size; keys: `q` quit, `c` clear faults behind the same in-TUI `y` confirmation as panel, `p` pause rendering, `+`/`-` history window) | **c key** |
| `e36 log OUT.csv` | Stream samples to CSV/JSONL until Ctrl-C (same selection flags; unverified params marked in headers/fields). Rows flushed as written. Resilient by default: `--burst N` closes/reopens the port every N samples (default 40, 0 = never); on a link error it waits for the device to return and resumes into the same file with a gap marker (`--no-reconnect` = fail fast) | no |
| `e36 raw HEX...` | Send arbitrary frame, print hex response (the probe tool) | caution |
| `e36 captures` | List/show capture sessions | no |

Global options: `--port PATH` (default `/dev/ttyUSB0`), `--sim` (simulated
transport) / `--sim-fixture PATH` (capture replay, implies `--sim`),
`--profile ID` (override auto-match), `--timing-debug` (per-request latency
stats to stderr). `e36 log` also takes `--samples N` for bounded runs (real
samples only; gap rows don't count), `--burst N` and `--reconnect/--no-reconnect`.
Env hooks: `E36CLI_CAPTURE_DIR`, `E36CLI_SIM_DTCS` (seed sim fault codes).

Failure policy: the live poller treats wire errors as transient (keeps polling,
gives up after 10 consecutive failed polls) and any other exception as fatal
immediately; either way the dashboard exits non-zero with a one-line message.
Fault polls are interleaved on the SAME poller thread/client (single-master
wire) and are always non-fatal: a failed DTC read keeps the last-known fault
list with a "read failed" note, and in `--once`/`--json` the params still
render. Transports are closed on every CLI exit path (capture files flush per
event).

`e36 log` policy (src/e36cli/datalog.py — CLI/poller layer; the DS2 and
transport layers know nothing of it): link errors (`TransportError`/`OSError`,
incl. pyserial's FTDI-drop `SerialException`, plus `Timeout`/`ChecksumError`/
`EchoMismatch` after the client's retries) close the port, warn one line on
stderr, wait for the device node (the `--port` path; if that is a
`/dev/ttyUSB*` and gone, the only `/dev/ttyUSB*` present; poll 0.5 s; Ctrl-C
exits cleanly), re-apply the 1 ms FTDI latency timer (doctor's helper; warn
only), reopen and resume. NAK / decode / profile errors stay fatal. The outage
is marked once on resume: CSV = a row with `t` (failure time) and every param
column empty (same column count); JSONL = `{"event": "reconnect", "t", "gap_s",
"port", "error"}`. `t` is seconds since the first sample (monotonic clock)
across reconnects. One capture session file per run, across all reopens. The
sim "reopens" the same simulated DME (no device node to lose) and never
reconnects (a replay missing a frame stays a fatal error), so sim output is
unchanged.

## Performance targets

- Wire-limit honesty (9600 baud 8E1 = 11 bits/byte ≈ 872 B/s, and every TX
  byte occupies the wire twice — the K-line echoes it): the full 29-param
  ms41.1 set is 12 batched 0x06 reads → **~1.9 Hz ceiling**; the 11-param
  dashboard core (profile `core = true` flags, the live/log default) is
  8 reads → **~3.5 Hz**. Targets pinned by perf tests: ≥ 1 Hz full set,
  ≥ 2.5 Hz core.
- Path to 10–19 Hz (future, needs on-car validation): the MS41 batch telegram
  (`0B 01` arm address list → `0B 00` poll, 38-byte response) per
  research/ms41-data.md §3.7 — medium confidence, not implemented in v1.
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
  cli.py  live.py  doctor.py  datalog.py (log: writer + burst/reconnect loop)
tests/
```

Python ≥ 3.11. Deps: `pyserial`, `typer`, `rich`. Dev: `pytest`, `hypothesis`.
No async framework — the wire is 960 B/s; threads suffice.

## Open items (filled from research / garage sessions)

- [x] Exact MS41 live-data read mechanism (status group vs RAM read) + offsets
      — RAM reads via 0x06, profiles populated (research/ms41-data.md §3.6)
- [x] Ident response field layout for MS41.x — 42-byte ASCII (research §2)
- [x] DTC read/clear command bytes + response layout — 04 xx / 05 (research §4)
- [x] Status byte semantics (ACK/NAK values) — A0/A1/A2/B0/FF (ds2-protocol §2)
- [x] Verified-on-car markers — garage session 1 (2026-10-25) verified the 8
      core physics params (rpm, maf, iat, coolant, vss, ignition, vanos, tps)
      on ECU 1429373; promoted in ms41.0-1429373 + ms41-generic profiles with
      `verified_source` citing tests/fixtures/car-live-once.jsonl. DTC record
      layout + hours counter also confirmed (research §4.2). Still unverified:
      the other common params (O2 ADCs, knock, idle valve, state bits) and all
      variant-specific addresses.
