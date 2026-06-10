"""Integration test: the git adapter against real ``git`` on a fixture repo (§7.6).

The unit fit-test proves classification against recorded boundary output; this
narrower integration test proves the happy-path adapter actually drives real
``git`` correctly — ``head_sha`` and ``rev_list`` parse genuine git output, not
just our hand-recorded fixtures. Uses ``SubprocessRunner`` (the real boundary)
on a throwaway ``tmp_path`` repo.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from prgroom.git import GitCli
from prgroom.proc import CommandResult, CommandRunner, SubprocessRunner

_HAS_GIT = shutil.which("git") is not None
pytestmark = pytest.mark.skipif(not _HAS_GIT, reason="git not on PATH")


class _CwdRunner:
    """A SubprocessRunner pinned to a working directory (so the test repo is the cwd)."""

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    def run(
        self,
        argv: list[str],
        *,
        input: str | None = None,  # noqa: ARG002  # Protocol signature; unused here
        timeout: float | None = None,  # noqa: ARG002  # Protocol signature; unused here
    ) -> CommandResult:
        completed = subprocess.run(  # noqa: S603  # internally-built git argv on a tmp fixture repo
            argv, capture_output=True, text=True, check=False, cwd=self._cwd
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
