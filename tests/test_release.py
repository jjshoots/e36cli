"""Release/toolchain consistency (STD-23): one version, one ruff, pinned actions."""

import re
import tomllib
from importlib.metadata import version
from pathlib import Path

import e36cli

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def _pyproject_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def test_dunder_version_matches_installed_metadata() -> None:
    assert e36cli.__version__ == version("e36cli")


def test_dunder_version_matches_pyproject() -> None:
    # release.yml separately checks the pushed tag against pyproject.
    assert e36cli.__version__ == _pyproject_version()


def test_ci_ruff_matches_pre_commit_rev() -> None:
    pre_commit = (ROOT / ".pre-commit-config.yaml").read_text()
    m = re.search(r"astral-sh/ruff-pre-commit\s*\n\s*rev:\s*v?([\w.]+)", pre_commit)
    assert m, "ruff-pre-commit repo not found in .pre-commit-config.yaml"
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    pins = re.findall(r'RUFF_VERSION:\s*"?([\w.]+)"?', ci)
    assert pins == [m.group(1)]


def test_workflow_actions_are_pinned_to_full_shas() -> None:
    assert WORKFLOWS
    for wf in WORKFLOWS:
        for ref in re.findall(r"^\s*-?\s*uses:\s*(\S+)", wf.read_text(), flags=re.M):
            if ref.startswith("./"):
                continue  # local reusable workflow, versioned with this repo
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), f"{wf.name}: {ref}"
