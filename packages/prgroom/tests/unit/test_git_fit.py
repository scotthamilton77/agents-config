"""Fit-test for the git adapter (§7.6).

Exercises the full public surface of ``GitCli`` against a ``RecordedRunner`` /
``TimeoutRunner`` — the subprocess boundary is the only mock point. Each
failure-classification arm (push-rejected vs git-transient) is driven by a
recorded ``CommandResult`` reproducing real git stderr, so the mapping to the
existing ``ErrorCode`` registry is exercised, not pinned at the definition site.
"""

from __future__ import annotations

import pytest

from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.git import GitCli, GitClient
from prgroom.proc import CommandResult
from tests.fakes import MissingBinaryRunner, RecordedRunner, TimeoutRunner


def _ok(stdout: str) -> CommandResult:
    return CommandResult(returncode=0, stdout=stdout, stderr="")


def _fail(stderr: str) -> CommandResult:
    return CommandResult(returncode=1, stdout="", stderr=stderr)


# ── structural fit ──


def test_git_cli_structurally_satisfies_protocol() -> None:
    assert isinstance(GitCli(RecordedRunner([])), GitClient)


# ── happy paths ──


def test_head_sha_strips_output() -> None:
    runner = RecordedRunner([_ok("a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4\n")])
    client = GitCli(runner)
    assert client.head_sha() == "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4"
    assert runner.calls[0] == ["git", "rev-parse", "HEAD"]


def test_current_branch_strips_output() -> None:
    runner = RecordedRunner([_ok("feature-x\n")])
    client = GitCli(runner)
    assert client.current_branch() == "feature-x"
    # `--abbrev-ref HEAD` yields the branch name (or the literal "HEAD" if detached).
    assert runner.calls[0] == ["git", "rev-parse", "--abbrev-ref", "HEAD"]


def test_rev_list_splits_lines() -> None:
    runner = RecordedRunner([_ok("sha1\nsha2\nsha3\n")])
    client = GitCli(runner)
    assert client.rev_list("origin/main..HEAD") == ["sha1", "sha2", "sha3"]
    assert runner.calls[0] == ["git", "rev-list", "origin/main..HEAD"]


def test_rev_list_empty_output_is_empty_list() -> None:
    runner = RecordedRunner([_ok("\n")])
    client = GitCli(runner)
    assert client.rev_list("origin/main..HEAD") == []


def test_push_succeeds_returns_none() -> None:
    runner = RecordedRunner([_ok("")])
    client = GitCli(runner)
    assert client.push("origin", "feature-branch") is None
    assert runner.calls[0] == ["git", "push", "origin", "feature-branch"]


def test_stash_succeeds_returns_none() -> None:
    runner = RecordedRunner([_ok("Saved working directory")])
    client = GitCli(runner)
    assert client.stash() is None
    assert runner.calls[0] == ["git", "stash"]


def test_log_returns_raw_output_and_builds_argv() -> None:
    # `log` is a snapshot read (§8.1 branch_state): the recent-commits text is
    # passed verbatim to the fix agent, so the adapter returns it unparsed.
    runner = RecordedRunner([_ok("abc Subject one\ndef Subject two\n")])
    client = GitCli(runner)
    assert client.log("origin/main..HEAD") == "abc Subject one\ndef Subject two\n"
    assert runner.calls[0] == ["git", "log", "origin/main..HEAD"]


def test_diff_stat_returns_raw_output_and_builds_argv() -> None:
    # `diff_stat` is the §8.1 diff-since-base summary; raw text, no parsing.
    runner = RecordedRunner([_ok(" file.py | 3 +++\n 1 file changed\n")])
    client = GitCli(runner)
    assert client.diff_stat("origin/main..HEAD") == " file.py | 3 +++\n 1 file changed\n"
    assert runner.calls[0] == ["git", "diff", "--stat", "origin/main..HEAD"]


def test_log_failure_classifies_as_git_transient() -> None:
    # A failed snapshot read reuses _run's classification — a non-push local
    # failure is conservatively transient (the snapshot retries next cadence).
    runner = RecordedRunner([_fail("fatal: bad revision 'origin/main..HEAD'\n")])
    client = GitCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.log("origin/main..HEAD")
    assert exc.value.code is ErrorCode.RUNTIME_GIT_TRANSIENT


def test_diff_stat_timeout_classifies_as_git_transient() -> None:
    client = GitCli(TimeoutRunner())
    with pytest.raises(PrgroomError) as exc:
        client.diff_stat("origin/main..HEAD")
    assert exc.value.code is ErrorCode.RUNTIME_GIT_TRANSIENT


