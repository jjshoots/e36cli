# TODO

Ordered by priority. Sources: garage session 3 (2026-10-29), write-up in
`car/research/session3-coldstart.md`; captures cited there. Remember: never mark a
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
- [x] **Drop EWS from `ADS_SUSPECTS`** — done 2026-10-30.

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

## Code review lows (2026-10-30 panel; standard ids in STANDARDS.md)

The 5 high + 15 medium findings are fixed. Remaining low-severity ones:

- [ ] **F-21** (STD-10) Wrap runtime formula errors: ArithmeticError / non-finite
      result in `ParamSpec.decode` → DecodeError naming param, formula, raw.
- [ ] **F-22** (STD-10) DTC record size inferred from divisibility; pass the
      expected size from `fetch_faults`, refuse ambiguous bare-04 payloads.
- [ ] **F-23** (STD-09) DTC DB: parse once into frozen `DtcInfo`, strict
      validation, wrapped TOML/OS errors; drop the unused `path_str`.
- [ ] **F-25** (STD-07) `ds2.Timing` frozen + validated; replace the two
      control-flow asserts with typed raises.
- [ ] **F-26** (STD-07) One wire-cost model (`ds2.wire_time(n)`): derive read
      deadlines from it (MAX_READ_CHUNK 0xF8 can exceed the 0.3 s deadline;
      the probe needed ≤0x60), point the perf tests at it.
      (`Timing.worst_case_s` landed for the join timeout.)
- [ ] **F-27** (STD-01) Split live.py into a rich-free engine module + views;
      add an AST import-direction test.
- [ ] **F-28** (STD-04) CaptureReader: reject unknown header versions (non-object
      lines and unknown `dir` are done).
- [ ] **F-30** (STD-19) Test that every `car/captures/` file is used by a test
      and every `verified_source` path resolves (car/README.md is the index).
- [ ] **F-31** (STD-15) Public seams instead of private access in tests
      (`sim._queue`, `_n_requests`); request-keyed sim fault injection; SLF001.
- [ ] **F-32** (STD-16) Move the six copied capture-dir fixtures into
      tests/conftest.py (also isolate HOME); read env vars once into Config;
      strict pytest settings (`--strict-markers`, `-ra`, `filterwarnings=error`).
- [ ] **F-34** (STD-14) `ParamSpec.from_toml()` instead of setting `_fn` after
      construction; public `evaluate(x)` for the sim.
- [ ] **F-35** (STD-14) Frozen `FaultsSnapshot` instead of the 5-tuple; Mode
      StrEnum for controller state (`_ReplayPair`, `Endian` are done).
- [ ] **F-36** (STD-12) `ms41.read_ident(client)`, one live-snapshot serializer,
      Annotated option aliases (the single error decorator is done).
- [ ] **F-37** (STD-21) Named DS2 status/opcode constants with citations; a
      contract docstring on `DS2Client.query`.
- [ ] **F-38** (STD-22) Dead branch + test-only symbols in sim.py; consider vulture.
- [ ] **F-39** (STD-20) Timezone-aware capture header timestamp (DTZ); hoist or
      justify function-local imports.
- [ ] Release tooling (from the release-pipeline work): ruff/pytest-timeout into
      the locked dev group so CI runs everything via `uv run`, no `uvx`.

Done in passing: F-24 (run_session acquires inside the guard), F-29 (closed
capture is terminal), F-33 (`__version__` from metadata, pinned CI ruff,
`uv sync --locked`, 3.13/3.14 in the matrix).

Owner-side physical checks for the car: `car/README.md`.
