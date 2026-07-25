"""Tests for the subprocess seam itself.

The real port's job is to turn every way a command can go wrong into a
CommandResult rather than an exception, because the layers above it report
anomalies and must never be interrupted by one."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gitclean.ports import (
    CommandResult,
    ScriptedCommands,
    SubprocessCommands,
    fail,
    ok,
)

# -- CommandResult -----------------------------------------------------------


def test_ok_is_exit_zero() -> None:
    assert ok().ok
    assert not fail().ok
    assert fail(code=127).returncode == 127


def test_out_strips_surrounding_whitespace() -> None:
    assert CommandResult(argv=(), returncode=0, stdout="  /repo\n", stderr="").out == "/repo"


def test_transcript_carries_the_command_exit_and_both_streams() -> None:
    result = CommandResult(
        argv=("git", "branch", "-D", "x"), returncode=1, stdout="out", stderr="err"
    )
    joined = "\n".join(result.transcript())
    assert "$ git branch -D x" in joined
    assert "exit: 1" in joined
    assert "out" in joined and "err" in joined


def test_transcript_omits_empty_streams_rather_than_showing_blank_headings() -> None:
    result = CommandResult(argv=("git", "status"), returncode=0, stdout="", stderr="   ")
    joined = "\n".join(result.transcript())
    assert "stdout" not in joined
    assert "stderr" not in joined


# -- the real port -----------------------------------------------------------


def test_git_runs_and_reports_success() -> None:
    result = SubprocessCommands().git(["--version"])
    assert result.ok
    assert "git version" in result.stdout


def test_a_nonzero_exit_is_a_result_not_an_exception() -> None:
    result = SubprocessCommands().git(["rev-parse", "--verify", "refs/heads/definitely-not-here"])
    assert not result.ok
    assert result.argv[0] == "git"


def test_a_missing_binary_becomes_exit_127(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(subprocess, "run", boom)
    result = SubprocessCommands().gh(["pr", "list"])
    assert result.returncode == 127
    assert "no such file" in result.stderr


def test_a_timeout_becomes_exit_124(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)

    monkeypatch.setattr(subprocess, "run", boom)
    result = SubprocessCommands(timeout=1).git(["log"])
    assert result.returncode == 124
    assert "timed out" in result.stderr


def test_has_gh_answers_from_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gitclean.ports.shutil.which", lambda _: None)
    assert not SubprocessCommands().has_gh()
    monkeypatch.setattr("gitclean.ports.shutil.which", lambda _: "/usr/bin/gh")
    assert SubprocessCommands().has_gh()


def test_cwd_is_honoured(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
    result = SubprocessCommands().git(["rev-parse", "--is-inside-work-tree"], cwd=tmp_path)
    assert result.out == "true"


# -- filesystem helpers ------------------------------------------------------


def test_write_text_creates_missing_parents(tmp_path: Path) -> None:
    port = SubprocessCommands()
    target = tmp_path / "deep" / "nested" / "keep"
    port.write_text(target, "x")
    assert port.exists(target)
    assert port.read_text(target) == "x"


def test_reading_a_missing_file_is_none_not_an_error(tmp_path: Path) -> None:
    assert SubprocessCommands().read_text(tmp_path / "absent") is None


def test_copy_file_creates_missing_parents(tmp_path: Path) -> None:
    port = SubprocessCommands()
    source = tmp_path / "a.txt"
    source.write_text("payload")
    dest = tmp_path / "salvage" / "untracked" / "a.txt"
    port.copy_file(source, dest)
    assert dest.read_text() == "payload"


# -- the fake ----------------------------------------------------------------


def test_an_unscripted_call_fails_loudly_naming_the_argv() -> None:
    """A benign default would let a test go green while production asks git
    something the test never anticipated."""
    port = ScriptedCommands()
    with pytest.raises(AssertionError, match="git status --short"):
        port.git(["status", "--short"])


def test_the_longest_matching_prefix_wins() -> None:
    port = ScriptedCommands(git={"branch": ok("generic"), "branch --merged main": ok("specific")})
    assert port.git(["branch", "--merged", "main"]).out == "specific"
    assert port.git(["branch", "-r"]).out == "generic"


def test_a_queued_answer_advances_per_call() -> None:
    """For the calls whose answer legitimately changes across a run -- a ref
    that resolves before deletion and not after."""
    port = ScriptedCommands(git={"show-ref": [ok("present"), fail()]})
    assert port.git(["show-ref", "x"]).ok
    assert not port.git(["show-ref", "x"]).ok


def test_an_exhausted_queue_fails_loudly() -> None:
    port = ScriptedCommands(git={"show-ref": [ok()]})
    port.git(["show-ref", "x"])
    with pytest.raises(AssertionError):
        port.git(["show-ref", "x"])


def test_the_fake_records_the_full_argv() -> None:
    port = ScriptedCommands(git={"branch": ok()}, gh={"pr": ok("[]")})
    port.git(["branch", "-D", "x"])
    port.gh(["pr", "list"])
    assert port.transcript == [("git", "branch", "-D", "x"), ("gh", "pr", "list")]


def test_the_fake_models_the_filesystem_in_memory() -> None:
    port = ScriptedCommands()
    assert not port.exists(Path("/salvage/keep"))
    port.write_text(Path("/salvage/keep"), "x")
    assert port.exists(Path("/salvage/keep"))
    assert port.read_text(Path("/salvage/keep")) == "x"
    assert port.read_text(Path("/absent")) is None
