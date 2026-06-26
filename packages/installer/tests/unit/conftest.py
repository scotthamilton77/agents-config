"""Shared fixtures for the installer unit suite.

OpenCode auto-detection probes the live PATH via ``shutil.which`` (mirrors the
bash ``command -v opencode``). PATH is global process state — on a developer
machine with ``opencode`` installed it would silently flip every auto-detect
result, making tests pass or fail based on who runs them. The autouse fixture
below pins the PATH probe to "not present" for the whole unit suite so that
auto-detect tests stay hermetic. Tests that specifically exercise the PATH
branch (see ``test_tools_opencode.py``) re-stub the probe in their own body,
which runs after this fixture and therefore wins.

The patch targets ``installer.tools.opencode.which`` — the module-local name
bound by ``from shutil import which`` — NOT ``shutil.which`` on the shared
stdlib module, so only OpenCode detection is affected and no unrelated
``shutil.which`` caller is perturbed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.installignore import InstallIgnore, load_installignore

_REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def _neutralize_opencode_path_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("installer.tools.opencode.which", lambda _cmd: None)


@pytest.fixture
def ignore() -> InstallIgnore:
    """The canonical .installignore content as an in-memory object, so a staging
    test gets the real exclusion set without needing a manifest file inside its
    temporary repo under test.

    Sourced from the REAL repo-root manifest via load_installignore rather than a
    hand-copied literal, so a new exclusion class added to .installignore cannot
    silently drift away from the set these staging tests exercise."""
    return load_installignore(_REPO_ROOT / ".installignore")
