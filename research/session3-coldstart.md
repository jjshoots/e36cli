# Garage session 3 — cold start, warm-up, rev test (ECU 1429373), 2026-10-29

Read-only session (idents, DTC read, 0x06 RAM reads; no writes, no clears) on
the owner's car from a cold soak: key-on/engine-off (KOEO) at ambient → crank →
idle → warm-up to ~83 °C coolant → three throttle blips. This note records what
the captures show and which profile entries they confirm or refute. **No
profile scalings or `verified` flags were changed alongside this note** — the
profile follow-ups are listed at the end and tracked in TODO.md.

Confidence legend (as in ms41-data.md):
- **[high]** — directly visible in the captures, consistent across many samples / conditions
- **[medium]** — inferred from capture behaviour, one plausible reading
- **[low]** — hypothesis, needs a targeted test

## Captures

All under `~/.local/share/e36cli/captures/` unless noted. Golden copies in
`tests/fixtures/` are in brackets.

| Capture | Content |
|---|---|
| `20261029-191535.jsonl` [`car-koeo-ident.jsonl`] | `ident`, KOEO |
| `20261029-191538.jsonl` [`car-koeo-dtc.jsonl`] | `dtc read`, KOEO |
| `20261029-191541.jsonl` | `live --once` (core set + faults), KOEO |
| `20261029-191548.jsonl`, `20261029-191554.jsonl` [`car-koeo-live-all.jsonl` = 191554] | `live --once --all`, KOEO |
| `20261029-191601.jsonl` [`car-koeo-scan.jsonl`] | `scan`, KOEO |
| `coldstart-20261029.csv` [`car-coldstart.csv`] | `log --all`, KOEO → crank → idle, 80 rows over ~82 s at ~1 Hz; the continuous run that the FTDI killed |
| `coldstart-20261029-part2.csv`, `-part03`…`-part06.csv` | warm-up bursts; part05 nearly empty (drop) |
| `coldstart-20261029-part40.csv` … `-part52.csv` | 13 consecutive full 40-sample bursts after a USB replug (55 s gap between part06 and part40) |
| `revtest-20261029-part01.csv` … `-part03.csv` [`car-revtest.csv` = part02] | rev test, 12-param subset: blips to 3051/3256 rpm (part01), 4074 rpm + two ~2.2k rpm holds (part02), return to idle (part03) |
| scratchpad `warm-core.csv` / `warm-all.csv` (not retained) | `--timing-debug` rate measurements, warm idle |

The other `20261029-19*.jsonl` files are the wire captures behind the CSV logs
(and a few `--sim` sessions, `"port": "sim"` in their header).

## 1. Session / hardware facts

- **Ident unchanged** [high]: ECU ID 1429373, Euro MS41.0, SW index 59, 04/96
  (`car-koeo-ident.jsonl`).
- **Faults unchanged** [high]: 217 (EGS CAN), 25 (lambda heater B1), 52
  (exhaust flap), all "currently present", frequencies 1/13/41 as on
  2026-10-25. Ages went 25.1 h (10-25) → 25.7 h (KOEO) → 26.2 h (end of
  session); hours counter 0x43F2 → 0x43F8 at KOEO. The counter runs and
  nothing re-stored (`car-koeo-dtc.jsonl`, live-panel fault polls).
- **KOEO cold** [high]: coolant 29.7 °C / IAT 30.4 °C (raw 104/105 — within
  1 LSB; 191554 reads 104/104). Cold-soaked engine at ambient, so the
  `x*0.747-48` scaling is consistent at the low end too (only checked at
  74/41 °C before).
- **Battery** [high for the reading, medium for the diagnosis]: 11.62 V (raw
  114) on every KOEO sample; crank dip to 9.99 V (seen at ~1 Hz sampling, true
  minimum may be lower); running 13.15 min / 14.17 median / 14.38 max V.
  Alternator charging is healthy; the battery itself looks weak or
  discharged. 11.62 V resting is well below a healthy ~12.6 V — **verify with
  a multimeter** before trusting the low end of 0xFB45 (verified only at
  14.0–14.4 V so far).
