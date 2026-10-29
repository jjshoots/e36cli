# Garage log — this car

Sessions run per the protocol in `GARAGE.md`; captures in `car/captures/`,
write-ups in `car/research/`. The car itself: `car/README.md`.

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
- **Session 1b — 2026-10-25 night, engine running: RAM probe DONE.** 3 window
  sweeps + 20-round validation (engine was shut off mid-validation; 8 clean
  rounds sufficed). Results in car/research/1429373-probe.md; profile updated.
  Next live items: confirm LTFT/additive scalings with a cold-start →
  warm-idle log (watch them move), re-test battery addr with headlights on
  (voltage dip), and try the 0x0B batch telegram. Use short bursts — the
  FTDI USB link dies under sustained traffic (try a different cable/port).
- **Session 3 — 2026-10-29, cold start → warm-up → rev test: DONE**
  (read-only). Step 9 answered: EWS 0x44 and GM 0x00 answer ident on the KKL
  cable, IKE 0x80 / ABS 0x56 silent. Cold-start log KOEO → crank → 83 °C,
  three blips (max 4074 rpm). Step 8 measured: 0.96 Hz `--all`, 1.56 Hz core
  — below the 2.5 Hz target, wire-bound. Continuous `e36 log` killed the FTDI
  (once until a physical replug); burst logging worked. Several profile
  entries shown wrong (ignition_advance frozen, O2/LTFT/load scalings).
  Full write-up: car/research/session3-coldstart.md; goldens in car/captures/.

## Next session

Physical checks (owner, no laptop needed):

- [ ] Bank 1 O2: inspect/reseat the B1 front sensor connector first (the
      decat/exhaust work may have disturbed it). If that's fine, measure
      heater resistance and the 12 V heater feed — DTC 25 + a flat 4.89 V
      signal suggest one break taking out signal and heater.
- [ ] Battery: multimeter across the terminals, engine off and settled. The
      DME read 11.62 V KOEO; if the meter agrees the battery is weak/discharged,
      if it reads ~12.5 V the 0xFB45 scaling is off at the low end.

On the car:

- [ ] Logging no longer needs the shell loop: plain `e36 log warmup.csv --all`
      reopens the port every 40 samples (`--burst`, the pattern that survived
      session 3) and, if the FTDI drops anyway, warns on stderr, waits for the
      device (replug if it stays gone — it picks up a re-enumerated
      /dev/ttyUSBn if it is the only one), re-applies the latency timer and
      resumes into the SAME file with a gap row (empty param columns; JSONL:
      a `"event": "reconnect"` line). Rows are flushed as written, so
      `tail -f warmup.csv` works. **Validate on the car:** a real drop →
      reconnect cycle (stderr warning, gap row, resume), and whether
      `--burst 40` alone prevents drops on a long run. Try a different USB
      port/cable if drops continue.
- [ ] After the profile fixes in TODO.md land: re-log a warm idle + blips to
      check the new ignition-angle candidate (0xE98D) and the O2/LTFT
      reinterpretation.
- [ ] Step 10 (`e36 panel` on the running engine) and step 11 (drive test,
      LTFT/additive B2) are not covered by the session-3 captures.

