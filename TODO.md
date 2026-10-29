# TODO

Ordered by priority. Sources: garage session 3 (2026-10-29), write-up in
`research/session3-coldstart.md`; captures cited there. Remember: never mark a
profile param `verified = true` without a capture to point at, and profile
scaling changes come with tests.

## Tooling

- [x] **Burst-style logging as the default.** DONE 2026-10-29:
      `src/e36cli/datalog.py` — `--burst N` (default 40) prophylactic reopen,
      auto-reconnect with gap rows/`reconnect` events, `--no-reconnect`; see
      SPEC `e36 log` policy. Deferred: the live/panel/dashboard Poller still
      uses the old give-up-after-10 policy (no reconnect); the capture header
      keeps the original port name if the FTDI re-enumerates elsewhere. Needs
      on-car validation of a real drop → reconnect cycle. Original note:
      a continuous `e36 log --all` died twice on 2026-10-29 with `device reports readiness to read but
      returned no data (device disconnected or multiple access on port?)`,
      and the FTDI later dropped off USB until physically replugged. What
      worked: a shell loop of `e36 log partNN.csv --all --samples 40 --rate 1.5`,
      reopening the port each burst (13 consecutive full bursts + the rev test
      after the replug). Build that into `e36 log` (and ideally the Poller):
      auto-reconnect on port error, wait for the device node to reappear,
      re-apply/verify the latency timer, keep appending to the SAME output
      file with a gap marker. See `src/e36cli/cli.py` (`log` command,
      `out.open("w", ...)` ~line 625) and the transport error path.
- [x] **Flush the CSV per row in `e36 log`.** DONE 2026-10-29 (CSV and
      JSONL, `SampleWriter` flushes after every row; flush, not fsync). Files showed 0 bytes until
      process exit (buffered writer; killed bursts left 0-byte
      `coldstart-20261029-part53.csv` / `revtest-20261029-part04.csv`). Flush
      after every row so a crash/drop never loses data and `tail -f` works.
- [ ] **0x0B batch telegram for poll rate.** Measured 0.96 Hz with `--all`
      (32 params) and 1.56 Hz core (`--timing-debug`: ~80 ms/request avg,
      95 ms worst) vs the 2.5 Hz GARAGE target. The `--rate` cap is NOT the
      limiter — per-request wire time is. Only fewer frames help
      (research/ms41-data.md §3.7).
- [ ] **Merge tool for burst logs.** Only needed for the session-3
      `partNN.csv` files now — `e36 log` bursts into one file itself. Add
      `e36 captures merge` (or similar) that concatenates them with a
      monotonic time column (and an empty gap row between parts, matching
      the new reconnect marker).
- [ ] **Drop EWS from `ADS_SUSPECTS`** (`src/e36cli/cli.py` ~line 201). EWS
      0x44 answered its ident probe on the KKL cable
      (`88 36 22 77 02 01 01 FF 02 96 06 01`), as did GM 0x00
      (`88 36 94 82 14 03 02 00 31 95 02 13`); both are already in the scan
      table. IKE 0x80 / ABS 0x56 stayed silent, so keep those. Ident-only,
      never write (SPEC hard rule). Golden: `tests/fixtures/car-koeo-scan.jsonl`.

## Profile `ms41.0-1429373` (each change with tests; see research note §4)

Done 2026-10-30 (profile + tests/test_car_fixtures.py evidence tests):
`ignition_advance` 0xE989 demoted (also in ms41-generic) and out of core;
0xE98D is now `ignition_angle` (core, unverified, (x−128)·0.375);
`knock_retard_global` offset dropped (x·0.375); `ltft_*` → `lambda_integrator_*`;
front O2 → inverted ADC span `100 − x·100/1023` % (rich high); `load` →
`x · 1.75` mg/stroke fitted to MAF/rpm (low confidence); `add_*`, `idle_valve`,
`lambda_bits` relabelled/annotated; `operating_state_bits` removed (dead);
coolant/IAT `verified_source` extended to the cold KOEO capture.

- [ ] **Derived true LTFT** (B2 ≈ mean(integrator) − mean(STFT) ≈ +12 %). Needs a
      two-param formula / derived-param concept the profile schema lacks —
      design decision pending.
- [ ] **Confirm `ignition_angle` offset** on the car (timing light at idle vs the
      ~+17° reading) — then it can be promoted.
- [ ] **`stft_*` factor**: zero point confirmed, 100/65535 vs 100/32768 open.
- [ ] **O2 high byte** (0x63 vs 0x73 at rest) — separate field?
- [ ] **`load` scaling**: fit spread 1.52–1.86 mg/count cold; re-check warm.
- [ ] **Battery promotion** of the low end: pending the multimeter check.
- [ ] **(Optional) mark O2 front params `core = true`** once the scaling is
      trusted.

## Owner, physical (no laptop needed)

- [ ] **Bank 1 O2 connector check.** O2 B1 flat at 4.87–4.90 V at every
      rpm/temperature/throttle, STFT B1 0, integrator static, plus DTC 25
      (heater open circuit) → one break taking out signal and heater. Check
      the B1 sensor connector first (decat/exhaust work), then heater
      resistance and the 12 V heater feed.
- [ ] **Multimeter battery check.** DME read 11.62 V KOEO (every sample),
      9.99 V cranking, 13.15–14.38 V running (alternator fine). Measure at
      the terminals with the engine off and settled: ~11.6 V → battery
      weak/discharged; ~12.5 V → 0xFB45 scaling is off at the low end.
