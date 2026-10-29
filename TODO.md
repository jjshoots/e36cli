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

- [ ] **Demote `ignition_advance` (0xE989) and find the real ignition angle.**
      Raw 128 = 24.14° on 730/731 samples, engine off and cranking included
      (one 18.92° outlier on a blip); the 2026-10-25 "verification" was the
      same constant (`tests/test_car_fixtures.py`, ignition_advance assert,
      which must change with it). Candidate: `knock_retard` 0xE98D, which
      reads like an idle ignition angle (−10.5…−3° cold, ~+13.9° at 45–48 °C,
      ~+17° warm); derive its scaling/offset. Also fix `knock_retard_global`
      0xE9D9 (raw 0 → −48°, offset wrong).
- [ ] **Rename `ltft_*` → `lambda_integrator_*` and derive the true LTFT.**
      0xEDA8 (and 0xED6E) is a sawtooth controller integrator (~0.66 %/sample,
      freezes at 11.99 in fuel cut), not a long-term trim. True B2 LTFT ≈
      mean(0xEDA8) − mean(0xED96) ≈ 11.3 → 12.6 % — supports the x/4096 factor
      scaling. Decide how to present a derived LTFT (computed param? panel
      only?). `stft_b2` 0xED96 updates per O2 crossing.
- [ ] **Front O2 scaling: raw / inverted.** `x*5/1023` is refuted as sensor
      volts: B2 swings rail to rail (~0.43–4.8) and is inverted (4.8 = lean in
      fuel cut, 0.5 = rich on blip). Also: KOEO raw words 0x63E8 vs 0x73E9
      decode the same, so only the masked low bits look meaningful — check
      what the high byte is. Rear O2 (1.6–1.8 V) is noise, no sensors (decat).
- [ ] **`load` units.** 1.0–1.5 at idle, 8.8 on a blip: ~90× too small for
      mg/stroke (true idle ≈ 118). Find the right scaling or meaning.
- [ ] **`lambda_bits` semantics.** bit0 stays 1 through fuel cut (so it is
      "closed loop reached", not "closed loop now"; B2 0→1 at 53.6–59.6 °C);
      value 9 (bit 3) seen during long rich idle stretches; B1 0 KOEO, 2
      running, never anything else.
- [ ] **`add_*` meaning.** `add_b2` 0 engine-off → 0.25 ms at first fire →
      0.44–0.47 ms warm: a live injection term, not a stored adaptation.
      `add_b1` always 0. Relabel/rescale.
- [ ] **Dead / misread params.** `operating_state_bits` 0xFD14 is 0 on every
      sample (dead on this ECU); `idle_valve` goes negative (controller term,
      not a position).
- [ ] **Promote now-citable verifications** (with tests against the new
      goldens): coolant/IAT low end (`car-koeo-live-all.jsonl`,
      `car-coldstart.csv`), battery 9.99–14.38 V (pending the multimeter
      check), `stft_b2` address + zero point.
- [ ] **(Optional) mark O2 front params `core = true`** once their scaling is
      fixed, so they show in the default dashboard view.

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
