# Contributing to e36cli

## Dev setup

```sh
git clone git@github.com:jjshoots/e36cli.git && cd e36cli
uv sync
uv run pre-commit install --install-hooks --hook-type pre-commit --hook-type pre-push
uv run pytest          # full suite, no hardware, no network, < 10 s
```

The CLI runs against a built-in simulated DME: `uv run e36 --sim panel`.
Lint/format is ruff (configured in `pyproject.toml`); pre-commit runs it for
you, CI enforces it.

## The rules that matter

1. **`SPEC.md` is the contract.** Read it before changing behavior; if reality
   contradicts the spec, update the spec in the same PR. The command surface
   is closed — new commands/flags need a spec change, not just code.
2. **Provenance is mandatory.** Every parameter in `data/profiles/*.toml` and
   every fault-code entry carries `source` (URL) and `verified` fields.
   `verified = true` additionally requires `verified_source` pointing at a
   capture file. No source, no merge. Unverified values must keep their `?`
   marker in every output path.
3. **The simulator is a Transport.** Everything above the transport layer must
   work identically against `--sim`. New commands need CLI tests via the
   simulator; new wire behavior needs fault-injection coverage.
4. **Writes are guarded.** Anything that modifies ECU state requires explicit
   confirmation, and non-DME modules are strictly read-only
   (see `research/cluster-and-service-reset.md` for why).
5. **Code meets `STANDARDS.md`.** Layering, capture, error policy, resource
   ownership, typing and test rules, each with how it is checked.

## Contributing a new ECU profile

The most valuable contribution. Open a *profile request* issue with:

- `e36 ident` output (ECU ID, SW index, build week),
- ideally a capture file from `~/.local/share/e36cli/captures/` of an
  `ident` + `dtc read` + `live --once` session (the ident response carries
  your DME's production serial — its tail may be the immobiliser ISN; zero it
  out, or say so and we will, before anything is published),
- what engine/market the car is.

If you can verify parameters live (values physically plausible at idle,
throttle/RPM/MAF moving together), say so — that's what promotes
`verified = false` to `true`.

## Releasing (maintainers)

1. Bump `version` in `pyproject.toml`, commit.
2. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. `release.yml` gates on lint + tests, builds, and publishes to PyPI via
   **Trusted Publishing** (OIDC — no tokens). One-time setup: configure a
   Trusted Publisher at <https://pypi.org/manage/account/publishing/>
   (project `e36cli`, owner `jjshoots`, repo `e36cli`, workflow
   `release.yml`, environment `pypi`).

## PR checklist

- `uv run pytest` green, `uvx ruff check` and `uvx ruff format --check` clean
- SPEC.md updated if behavior changed
- Provenance fields on any new data
- Capture fixtures for any new wire behavior claimed as real
