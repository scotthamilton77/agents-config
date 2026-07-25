"""gitclean — survey git worktrees and branches, then delete only what is
provably safe to delete."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

_FALLBACK_VERSION = "0.1.0"


def get_version() -> str:
    """Installed version, falling back to the source constant when the package
    is imported from a source tree that was never installed (editable test
    runs, `python -m` from src/)."""
    try:
        return version("gitclean")
    except PackageNotFoundError:  # pragma: no cover - only when uninstalled
        return _FALLBACK_VERSION


__version__ = get_version()
