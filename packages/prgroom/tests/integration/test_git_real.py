"""Integration test: the git adapter against real ``git`` on a fixture repo (§7.6).

The unit fit-test proves classification against recorded boundary output; this
narrower integration test proves the happy-path adapter actually drives real
``git`` correctly — ``head_sha`` and ``rev_list`` parse genuine git output, not
just our hand-recorded fixtures. Uses ``SubprocessRunner`` (the real boundary)
on a throwaway ``tmp_path`` repo.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from prgroom.errors import ErrorCode, PrgroomError
from prgroom.git import GitCli
from prgroom.proc import CommandResult, CommandRunner, SubprocessRunner

_HAS_GIT = shutil.which("git") is not None
pytestmark = pytest.mark.skipif(not _HAS_GIT, reason="git not on PATH")


class _CwdRunner:
    """A SubprocessRunner pinned to a working directory (so the test repo is the cwd).

    Mirrors the production :class:`SubprocessRunner` C-locale pinning so the
    push-rejection assertion is a faithful ground-truth anchor for both the
    English marker-matching AND the locale fix — the installed git's real stderr
    under ``C`` must contain a recognized rejection marker.
    """

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    def run(
        self,
        argv: list[str],
        *,
        input: str | None = None,  # noqa: ARG002  # Protocol signature; unused here
        timeout: float | None = None,  # noqa: ARG002  # Protocol signature; unused here
    ) -> CommandResult:
        env = {**os.environ, "LC_ALL": "C", "LANG": "C"}
        completed = subprocess.run(  # noqa: S603  # internally-built git argv on a tmp fixture repo
            argv, capture_output=True, text=True, check=False, cwd=self._cwd, env=env
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603  # test-only fixture-repo setup
        ["git", *args],  # noqa: S607  # `git` on PATH is fine in a test fixture
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "a.txt").write_text("one\n")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-m", "first")
    (tmp_path / "b.txt").write_text("two\n")
    _git(tmp_path, "add", "b.txt")
    _git(tmp_path, "commit", "-m", "second")
    return tmp_path


def test_cwd_runner_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(_CwdRunner(tmp_path), CommandRunner)


def test_head_sha_against_real_git(repo: Path) -> None:
    client = GitCli(_CwdRunner(repo))
    sha = client.head_sha()
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


def test_rev_list_counts_real_commits(repo: Path) -> None:
    client = GitCli(_CwdRunner(repo))
    assert len(client.rev_list("HEAD~1..HEAD")) == 1
    assert len(client.rev_list("HEAD")) == 2


def test_subprocess_runner_runs_real_git_version() -> None:
    # The production runner itself drives a real binary end-to-end.
    result = SubprocessRunner().run(["git", "--version"])
    assert result.returncode == 0
    assert result.stdout.startswith("git version")


def _clone_with_identity(origin: Path, dest: Path) -> None:
    _git(dest.parent, "clone", str(origin), dest.name)
    _git(dest, "config", "user.email", "test@example.com")
    _git(dest, "config", "user.name", "Test")


def test_push_rejection_against_real_git(tmp_path: Path) -> None:
    # Ground-truth anchor: drive the installed git to emit a REAL non-fast-forward
    # rejection (no network — a bare file:// origin) and assert GitCli classifies
    # it terminal. A future git stderr reword would fail HERE rather than silently
    # misclassifying in production. Doubles as the locale fix's anchor (C locale).
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", "origin.git")

    clone_a = tmp_path / "a"
    _clone_with_identity(origin, clone_a)
    (clone_a / "f.txt").write_text("a1\n")
    _git(clone_a, "add", "f.txt")
    _git(clone_a, "commit", "-m", "a1")
    _git(clone_a, "push", "origin", "main")

    # Clone B starts from the same origin tip, then both diverge.
    clone_b = tmp_path / "b"
    _clone_with_identity(origin, clone_b)

    (clone_a / "f.txt").write_text("a2\n")
    _git(clone_a, "add", "f.txt")
    _git(clone_a, "commit", "-m", "a2")
    _git(clone_a, "push", "origin", "main")  # origin now ahead of B

    (clone_b / "g.txt").write_text("b1\n")
    _git(clone_b, "add", "g.txt")
    _git(clone_b, "commit", "-m", "b1")

    client = GitCli(_CwdRunner(clone_b))
    with pytest.raises(PrgroomError) as exc:
        client.push("origin", "main")  # non-fast-forward -> rejected
    assert exc.value.code is ErrorCode.RUNTIME_PUSH_REJECTED
