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
    assert target.read_text() == "x"


# -- archiving ---------------------------------------------------------------


def test_an_archive_round_trips_a_real_directory(tmp_path: Path) -> None:
    port = SubprocessCommands()
    source = tmp_path / "tree"
    (source / "sub").mkdir(parents=True)
    (source / "sub" / "a.txt").write_text("payload")
    dest = tmp_path / "salvage" / "deep" / "tree.tar.gz"

    assert port.create_archive(source, dest).ok
    listing = port.list_archive(dest)
    assert listing.ok
    assert "./sub/a.txt" in listing.stdout

    restored = tmp_path / "restored"
    restored.mkdir()
    subprocess.run(["tar", "-xzf", str(dest), "-C", str(restored)], check=True)  # noqa: S603, S607
    assert (restored / "sub" / "a.txt").read_text() == "payload"


def test_an_archive_keeps_a_symlink_as_a_symlink(tmp_path: Path) -> None:
    """`shutil.copy2` follows links, so an untracked link to ~/.ssh/id_rsa
    would copy the key's bytes into the salvage directory -- and it raises
    outright on a dangling one."""
    port = SubprocessCommands()
    source = tmp_path / "tree"
    source.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("private key")
    (source / "link").symlink_to(secret)
    (source / "dangling").symlink_to(tmp_path / "not-there")

    dest = tmp_path / "tree.tar.gz"
    assert port.create_archive(source, dest).ok

    restored = tmp_path / "restored"
    restored.mkdir()
    subprocess.run(["tar", "-xzf", str(dest), "-C", str(restored)], check=True)  # noqa: S603, S607
    # Still a link, still pointing where it pointed: the secret's bytes were
    # never copied into the salvage, and the dangling link did not raise.
    assert (restored / "link").is_symlink()
    assert (restored / "link").readlink() == secret
    assert (restored / "dangling").is_symlink()


def test_an_archive_captures_ignored_files_and_excludes_dot_git(tmp_path: Path) -> None:
    port = SubprocessCommands()
    source = tmp_path / "tree"
    (source / ".git").mkdir(parents=True)
    (source / ".git" / "config").write_text("[core]")
    (source / ".env").write_text("TOKEN=hunter2")
    (source / ".gitignore").write_text(".env\n")

    dest = tmp_path / "tree.tar.gz"
    assert port.create_archive(source, dest).ok
    listing = port.list_archive(dest).stdout
    assert "./.env" in listing
    assert ".git/config" not in listing


def test_listing_a_missing_archive_is_a_result_not_an_exception(tmp_path: Path) -> None:
    assert not SubprocessCommands().list_archive(tmp_path / "absent.tar.gz").ok


def test_an_archive_does_not_capture_itself(tmp_path: Path) -> None:
    """--salvage-dir may legitimately point inside the worktree being salvaged.
    GNU tar warns about archiving its own output; BSD tar, which is what ships
    on macOS, does not."""
    port = SubprocessCommands()
    source = tmp_path / "tree"
    source.mkdir()
    (source / "a.txt").write_text("payload")

    nested = port.create_archive(source, source / "salvage" / "tree.tar.gz")
    assert nested.ok
    listing = port.list_archive(source / "salvage" / "tree.tar.gz").stdout
    assert "./a.txt" in listing
    assert "salvage" not in listing


def test_an_archive_written_into_the_root_it_archives_skips_only_itself(tmp_path: Path) -> None:
    port = SubprocessCommands()
    source = tmp_path / "tree"
    source.mkdir()
    (source / "a.txt").write_text("payload")

    assert port.create_archive(source, source / "tree.tar.gz").ok
    listing = port.list_archive(source / "tree.tar.gz").stdout
    assert "./a.txt" in listing
    assert "./tree.tar.gz" not in listing


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


def test_the_fake_models_written_files_in_memory() -> None:
    port = ScriptedCommands()
    port.write_text(Path("/salvage/keep"), "x")
    assert port.files["/salvage/keep"] == "x"


def test_an_unscripted_archive_call_fails_loudly() -> None:
    """Same discipline as the command tables: a salvage that silently
    'succeeded' in a test is exactly what this fake exists to catch."""
    port = ScriptedCommands()
    with pytest.raises(AssertionError, match="archive answer"):
        port.create_archive(Path("/repo/wt"), Path("/salvage/wt.tar.gz"))
    with pytest.raises(AssertionError, match="archive listing"):
        ScriptedCommands().list_archive(Path("/salvage/wt.tar.gz"))


def test_the_longest_matching_key_wins_so_a_shorter_one_cannot_absorb_it() -> None:
    """Two of gitclean's `for-each-ref` calls share a prefix: the survey's
    batch read starts with `%(refname)` and so does the post-delete verifier.
    Matching by longest key is what keeps them apart -- were it first-match or
    shortest, a test scripting one would silently answer the other, and the
    verifier would 'confirm' a deletion using the survey's output."""
    port = ScriptedCommands(
        git={
            "for-each-ref --format=%(refname) refs/heads/gone": ok(""),
            "for-each-ref --format=%(refname)\x1f": ok("survey-batch-output"),
        }
    )

    verifier = port.git(["for-each-ref", "--format=%(refname)", "refs/heads/gone"])
    survey_read = port.git(["for-each-ref", "--format=%(refname)\x1f%(objectname)", "refs/heads"])

    assert verifier.stdout == ""
    assert survey_read.stdout == "survey-batch-output"
