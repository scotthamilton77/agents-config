"""Fixtures + guards for the real-bd integration suite.

Every install is a throwaway .beads under pytest tmp_path, bound to bd via
BEADS_DIR so bd's upward .beads discovery can never reach the repo's real DB.
The suite skips wholesale when bd is not on PATH.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


def resolve_bd() -> str:
    """Absolute path to the bd binary, or skip the whole module if absent."""
    bd = shutil.which("bd")
    if bd is None:
        pytest.skip("bd not on PATH; the real-bd integration suite requires it")
    return bd


def assert_off_repo(path: Path) -> None:
    """Refuse if `path` is inside any git repo (belt: bd walks UP for .beads,
    so a repo-nested install could reach a real .beads or commit bd's self-init
    into an enclosing checkout). tmp_path is off-repo, so this passes normally."""
    resolved = path.resolve()
    for ancestor in (resolved, *resolved.parents):
        if (ancestor / ".git").exists():
            raise RuntimeError(
                f"refusing to run bd under {resolved}: ancestor {ancestor} is inside a git repo; "
                "the integration harness must install into an off-repo temp dir"
            )
