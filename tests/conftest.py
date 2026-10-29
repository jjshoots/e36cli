"""Suite-wide fixtures: keep CLI output plain text whatever the host environment.

On CI, Typer forces a rich terminal (it checks GITHUB_ACTIONS / FORCE_COLOR /
PY_COLORS once, at import), so `--help` output carries ANSI escapes that split
option names (`--burst` -> `-` + `-burst`) and plain-text asserts fail. Rich
consoles likewise honour FORCE_COLOR / PY_COLORS when constructed, and
e36cli.cli builds its consoles at import. Tests assert on plain text, so pin
everything to the non-TTY default that CliRunner would otherwise give.
"""

from __future__ import annotations

import os

# Before any test module imports e36cli.cli (and its module-level Consoles).
for _var in ("FORCE_COLOR", "PY_COLORS"):
    os.environ.pop(_var, None)

import pytest  # noqa: E402
import typer.rich_utils  # noqa: E402


@pytest.fixture(autouse=True)
def plain_cli_output(monkeypatch):
    monkeypatch.setattr(typer.rich_utils, "FORCE_TERMINAL", False)
