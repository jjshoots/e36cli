# The car

Everything specific to the owner's car lives under `car/`. The ECU-*type*
profile it uses ships with the package at `data/profiles/ms41.0-1429373.toml`.

| | |
|---|---|
| `car/README.md` | this dossier: identity, mods, faults, diagnosis, owner checks |
| `car/log.md` | garage session log + plan for the next session |
| `car/captures/` | real K-line captures and logs from the car — replay goldens for `tests/` |
| `car/research/` | car-specific findings: RAM probe (`1429373-probe.md`, raw data in `data/`), cold start/warm-up (`session3-coldstart.md`) |

## Identity

- **BMW E36**, M52B25 engine with an M52B28 ("2.8") DME fitted.
- **DME:** ECU ID **1429373**, Euro **MS41.0**, SW index 59, built week 04/96
  (ident: `car/captures/car-ident.jsonl`). Not the US MS41.1 the "2.8" label
  suggested.
- **Production serial: redacted.** The ident's serial field (payload bytes
  33–42) is replaced by `000000000` in every capture here, with the DS2
  checksum recomputed so replays still verify. The last 4 digits are taken to
  be the EWS ISN (immobiliser pairing code; research/ms41-data.md §2, medium
  confidence), so never commit an unredacted ident. Real captures under
  `~/.local/share/e36cli/captures/` are NOT redacted.
- **Modules on the KKL cable:** DME 0x12, EWS 0x44, GM 0x00 answer ident; IKE
  0x80 and ABS 0x56 are silent (probably need an ADS interface).
- **Rig:** VAG KKL 409.1 cable (FTDI FT232RL, `/dev/ttyUSB0`, latency timer
  1 ms) on a Linux laptop. The FTDI drops off USB under continuous traffic;
  burst reopen (`e36 log --burst 40`, the default) survives it.

## Mods and history

- **No catalytic converters** (decat); no rear O2 sensors, so the rear O2
  channels read floating-input noise.
- The Euro MS41.0 DME is a swap — that plus the decat explains the identity.
  Likely from an automatic donor in a (probably) manual car.

## Stored faults (unchanged across sessions, left uncleared)

| Code | Meaning | Read |
|---|---|---|
| 217 | EGS (gearbox) CAN | artifact of the auto-donor DME; re-stores after every clear |
| 25 | Lambda heater bank 1 | real — see bank 1 below |
| 52 | Exhaust flap | likely decat-related |

All three "currently present", frequencies 1/13/41; hours counter advancing
(`car/captures/car-dtc.jsonl`, `car-koeo-dtc.jsonl`).

## Diagnosis so far

- **Bank 1 runs open loop:** front O2 B1 flat at the rail, STFT B1 frozen at
  exactly 0, integrator static, plus DTC 25 → one break taking out sensor
  signal and heater. Bank 2 is closed loop (entered at 54–60 °C coolant) with a
  true long-term trim of about +12 %.
- **Battery weak, charging fine:** 11.62 V key-on/engine-off, 9.99 V cranking,
  13.2–14.4 V running (DME reading; multimeter check pending).
- Idle 930 → ~704 rpm over warm-up; MAF 12.5–17 kg/h idle, ~190 kg/h at 4k.

## Owner checks (no laptop needed)

- [ ] **Bank 1 O2 connector check.** O2 B1 flat at 4.87–4.90 V at every
      rpm/temperature/throttle, STFT B1 0, integrator static, plus DTC 25
      (heater open circuit) → one break taking out signal and heater. Check
      the B1 sensor connector first (decat/exhaust work), then heater
      resistance and the 12 V heater feed.
- [ ] **Multimeter battery check.** DME read 11.62 V KOEO (every sample),
      9.99 V cranking, 13.15–14.38 V running (alternator fine). Measure at
      the terminals with the engine off and settled: ~11.6 V → battery
      weak/discharged; ~12.5 V → 0xFB45 scaling is off at the low end.
