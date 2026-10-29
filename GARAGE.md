# Garage session protocol

Scarce resource: car time. Follow in order; each step produces a capture even on
failure. Stop and think only if a step's *decision point* says so — otherwise
record and continue. Everything is auto-captured to
`~/.local/share/e36cli/captures/`. What has been done on the car so far, and
the plan for the next session: `car/log.md`.

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
7. `e36 log idle-warmup.csv` for a few minutes of warmup (burst reopen +
   auto-reconnect are on by default; watch stderr for link warnings).
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

## After any session

- Copy the session's capture files into `car/captures/` (golden names:
  `car-ident.jsonl`, `car-dtc.jsonl`, ...).
- Promote `verified = true` ONLY for params whose live values made physical
  sense, citing the capture file in `source_verified`.
- Fix the simulator anywhere its bytes differed from the car's.
- Log the session in `car/log.md`; car-specific findings go in
  `car/research/`; update CLAUDE.md "State / history".
