"""SubprocessGitRunner: the one real git I/O boundary in slice 1.

Every other test drives a `ScriptedGitRunner` fake; this file is the sole place
that proves the `git ls-tree -r` wiring (argv, tab-delimited parse, blob rows)
actually works, against a real throwaway repo (git is always available in CI).
Slice 2 extends this seam with cat_object_exists/rev_list/diff/churn/etc.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from vizsuite.adapters.git.runner import SubprocessGitRunner


def _git(cwd: Path, *args: str) -> None:
    # Fixture setup runs a known binary (git) on test-literal args — the exact
    # "intentional subprocess" case S603/S607 exist to let callers opt out of.
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)  # noqa: S603, S607


def _git_out(cwd: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


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


def _two_commit_repo(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """A base commit (a.py) then a head commit (modifies a.py, adds b.py). Returns (base, head)."""
    _init_repo(root, [("a.py", "x = 1\n")])
    base = _git_out(root, "rev-parse", "HEAD")
    (root / "a.py").write_text("x = 2\n", encoding="utf-8")
    (root / "b.py").write_text("y = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "head")
    head = _git_out(root, "rev-parse", "HEAD")
    monkeypatch.chdir(root)
    return base, head


def test_cat_exists_rev_list_diff_on_real_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    base, head = _two_commit_repo(tmp_path, monkeypatch)
    runner = SubprocessGitRunner()

    assert runner.cat_object_exists(head) is True
    assert runner.cat_object_exists("0" * 40) is False  # a well-formed but absent OID
    assert runner.rev_list(base, head) == [head]  # exactly one commit in base..head
    assert set(runner.diff_name_only(base, head)) == {"a.py", "b.py"}  # 3-dot net diff


def test_churn_for_commits_sums_real_pydriller_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    base, head = _two_commit_repo(tmp_path, monkeypatch)
    head_only = SubprocessGitRunner().rev_list(base, head)

    rows = SubprocessGitRunner().churn_for_commits(head_only)

    by_path = {(row.new_path or row.old_path): row for row in rows}
    # the head commit modified a.py (1 added, 1 deleted) and added b.py (1 added).
    assert by_path["a.py"].added == 1
    assert by_path["a.py"].deleted == 1
    assert by_path["b.py"].added == 1
    assert by_path["b.py"].deleted == 0


def test_churn_for_commits_reads_commit_unreachable_from_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # The real case: a PR head not merged into the checked-out branch. PyDriller's
    # branch-traversal filter (Repository(only_commits=...)) would silently yield
    # nothing for it; churn must read the commit object directly by SHA.
    _init_repo(tmp_path, [("a.py", "x = 1\n")])
    base_branch = _git_out(tmp_path, "rev-parse", "--abbrev-ref", "HEAD")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "feature")
    feature = _git_out(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "-q", base_branch)  # HEAD no longer reaches `feature`
    monkeypatch.chdir(tmp_path)

    rows = SubprocessGitRunner().churn_for_commits([feature])

    by_path = {(row.new_path or row.old_path): row for row in rows}
    assert by_path["a.py"].added == 1
    assert by_path["a.py"].deleted == 1
    assert by_path["b.py"].added == 1


def test_archive_tar_streams_the_committed_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # `git archive` reads the commit *tree object*, so the tar carries exactly the
    # committed blobs — the immutable-snapshot seam scc will scan in slice 3.
    _init_repo(tmp_path, [("a.py", "x = 1\n"), ("src/b.py", "y = 2\n")])
    monkeypatch.chdir(tmp_path)

    tar_bytes = SubprocessGitRunner().archive_tar("HEAD")

    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
        members = {m.name: m for m in tar.getmembers() if m.isfile()}
        assert {"a.py", "src/b.py"} <= set(members)
        extracted = tar.extractfile("a.py")
        assert extracted is not None
        assert extracted.read() == b"x = 1\n"
