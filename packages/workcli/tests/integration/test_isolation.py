"""The isolation guard is load-bearing: it must refuse to run bd anywhere that
could resolve into a real .beads via bd's upward directory walk."""

from __future__ import annotations

import subprocess

import pytest

from tests.integration.conftest import assert_off_repo, resolve_bd


def test_resolve_bd_returns_absolute_path_or_skips():
    bd = resolve_bd()  # skips the module if bd is absent
    assert bd.startswith("/")


def test_guard_refuses_a_path_inside_a_git_repo(tmp_path):
    # A tmp dir that IS a git repo must be rejected (bd would commit into it /
    # walk up to its .beads).
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)  # noqa: S607
    with pytest.raises(RuntimeError, match="inside a git repo"):
        assert_off_repo(tmp_path)


def test_guard_allows_a_bare_tmp_dir(tmp_path):
    # pytest tmp_path is off-repo (/private/var/folders/... on macOS); no ancestor
    # is a git repo, so the guard passes.
    assert_off_repo(tmp_path)  # must not raise
