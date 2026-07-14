"""SubprocessGitRunner: the one real git I/O boundary.

Every other test drives a `ScriptedGitRunner` fake; this file is the sole place
that proves the real `git` wiring (argv, tab-delimited parse, blob rows, typed
adapter-failure boundary) actually works, against a real throwaway repo (git is
always available in CI). `repo_root` is injected explicitly (never the process
cwd), so these tests never `monkeypatch.chdir` — proving the runner does not
depend on the ambient working directory.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from vizsuite.adapters.git.runner import SubprocessGitRunner
from vizsuite.envelope import ErrorCode, VizError


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


def test_ls_tree_reads_committed_blob_rows(tmp_path: Path):
    _init_repo(tmp_path, [("a.py", "x = 1\n"), ("src/b.py", "y = 2\n")])

    rows = SubprocessGitRunner(repo_root=str(tmp_path)).ls_tree("HEAD")

    by_path = {row.path: row for row in rows}
    assert set(by_path) == {"a.py", "src/b.py"}
    for row in rows:
        assert row.obj_type == "blob"
        assert row.mode.startswith("100")
        assert len(row.blob_sha) == 40  # full git object SHA-1


def test_ls_tree_nonzero_exit_is_typed_adapter_failure(tmp_path: Path):
    # Not a git repo at all → `git ls-tree` exits nonzero; must surface as a
    # typed ADAPTER_FAILURE, not a raw CalledProcessError (→ opaque E_INTERNAL).
    with pytest.raises(VizError) as excinfo:
        SubprocessGitRunner(repo_root=str(tmp_path)).ls_tree("HEAD")

    assert excinfo.value.code == ErrorCode.ADAPTER_FAILURE


def _two_commit_repo(root: Path) -> tuple[str, str]:
    """A base commit (a.py) then a head commit (modifies a.py, adds b.py). Returns (base, head)."""
    _init_repo(root, [("a.py", "x = 1\n")])
    base = _git_out(root, "rev-parse", "HEAD")
    (root / "a.py").write_text("x = 2\n", encoding="utf-8")
    (root / "b.py").write_text("y = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "head")
    head = _git_out(root, "rev-parse", "HEAD")
    return base, head


def test_cat_exists_rev_list_diff_on_real_repo(tmp_path: Path):
    base, head = _two_commit_repo(tmp_path)
    runner = SubprocessGitRunner(repo_root=str(tmp_path))

    assert runner.cat_object_exists(head) is True
    assert runner.cat_object_exists("0" * 40) is False  # a well-formed but absent OID
    assert runner.rev_list(base, head) == [head]  # exactly one commit in base..head
    assert set(runner.diff_name_only(base, head)) == {"a.py", "b.py"}  # 3-dot net diff


def test_rev_list_nonzero_exit_is_typed_adapter_failure(tmp_path: Path):
    # A well-formed but nonexistent ref on both sides → `git rev-list` exits nonzero.
    _init_repo(tmp_path, [("a.py", "x = 1\n")])
    runner = SubprocessGitRunner(repo_root=str(tmp_path))

    with pytest.raises(VizError) as excinfo:
        runner.rev_list("0" * 40, "1" * 40)

    assert excinfo.value.code == ErrorCode.ADAPTER_FAILURE


def test_diff_name_only_nonzero_exit_is_typed_adapter_failure(tmp_path: Path):
    _init_repo(tmp_path, [("a.py", "x = 1\n")])
    runner = SubprocessGitRunner(repo_root=str(tmp_path))

    with pytest.raises(VizError) as excinfo:
        runner.diff_name_only("0" * 40, "1" * 40)

    assert excinfo.value.code == ErrorCode.ADAPTER_FAILURE


def test_churn_for_commits_sums_real_pydriller_rows(tmp_path: Path):
    base, head = _two_commit_repo(tmp_path)
    runner = SubprocessGitRunner(repo_root=str(tmp_path))
    head_only = runner.rev_list(base, head)

    rows = runner.churn_for_commits(head_only)

    by_path = {(row.new_path or row.old_path): row for row in rows}
    # the head commit modified a.py (1 added, 1 deleted) and added b.py (1 added).
    assert by_path["a.py"].added == 1
    assert by_path["a.py"].deleted == 1
    assert by_path["b.py"].added == 1
    assert by_path["b.py"].deleted == 0


def test_churn_for_commits_reads_commit_unreachable_from_head(tmp_path: Path):
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

    rows = SubprocessGitRunner(repo_root=str(tmp_path)).churn_for_commits([feature])

    by_path = {(row.new_path or row.old_path): row for row in rows}
    assert by_path["a.py"].added == 1
    assert by_path["a.py"].deleted == 1
    assert by_path["b.py"].added == 1


def test_archive_tar_streams_the_committed_tree(tmp_path: Path):
    # `git archive` reads the commit *tree object*, so the tar carries exactly the
    # committed blobs — the immutable-snapshot seam scc will scan in slice 3.
    _init_repo(tmp_path, [("a.py", "x = 1\n"), ("src/b.py", "y = 2\n")])

    tar_bytes = SubprocessGitRunner(repo_root=str(tmp_path)).archive_tar("HEAD")

    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
        members = {m.name: m for m in tar.getmembers() if m.isfile()}
        assert {"a.py", "src/b.py"} <= set(members)
        extracted = tar.extractfile("a.py")
        assert extracted is not None
        assert extracted.read() == b"x = 1\n"


def test_archive_tar_types_git_failure_as_adapter_failure(tmp_path: Path):
    # A failing `git archive` (here: an absent OID) must surface as a typed
    # ADAPTER_FAILURE, not a raw CalledProcessError that the CLI reports as
    # E_INTERNAL — the loud-boundary contract the other slice-3 adapters honor.
    _init_repo(tmp_path, [("a.py", "x = 1\n")])

    with pytest.raises(VizError) as excinfo:
        SubprocessGitRunner(repo_root=str(tmp_path)).archive_tar("0" * 40)  # well-formed, absent

    assert excinfo.value.code == ErrorCode.ADAPTER_FAILURE


def test_runner_never_reads_the_process_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # The load-bearing invariant: constructing the runner against `repo_root`
    # must work correctly even when the process cwd points somewhere unrelated
    # (here: a directory with no repo at all).
    _init_repo(tmp_path, [("a.py", "x = 1\n")])
    unrelated = tmp_path.parent / "unrelated-cwd"
    unrelated.mkdir(exist_ok=True)
    monkeypatch.chdir(unrelated)

    rows = SubprocessGitRunner(repo_root=str(tmp_path)).ls_tree("HEAD")

    assert {row.path for row in rows} == {"a.py"}
