"""`materialize()` — extract the git-archive tar to a tempdir, sanity-check the estate.

The snapshot scc scans (slice 3) is extracted from `git archive`, never the live
checkout, so a dirty working tree can never leak into the artifact (the Path-C
invariant, proven by the real-subprocess test). `materialize` self-cleans its
tempdir on any failure; on success the caller tears the returned dir down in a
`finally`. The fake-driven tests exercise the extract + estate-sanity logic in
isolation; the real-`git` test proves the archive seam end-to-end.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.fakes import ScriptedGitRunner, tar_of
from vizsuite.adapters.git.runner import SubprocessGitRunner
from vizsuite.envelope import ErrorCode, VizError
from vizsuite.reconcile.snapshot import materialize


def test_materialize_extracts_the_archive_at_the_head_oid() -> None:
    git = ScriptedGitRunner(archive_tar_bytes=tar_of({"a.py": "x = 1\n", "src/b.py": "y = 2\n"}))

    snapshot = materialize(git, "head111", {"a.py", "src/b.py"})

    try:
        assert snapshot.is_dir()
        assert (snapshot / "a.py").read_text(encoding="utf-8") == "x = 1\n"
        assert (snapshot / "src" / "b.py").read_text(encoding="utf-8") == "y = 2\n"
        # The archive is taken at the resolved head OID, never the checkout's HEAD.
        assert ("archive_tar", "head111") in git.calls
    finally:
        shutil.rmtree(snapshot, ignore_errors=True)


def test_materialize_missing_estate_path_alarms_and_self_cleans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An estate path the archive dropped (an `export-ignore` gitattribute in a
    # target repo) must alarm loudly, not yield a silently-thin snapshot — and the
    # tempdir must not leak when it does.
    git = ScriptedGitRunner(archive_tar_bytes=tar_of({"a.py": "x = 1\n"}))
    made = tmp_path / "snap"
    monkeypatch.setattr("vizsuite.reconcile.snapshot.mkdtemp", lambda *_a, **_k: str(made))

    with pytest.raises(VizError) as excinfo:
        materialize(git, "head111", {"a.py", "gone.py"})

    assert excinfo.value.code == ErrorCode.ADAPTER_FAILURE
    assert "gone.py" in str(excinfo.value.detail)
    assert not made.exists()  # self-cleaned — no leaked tempdir


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)  # noqa: S603, S607


def test_materialize_snapshot_cannot_leak_a_dirty_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Commit content A, then dirty the worktree (edit tracked -> B, add untracked).
    # The snapshot at the commit must be exactly A with the untracked file absent —
    # the test a guard-based "is the tree clean?" design could never pass.
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "tracked.py").write_text("A\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "A")
    (tmp_path / "tracked.py").write_text("B\n", encoding="utf-8")  # modify tracked
    (tmp_path / "untracked.py").write_text("leak\n", encoding="utf-8")  # add untracked
    monkeypatch.chdir(tmp_path)

    snapshot = materialize(SubprocessGitRunner(), "HEAD", {"tracked.py"})

    try:
        assert (snapshot / "tracked.py").read_text(encoding="utf-8") == "A\n"  # committed, not B
        assert not (snapshot / "untracked.py").exists()  # untracked never leaks
    finally:
        shutil.rmtree(snapshot, ignore_errors=True)
