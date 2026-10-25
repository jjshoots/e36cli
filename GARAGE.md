# Garage session protocol

Scarce resource: car time. Follow in order; each step produces a capture even on
failure. Stop and think only if a step's *decision point* says so — otherwise
record and continue. Everything is auto-captured to
`~/.local/share/e36cli/captures/`.

## Prep (at desk, before walking out)

- [ ] `uv run pytest` green
- [ ] `uv run e36 doctor` with cable plugged into laptop only — port found,
      permissions OK, latency timer = 1 ms
- [ ] Charge laptop

## Session 1 — ignition on, engine off

1. Plug into OBD2 cabin port (fallback: 20-pin round under hood, adapter, K on pin 20).
2. `uv run e36 ident`
   - Decision: no response → try 20-pin port; still nothing → `e36 raw 12 04 00`
     variants per research doc; capture everything, abort session, debug at desk.
   - Success: note SW/HW numbers; does a profile match? If tuned software, record ident.
3. `uv run e36 dtc read` — expect plausible codes (car's known issues).
4. `uv run e36 live --once` — sanity-check values at ignition-on:
   coolant ≈ ambient/engine-warm, RPM = 0, battery ≈ 12.x V, throttle responds
   to pedal press.
5. `uv run e36 scan` — see which other modules answer.

## Session 2 — engine running (only if session 1 clean)

6. `e36 live` at idle: RPM ~700–800, battery ~13.8–14.2 V (alternator),
   coolant rising. Blip throttle: RPM + TPS + MAF must move together.
7. `e36 log idle-warmup.csv` for a few minutes of warmup.
8. `--timing-debug` on: record achieved poll rate (target ≥ 2.5 Hz core).

## Session 3 — new features to validate on the car

9. `e36 scan` (ignition on): do IKE 0x80 / ABS 0x56 / EWS 0x44 answer their
   harmless ident probes on this KKL cable, or is the "needs ADS" story true?
   Record the raw ident bytes either way.
10. `e36 panel` on the running engine: full param set + state-bits line
    (throttle closed should toggle with pedal; decel fuel cut on a rev
    release), faults panel updates, `c`→`y` clear flow IF the owner wants the
    codes cleared (expect 217 to re-store; 25 to re-store until the B1 sensor
    is fixed).
11. Drive test: watch LTFT/additive B2 move (confirms the x/4096 scaling
    hypothesis) → promote trim scalings if confirmed.

## Session log

- **Session 1 — 2026-10-25, ignition on + idling: DONE.** doctor ✓ (after
  chmod/latency sudo fixes), ident ✓ (ECU 1429373 = Euro MS41.0, profile
  added), dtc read ✓ (217/25/52, ages decoded), live --once ✓ (8 params
  physically plausible → promoted verified). Goldens in tests/fixtures/.
  Gotcha hit: running `e36 live` in a second window while another e36 command
  runs kills both — single-master wire; port is now opened exclusively.
  Still pending from session 2 list: warmup log, measured poll rate (step 8
  target is now ≥ 2.5 Hz core, not 10 Hz).
- **Session 2 (partial) — 2026-10-25, engine running:** throttle-blip
  coherence check DONE by the owner via `e36 live` — RPM, TPS and MAF moved
  together on blips, confirming decode coherence beyond static plausibility.

## After any session

- Copy the session's capture files into `tests/fixtures/` (golden names:
  `car-ident.jsonl`, `car-dtc.jsonl`, ...).
- Promote `verified = true` ONLY for params whose live values made physical
  sense, citing the capture file in `source_verified`.
- Fix the simulator anywhere its bytes differed from the car's.
- Update CLAUDE.md "State / history".
- **Session 1b — 2026-10-25 night, engine running: RAM probe DONE.** 3 window
  sweeps + 20-round validation (engine was shut off mid-validation; 8 clean
  rounds sufficed). Results in research/1429373-probe.md; profile updated.
  Next live items: confirm LTFT/additive scalings with a cold-start →
  warm-idle log (watch them move), re-test battery addr with headlights on
  (voltage dip), and try the 0x0B batch telegram. Use short bursts — the
  FTDI USB link dies under sustained traffic (try a different cable/port).