- **Scan** [high]: EWS 0x44 answered ident
  `88 36 22 77 02 01 01 FF 02 96 06 01`; GM 0x00 answered
  `88 36 94 82 14 03 02 00 31 95 02 13`; IKE 0x80 and ABS 0x56 silent
  (`car-koeo-scan.jsonl`). So EWS does *not* need ADS on this cable — it
  should come out of `ADS_SUSPECTS` (`src/e36cli/cli.py`). IKE/ABS remain
  consistent with the "needs ADS" story.

## 2. FTDI / wire behaviour

- [high] A continuous `e36 log --all` died at ~2 min and, on retry, within
  seconds: `device reports readiness to read but returned no data (device
  disconnected or multiple access on port?)`. Later the adapter vanished from
  USB entirely until physically replugged.
- [high] Burst loop (`e36 log partNN.csv --all --samples 40 --rate 1.5`,
  reopening the port per burst) worked. After the replug the cable held for
  13 consecutive full bursts (part40–52) plus the whole rev test.
- [high] Achieved rates: **0.96 Hz with `--all`** (32 params), **1.56 Hz
  core** (timing-debug: ~80 ms per request average, 95 ms worst). Below the
  GARAGE 2.5 Hz core target. Wire-bound (the `--rate` cap of 1.5 is not the
  limiter for `--all`; per-request latency is), so the 0x0B batch telegram
  (ms41-data.md §3.7) is the way forward.
- [high] The CSV writer does not flush until exit: files showed 0 bytes while
  logging (`coldstart-20261029-part53.csv`, `revtest-20261029-part04.csv` are
  0-byte leftovers of killed bursts).

## 3. Warm-up behaviour (coldstart + part2–52)

- [high] Idle speed: 930 rpm peak after start → ~800 by 45 s → ~740 at 40 °C
  → ~715 at 60 °C → ~704 at 80 °C.
- [high] IAT stayed at ambient (~31 °C) for ~5 min, then heat-soaked +4.5 °C.
- [high] **Bank 2 entered closed loop at 53.6–59.6 °C coolant**:
  `lambda_bits_b2` 0 → 1, STFT B2 starts moving, O2 B2 starts switching.
- [medium] From part47 an extra load appears (MAF 14.5 → ~17 kg/h, inj_pw
  +0.5 ms, idle_valve term steps up). Probably the radiator/aux fan.

## 4. Profile findings (all hypotheses until acted on with tests)

### 4.1 `ignition_advance` 0xE989 is frozen — currently `verified = true` [high]

Raw 128 (= 24.14°) on 730 of 731 CSV samples (coldstart parts + warm-core/
warm-all), **including engine off and cranking**. The single exception is
18.92° (raw 114) at 1169 rpm during a blip in `coldstart-20261029-part52.csv`.
The 2026-10-25 "verification" (`tests/test_car_fixtures.py`, the
`ignition_advance` assert in `test_car_live_once_json_values_are_the_recorded_physics`)
read the same constant. **Must be demoted** — it was never seen to move.

### 4.2 `knock_retard` 0xE98D looks like the real ignition angle [medium]

With the current `(x-128)*0.375` formula it reads −10.5…−3° cold, steps to
~+13.9° at 45–48 °C coolant (as warm-up enrichment ends), ~+17.25° warm idle,
15.75° in the warm-all snapshot, max 19.1°. That is the shape of an idle
ignition angle, not a knock retard. Candidate address for the real ignition
angle; scaling/offset still to derive. `knock_retard_global` 0xE9D9 reads
raw 0 → −48° (range −48…−43.5): offset is wrong whatever it is.

### 4.3 Front O2 `x*5/1023` is not sensor volts [high for "refuted"]

- B2 swings between rails ~0.43 and ~4.8 V — a narrowband sensor tops out
  ~0.9 V. And it is **inverted**: ~4.8 V during decel fuel cut (lean), ~0.5 V
  on blip enrichment (rich). Needs a raw/inverted scaling (e.g. treat as an
  inverted ADC count) [medium].
- KOEO both banks read ~4.89 V, but the raw words differ in the high byte
  (0x63E8 vs 0x73E9) while the low 10 bits decode the same — only the masked
  low bits seem meaningful; the high byte may be a separate field [low].
- Rear O2 1.61–1.78 V: noise only, consistent with no rear sensors (decat).

