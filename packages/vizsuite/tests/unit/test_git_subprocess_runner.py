"""SubprocessGitRunner: the one real git I/O boundary in slice 1.

Every other test drives a `ScriptedGitRunner` fake; this file is the sole place
that proves the `git ls-tree -r` wiring (argv, tab-delimited parse, blob rows)
actually works, against a real throwaway repo (git is always available in CI).
Slice 2 extends this seam with rev_parse/rev_list/diff/etc.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from vizsuite.adapters.git.runner import SubprocessGitRunner


def _git(cwd: Path, *args: str) -> None:
    # Fixture setup runs a known binary (git) on test-literal args — the exact
    # "intentional subprocess" case S603/S607 exist to let callers opt out of.
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)  # noqa: S603, S607


def _init_repo(root: Path, files: Sequence[tuple[str, str]]) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    for rel, content in files:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")


def test_ls_tree_reads_committed_blob_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _init_repo(tmp_path, [("a.py", "x = 1\n"), ("src/b.py", "y = 2\n")])
    monkeypatch.chdir(tmp_path)

    rows = SubprocessGitRunner().ls_tree("HEAD")

    by_path = {row.path: row for row in rows}
    assert set(by_path) == {"a.py", "src/b.py"}
    for row in rows:
        assert row.obj_type == "blob"
        assert row.mode.startswith("100")
        assert len(row.blob_sha) == 40  # full git object SHA-1