# ── failure classification ──


def test_push_non_fast_forward_classifies_as_push_rejected() -> None:
    stderr = (
        "To github.com:octo/demo.git\n"
        " ! [rejected]        feature-branch -> feature-branch (non-fast-forward)\n"
        "error: failed to push some refs to 'github.com:octo/demo.git'\n"
    )
    runner = RecordedRunner([_fail(stderr)])
    client = GitCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.push("origin", "feature-branch")
    assert exc.value.code is ErrorCode.RUNTIME_PUSH_REJECTED
    assert exc.value.tier is Tier.RUNTIME_TERMINAL_USER


def test_push_protected_branch_classifies_as_push_rejected() -> None:
    stderr = (
        " ! [remote rejected] main -> main (protected branch hook declined)\n"
        "error: failed to push some refs\n"
    )
    runner = RecordedRunner([_fail(stderr)])
    client = GitCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.push("origin", "main")
    assert exc.value.code is ErrorCode.RUNTIME_PUSH_REJECTED


def test_push_hook_declined_classifies_as_push_rejected() -> None:
    stderr = " ! [remote rejected] feature -> feature (pre-receive hook declined)\n"
    runner = RecordedRunner([_fail(stderr)])
    client = GitCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.push("origin", "feature")
    assert exc.value.code is ErrorCode.RUNTIME_PUSH_REJECTED


def test_push_network_failure_classifies_as_git_transient() -> None:
    stderr = (
        "fatal: unable to access 'https://github.com/octo/demo.git/': "
        "Could not resolve host: github.com\n"
    )
    runner = RecordedRunner([_fail(stderr)])
    client = GitCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.push("origin", "feature")
    assert exc.value.code is ErrorCode.RUNTIME_GIT_TRANSIENT
    assert exc.value.tier is Tier.RUNTIME_TRANSIENT


def test_push_connection_timeout_classifies_as_git_transient() -> None:
    stderr = (
        "fatal: unable to access 'https://github.com/octo/demo.git/': "
        "Failed to connect to github.com port 443: Connection timed out\n"
    )
    runner = RecordedRunner([_fail(stderr)])
    client = GitCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.push("origin", "feature")
    assert exc.value.code is ErrorCode.RUNTIME_GIT_TRANSIENT


def test_subprocess_timeout_classifies_as_git_transient() -> None:
    # A hung network op surfaces as TimeoutExpired from the boundary, not a
    # non-zero return; the adapter must still map it to RUNTIME_GIT_TRANSIENT.
    client = GitCli(TimeoutRunner())
    with pytest.raises(PrgroomError) as exc:
        client.push("origin", "feature")
    assert exc.value.code is ErrorCode.RUNTIME_GIT_TRANSIENT


def test_unclassifiable_git_failure_falls_back_to_git_transient() -> None:
    # A non-push, non-network local failure is conservatively transient: a
    # retry on the next cadence is harmless, whereas wrongly marking it terminal
    # would gate a PR on a possibly-flaky local condition.
    runner = RecordedRunner([_fail("fatal: some unexpected git error\n")])
    client = GitCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.push("origin", "feature")
    assert exc.value.code is ErrorCode.RUNTIME_GIT_TRANSIENT


def test_git_forwards_a_bounded_timeout_to_the_runner() -> None:
    # A hung git call must not block forever holding the PR lock; the adapter
    # passes a bounded default timeout to the boundary on every call.
    runner = RecordedRunner([_ok("")])
    GitCli(runner).head_sha()
    assert runner.timeouts[0] is not None
    assert runner.timeouts[0] > 0


def test_git_missing_binary_classifies_as_git_terminal() -> None:
    # A missing `git` binary surfaces as OSError from the boundary — a permanent
    # local-environment gap a blind retry will never fix. The adapter maps it to
    # the terminal code (exit 77, human-gated), mirroring the gh adapter's own
    # OSError->RUNTIME_GH_TERMINAL mapping; it never floats up as a raw traceback
    # and never masquerades as a retryable transient.
    client = GitCli(MissingBinaryRunner())
    with pytest.raises(PrgroomError) as exc:
        client.push("origin", "feature")
    assert exc.value.code is ErrorCode.RUNTIME_GIT_TERMINAL
    assert exc.value.tier is Tier.RUNTIME_TERMINAL_USER
