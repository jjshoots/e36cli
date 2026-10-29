"""e36cli — DS2 diagnostic CLI for BMW E36 (MS41) over K-line."""

from importlib.metadata import PackageNotFoundError, version

# Single source of truth is pyproject.toml's [project].version, read back from
# the installed distribution metadata (also present for `uv sync` editable
# installs). The fallback only covers importing straight from a source tree
# that was never installed (e.g. PYTHONPATH=src).
try:
    __version__ = version("e36cli")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