### 4.4 Trim block reinterpretation [medium]

- `ltft_b2` 0xEDA8 (and by symmetry `ltft_b1` 0xED6E) is **not** a long-term
  trim: it is a sawtooth (~0.66 %/sample ramps), i.e. the lambda-controller
  integrator, and freezes at 11.99 during fuel cut. Range 5.35…24.05 with the
  x/4096 formula. Proposed rename: `lambda_integrator_b1/b2`.
- `stft_b2` 0xED96 updates at O2 crossings (looks like a per-switch mean).
  Address and the 0x8000 zero point are confirmed (raw 32768 = 0 at KOEO,
  `car-koeo-live-all.jsonl`).
- True B2 LTFT ≈ steady offset mean(0xEDA8) − mean(0xED96) ≈ 11.3 → 12.6 %
  over the warm-up. A double-digit percent offset that is stable is what an
  adaptation looks like, which **supports the x/4096 factor scaling** for the
  0xEDA8 word (probe note §Verdicts called it LOW).
- `add_b2` 0xEDA0: 0 engine-off → 0.25 ms at first fire → 0.44–0.47 ms warm
  (max 0.50). A live injection term, not a stored adaptation. `add_b1` always
  0.
- `lambda_bits` bit0 stays 1 through fuel cut → not a live "closed loop now"
  flag; more like "closed loop reached since start". Value 9 (bit 3 set) seen
  on B2 during long rich idle stretches (55 samples), meaning unknown. B1 is
  0 at KOEO/crank and 2 once running, never anything else.

### 4.5 Other params

- `load` 0xFAFC [high for "wrong units"]: 1.0–1.5 at idle, 8.8 on a blip;
  ~90× too small for mg/stroke (true idle ≈ 118 mg/stroke). Scaling or
  meaning wrong.
- `operating_state_bits` 0xFD14: 0 on all 679 samples, cranking and fuel cut
  included → dead address on this ECU [high].
- `engine_state_bits` 0xFD24: 0 KOEO, 26 (0x1A) almost always running, 28/30
  briefly; unexplored [low].
- `idle_valve` 0xDA36 goes negative (−1.0…12.75, sawtooth) → a controller
  term, not a valve position [medium].
- `vanos_angle` 18.73° frozen at idle (raw 50, as on 10-25), 16.1–17.6° on
  blips. It moves, but only a little; keep `verified` but note the idle value
  is a parked position [medium].
- `maf` plausible throughout [high]: 12.5–17 kg/h idle, 41–55 at ~2.2k,
  159–192 kg/h on the 4k blip (revtest).

### 4.6 Bank 1 verdict [high]

O2 B1 4.868–4.897 V (ADC noise; 4.78–5.00 extremes over 859 samples) at every
rpm, temperature and throttle; STFT B1 0, integrator (`ltft_b1`) static at
5.493, `lambda_bits_b1` 2. Together with DTC 25 (heater, open circuit) this
points to **a single break that takes out signal and heater**: check the B1
sensor connector first (decat/exhaust work disturbs it), then heater
resistance and the 12 V heater feed.

## 5. Newly citable verification sources

For the profile follow-up (each still needs a test before flipping flags):

- `coolant_temp` / `iat` low end: KOEO ~30 °C agreement
  (`car-koeo-live-all.jsonl`, `coldstart-20261029.csv`), warm-up through
  83 °C (part40–52).
- `battery` 9.99–14.38 V range: `coldstart-20261029.csv` + part40–52 (low
  end pending the multimeter check).
- `stft_b2` address and zero point; `stft_b1` = 0 ⇒ open loop.
- `lambda_bits_b2` bit0 transition at closed-loop entry (53.6–59.6 °C).

## 6. Follow-ups (see TODO.md)

Demote `ignition_advance`, find the real ignition angle (0xE98D candidate);
rename `ltft_*` → lambda integrator and derive true LTFT; O2 raw/inverted
scaling; `load` units; `lambda_bits` semantics; `add_*` meaning; drop EWS from
`ADS_SUSPECTS`; CSV flush; burst logging; 0x0B batch telegram for rate. Owner,
physical: B1 connector check, multimeter battery check.
