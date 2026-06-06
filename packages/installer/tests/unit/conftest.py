"""Shared fixtures for the installer unit suite.

OpenCode auto-detection probes the live PATH via ``shutil.which`` (mirrors the
bash ``command -v opencode``). PATH is global process state — on a developer
machine with ``opencode`` installed it would silently flip every auto-detect
result, making tests pass or fail based on who runs them. The autouse fixture
below pins the PATH probe to "not present" for the whole unit suite so that
auto-detect tests stay hermetic. Tests that specifically exercise the PATH
branch (see ``test_tools_opencode.py``) re-stub ``shutil.which`` in their own
body, which runs after this fixture and therefore wins.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _neutralize_opencode_path_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("installer.tools.opencode.shutil.which", lambda _cmd: None)
