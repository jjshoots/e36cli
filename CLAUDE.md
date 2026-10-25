# e36cli — Claude notes

Fully Claude-owned project. Owner: jet. Car: BMW E36, M52B25 engine with an
M52B28 ("2.8") MS41.x DME, possibly tuned. Cable: VAG KKL 409.1, FTDI FT232RL,
`/dev/ttyUSB0`. Host: this Linux box, fish shell, uv-managed Python.

## Spin-up (read in this order)

1. `SPEC.md` — the contract. Command surface, invariants, layer boundaries.
2. `research/` — sourced protocol/data findings with confidence markers.
   Treat [low] confidence facts as hypotheses to verify on the car.
3. `GARAGE.md` — what to do when the laptop is plugged into the car.

## Ground rules learned from planning (don't re-derive)

- The simulator encodes our *beliefs*; only real captures prove correctness.
  Never mark a profile param `verified = true` without a capture to point at.
- K-line echoes every TX byte — all transport code must consume the echo.
- Throughput ceiling is the wire (9600 baud). Optimize frame count, not Python.
- FTDI latency timer must be 1 ms (`e36 doctor` handles it) or everything
  feels broken.
- Writes (dtc clear etc.) are guarded; captures are always-on. See SPEC invariants.

## Dev loop

- `uv sync` then `uv run pytest` (must stay green, no hardware needed).
- `uv run e36 --sim live` etc. — every command works against the simulator.
- Real car: follow GARAGE.md; raw probing via `uv run e36 raw ...`.
- Captures land in `~/.local/share/e36cli/captures/`; copy interesting ones
  into `tests/fixtures/` as goldens.

## State / history

- 2026-10-25: project started. Research agents gathered DS2/MS41 docs into
  `research/` (NB: ms4x.net wiki DS2 pages are empty stubs; real sources were
  RomRaider's Java DS2 code and the BimmerStein-ECU-Tool Python repo).
  Full stack + simulator built; adversarial review pass fixed 13 defects
  (notably: tolerant echo strip, honest wire math, poller failure policy,
  core-param subset); 171 tests; installed via `uv tool install .`.
  Nothing verified on the car yet.
  Perf reality: 0x06 RAM reads cap at ~3.3 Hz full set / ~6.4 Hz dashboard
  subset (wire math) — the 0x0B batch telegram (research/ms41-data.md §3.7)
  is the future 10–19 Hz path, unimplemented pending on-car validation.
  Next milestone: garage session 1 (GARAGE.md), then promote verified params.
