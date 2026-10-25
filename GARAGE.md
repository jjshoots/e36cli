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
8. `--timing-debug` on: record achieved poll rate (target ≥ 10 Hz).

## After any session

- Copy the session's capture files into `tests/fixtures/` (golden names:
  `car-ident.jsonl`, `car-dtc.jsonl`, ...).
- Promote `verified = true` ONLY for params whose live values made physical
  sense, citing the capture file in `source_verified`.
- Fix the simulator anywhere its bytes differed from the car's.
- Update CLAUDE.md "State / history".
