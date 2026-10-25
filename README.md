# e36cli

DS2 diagnostic CLI for a BMW E36 (M52, MS41.x DME) over K-line, built for a
VAG KKL 409.1 cable (FTDI FT232RL) on Linux.

```
uv tool install .          # installs the `e36` command
# or, in the repo:
uv sync && uv run e36 --help
```

Try it without a car:

```
e36 --sim ident            # identification + profile match
E36CLI_SIM_DTCS=100,214 e36 --sim dtc read
e36 --sim live             # live dashboard against the simulated DME
```

With the car: run `e36 doctor` first (port, permissions, FTDI latency), then
follow GARAGE.md. Every real-port session is captured to
`~/.local/share/e36cli/captures/` automatically.

Values marked `?` come from community-sourced RAM maps not yet verified against
this car. See SPEC.md for the architecture contract and `research/` for the
sourced protocol/data documentation. Dev: `uv run pytest`.
