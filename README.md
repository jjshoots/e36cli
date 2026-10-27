# e36cli

[![CI](https://github.com/jjshoots/e36cli/actions/workflows/ci.yml/badge.svg)](https://github.com/jjshoots/e36cli/actions/workflows/ci.yml)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](pyproject.toml)

A fast, honest, terminal-native diagnostic tool for the BMW E36 (M52 / MS41.x DME),
speaking BMW's DS2 protocol over K-line through a ~$10 VAG KKL (FTDI) cable.
Built on Linux, for Linux.

```
        e36 snapshot — ms41.1
┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━┓
┃ Param             ┃   Value ┃ Unit ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━┩
│ Engine RPM        │   817 ? │ rpm  │
│ Mass air flow     │  9.25 ? │ kg/h │
│ Intake air temp   │ 24.46 ? │ °C   │
│ Coolant temp      │ 19.98 ? │ °C   │
│ Vehicle speed     │     0 ? │ km/h │
│ Ignition advance  │ 12.58 ? │ °    │
│ VANOS angle       │ 59.92 ? │ °    │
│ Throttle position │  0.78 ? │ %    │
│ Short trim B1     │  1.00 ? │ %    │
│ Short trim B2     │  1.00 ? │ %    │
│ Battery voltage   │ 13.97 ? │ V    │
└───────────────────┴─────────┴──────┘
       ? = not verified on car
                     2 stored fault(s)
┏━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━┓
┃ Code ┃ Description                     ┃ Freq ┃ Age (h) ┃
┡━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━┩
│   25 │ Lambda Sensor Heater Bank 1 ?   │    1 │    30.0 │
│   52 │ Solenoid Valve - Exhaust Flap ? │    1 │    30.0 │
└──────┴─────────────────────────────────┴──────┴━━━━━━━━━┘
```

*(real output — from the built-in simulator, no car attached)*

## Features

- **`e36 live`** — live dashboard: gauges at the K-line's physical speed limit,
  stored faults refreshed alongside, staleness shown honestly.
- **`e36 panel`** — the everything-view: ECU identification, every known
  parameter, decoded status bits, faults — and clear them with a guarded
  keypress.
- **`e36 dtc read` / `dtc clear`** — fault codes with plain-text descriptions,
  occurrence counts, and age in engine-hours. Writes always require
  confirmation.
- **`e36 log`** — stream samples to CSV/JSONL for analysis.
- **`e36 scan`** — probe every known E36 module address, show raw idents.
- **`e36 sia`** — guided service-interval reset walkthrough (the safe,
  pin-7 way — see *Philosophy*).
- **`e36 raw`** — send arbitrary DS2 frames when you know what you're doing.
- **`e36 doctor`** — port, permissions, FTDI latency: diagnose the laptop
  before blaming the car.
- **Capture-everything**: every byte exchanged with a real car is recorded to
  session files — your own regression corpus, replayable against the test
  suite with `--sim-fixture`.
- **Built-in simulated DME**: every command works with `--sim`, no hardware
  needed. The simulator idles, warms up, stores and clears faults, and can
  inject wire faults.

## Philosophy: provenance or it didn't happen

Community-sourced RAM maps are a minefield of copy-paste errors. Every
parameter in this tool carries a `source` URL and a `verified` flag; anything
not yet proven against a real engine renders with a **`?` marker** in every
output — tables, CSV headers, JSON fields. Parameters get promoted only with a
capture file as evidence.

Current ground truth: verified on a **1996 Euro E36 (M52, MS41.0, ECU
1429373)** — identification, fault read/clear (byte-exact), and the core
sensor set live at idle, plus a RAM probe that located the fuel-trim and
battery-voltage blocks on that ECU. US MS41.1/MS41.2 profiles ship with
sourced-but-unverified addresses. See [`research/`](research/) for the sourced
protocol documentation and [`SPEC.md`](SPEC.md) for the architecture contract.

Writes are conservative by design: fault-clearing needs explicit confirmation,
non-DME modules are strictly read-only, and there is deliberately **no**
software service-interval reset — the E36 cluster's reset opcode was never
published and sits one selector value away from an odometer reset
([details](research/cluster-and-service-reset.md)). `e36 sia` walks you
through the safe hardware method instead.

## Install

```sh
uv tool install e36cli            # from PyPI, or:
uv tool install git+https://github.com/jjshoots/e36cli
```

## Quickstart (no car needed)

```sh
e36 --sim ident                          # identification + profile match
E36CLI_SIM_DTCS=25,52 e36 --sim dtc read # seeded fault codes
e36 --sim live                           # live dashboard
e36 --sim panel                          # the everything-view
```

## Hardware

- Any **VAG KKL 409.1** cable with a **genuine FTDI** chip (FT232RL). CH340
  clones work for basic serial but are untested here.
- E36s: the round 20-pin connector under the hood (K-line on pin 20), or the
  cabin OBD2 socket on later cars. Cheap 20-pin→OBD2 adapters exist.
- One-time Linux setup (permissions + the critical 1 ms FTDI latency timer):

```sh
printf 'SUBSYSTEM=="usb-serial", DRIVER=="ftdi_sio", ATTR{latency_timer}="1"\nKERNEL=="ttyUSB[0-9]*", MODE="0666"\n' \
  | sudo tee /etc/udev/rules.d/99-e36cli.rules
sudo udevadm control --reload   # then replug the cable
e36 doctor                      # verifies all of it
```

Supported ECUs: MS41.0 / MS41.1 / MS41.2 (M52 and S52 engines, 1995–2000),
with a generic fallback for unrecognized MS41 software. Pre-OBD2 E36 DMEs
(ADS-protocol era) are **not** supported — they need different interface
hardware entirely.

## Contributing

PRs welcome — especially capture files and verified parameters from other
MS41 variants. `uv sync && uv run pytest` is the whole dev loop; the test
suite needs no hardware. See [CONTRIBUTING.md](CONTRIBUTING.md), and open a
*profile request* issue with your `e36 ident` output if your ECU isn't
recognized.

## Disclaimer

Use at your own risk. This tool talks to the engine control unit of a moving
vehicle: reads are safe by design, writes are guarded, but you are the
operator. Never use component-activation or fault-clearing functions while
driving. This project is not affiliated with, endorsed by, or connected to
BMW AG in any way. All trademarks are the property of their respective owners.

## License

[GPL-3.0-or-later](LICENSE). The fault-code database and parts of the
parameter maps derive from GPL-licensed community tooling (BimmerStein,
RomRaider definitions) — see `research/` for full provenance.
