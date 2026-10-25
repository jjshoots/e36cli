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
- 2026-10-25 (night): **live RAM probe of 1429373 succeeded** — see
  research/1429373-probe.md. Trim block = 1429861 layout exactly (injPW
  0xECBC, STFT 0xED5C/0xED96, LTFT 0xED6E/0xEDA8, additive 0xED66/0xEDA0);
  battery = 0xFB45 (1429861 − 2), VERIFIED at 14.0–14.4 V running; several
  documented scalings are wrong for this program (hypotheses in the profile).
  Diagnostic gold: STFT B1 frozen at exactly 0% + B1 O2 flat at 4.89 V ⇒
  bank 1 runs OPEN LOOP (dead/unplugged B1 sensor); bank 2 closed loop and
  adapting. 10 probed params added to the profile; core now includes
  stft_b1/b2 + battery (replay tests pin the old core-8 via --params).
  Wire lessons: big 0x06 reads need Timing(deadline=1.0) and ≤0x60 chunks;
  the FTDI drops off USB under sustained traffic (burst sessions fixed it —
  suspect cable); 0xF880+ is calibration tables w/ 0x100-periodic mirror;
  flush_input termios.error escape fixed + regression test (186 tests).
- 2026-10-25 (late night): **`e36 panel` + `e36 sia` shipped** (204 tests).
  Panel = ident header, all params, decoded state bits (only the documented
  bits of 0xFD24/0xFD14 — "closed throttle" is INVERTED bit 0), faults, keys
  q/c; the `c` clear runs on the Poller thread via `request_clear()` after an
  in-TUI `y` confirm. SIA reset over DS2 is a researched **NO-GO**
  (research/cluster-and-service-reset.md: opcode unpublished; GWSZ_RESET =
  odometer reset sits in the same command space; Euro E36 cluster likely needs
  ADS, not KKL) — `e36 sia` is a guided pin-7→pin-19 walkthrough instead,
  zero wire traffic, flash counts (7 oil / 23 inspection) over stopwatch.
  `e36 scan` now shows raw ident bytes and labels silent IKE/ABS/EWS with
  "may require ADS interface". HARD RULE now in SPEC: never write to non-DME
  modules. NOT yet validated on the car: panel on a running engine, scan
  module idents (0x80/0x56/0x44 harmless ident probes).
