# e36cli — Claude notes

Fully Claude-owned project. Owner: jet. Car: BMW E36, M52B25 engine with an
M52B28 ("2.8") MS41.x DME, possibly tuned. Cable: VAG KKL 409.1, FTDI FT232RL,
`/dev/ttyUSB0`. Host: this Linux box, fish shell, uv-managed Python.

## Spin-up (read in this order)

1. `SPEC.md` — the contract. Command surface, invariants, layer boundaries.
2. `research/` — sourced protocol/data findings with confidence markers.
   Treat [low] confidence facts as hypotheses to verify on the car.
3. `GARAGE.md` — what to do when the laptop is plugged into the car.

## Ground rules learned from planning (don't re-derive)

- The simulator encodes our *beliefs*; only real captures prove correctness.
  Never mark a profile param `verified = true` without a capture to point at.
- K-line echoes every TX byte — all transport code must consume the echo.
- Throughput ceiling is the wire (9600 baud). Optimize frame count, not Python.
- FTDI latency timer must be 1 ms (`e36 doctor` handles it) or everything
  feels broken.
- Writes (dtc clear etc.) are guarded; captures are always-on. See SPEC invariants.

## Dev loop

- `uv sync` then `uv run pytest` (must stay green, no hardware needed).
- `uv run e36 --sim live` etc. — every command works against the simulator.
- Real car: follow GARAGE.md; raw probing via `uv run e36 raw ...`.
- Captures land in `~/.local/share/e36cli/captures/`; copy interesting ones
  into `tests/fixtures/` as goldens.

## State / history

- 2026-10-25: project started. Research agents gathered DS2/MS41 docs into
  `research/` (NB: ms4x.net wiki DS2 pages are empty stubs; real sources were
  RomRaider's Java DS2 code and the BimmerStein-ECU-Tool Python repo).
  Full stack + simulator built; adversarial review pass fixed 13 defects
  (notably: tolerant echo strip, honest wire math, poller failure policy,
  core-param subset); 171 tests; installed via `uv tool install .`.
  Nothing verified on the car yet.
  Perf reality: honest wire math (11 bits/byte + echo) puts 0x06 RAM reads at
  ~1.9 Hz full set / ~3.5 Hz core subset — the 0x0B batch telegram
  (research/ms41-data.md §3.7) is the future 10–19 Hz path, unimplemented
  pending on-car validation.
- 2026-10-25 (later): **garage session 1 done, car talks.** The "2.8" DME is
  NOT the predicted US MS41.1 — ident says **ECU ID 1429373, Euro MS41.0**
  (SW index 59, built 04/96). New profile `ms41.0-1429373` (common params
  only; the logger XML has no 1429373 column for variant-specific addresses —
  no trims/battery/injector-PW until we find or derive them). 8 physics params
  verified at idle and promoted (`verified_source` cites the capture); DTC
  record layout + hours-counter ages confirmed byte-exact (research §4.2 note;
  responses carry a trailing pad byte). Real captures are replay goldens in
  tests/fixtures/ (car-ident/car-dtc/car-live-once) with CLI replay tests.
  Hard lesson: **the K-line is single-master** — a second e36 process on the
  port steals bytes; SerialTransport now opens with exclusive=true.
  Car's stored faults: 217 (EGS CAN), 25 (lambda heater B1), 52 (exhaust flap)
  — all "currently present", left uncleared.
  Next: session 2 (engine running checks per GARAGE.md — throttle-blip
  coherence, log warmup, measure real poll rate); find 1429373 trim/battery
  addresses (RomRaider login-gated sheet? firmware dump?); then the 0x0B
  batch telegram for 10+ Hz.
- 2026-10-25 (later still): owner ran the throttle-blip check with `e36 live`
  on the running engine — RPM/TPS/MAF moved together ✓ (session-2 item done).
  `e36 live` now also shows a stored-faults panel: DTC reads interleaved on
  the poller thread every 10 s (`--dtc-interval`, `--no-dtc`), always
  non-fatal; `--once`/`--json` include faults too (`faults` array /
  `faults_error`). Wire cost ≈ 65 B per fault poll → < 1% of the budget.
  Car context worth remembering: no catalytic converters (decat + Euro MS41.0
  swap explains the ECU identity); fault 217 (EGS CAN) is likely an artifact
  of the auto-donor ECU in (probably) a manual car — it will re-store after
  every clear.
