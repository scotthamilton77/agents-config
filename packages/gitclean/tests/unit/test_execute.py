"""Tests for salvage, deletion, and verification.

The interesting cases are the ones where git reports success and the thing is
still there. A tool that trusts exit codes cannot tell those from real
successes, which is why every deletion re-asks."""

from __future__ import annotations

from datetime import UTC, datetime

from conftest import make_branch, make_survey

from gitclean.execute import Executor, default_salvage_dir, slug
from gitclean.model import Disposition, Plan, Risk, Target, TargetKind
from gitclean.ports import CommandResult, ScriptedCommands, fail, ok


def target(
    kind: TargetKind,
    name: str,
    *,
    risk: Risk = Risk.NONE,
) -> Target:
    prefix = {
        TargetKind.WORKTREE: "worktree",
        TargetKind.BRANCH: "branch",
        TargetKind.REMOTE_BRANCH: "remote",
    }[kind]
    return Target(
        id=f"{prefix}:{name}",
        kind=kind,
        name=name,
        disposition=Disposition.SAFE,
        risk=risk,
        reasons=(),
        last_activity=None,
        salvage_needed=risk is not Risk.NONE,
    )


def plan(*targets: Target, dry_run: bool = False, salvage_dir: str | None = "/salvage") -> Plan:
    return Plan(targets=targets, salvage_dir=salvage_dir, dry_run=dry_run)


def run(port: ScriptedCommands, the_plan: Plan, survey=None):  # type: ignore[no-untyped-def]
    return Executor(port, survey if survey is not None else make_survey()).run(the_plan)


# -- dry run -----------------------------------------------------------------


def test_dry_run_issues_no_commands() -> None:
    port = ScriptedCommands()
    report = run(port, plan(target(TargetKind.BRANCH, "feat/x"), dry_run=True))
    assert port.transcript == []
    assert report.deletions[0].deleted is False
    assert "dry run" in report.deletions[0].detail


def test_dry_run_announces_the_salvage_step() -> None:
    port = ScriptedCommands()
    report = run(
        port,
        plan(target(TargetKind.BRANCH, "wip", risk=Risk.RECOVERABLE), dry_run=True),
    )
    assert "after salvage" in report.deletions[0].detail


# -- local branch ------------------------------------------------------------


def test_branch_deletion_is_verified_by_re_asking_git() -> None:
    port = ScriptedCommands(
        git={
            "branch -D -- feat/x": ok(),
            "for-each-ref --format=%(refname) refs/heads/feat/x": ok(""),
        }
    )
    report = run(port, plan(target(TargetKind.BRANCH, "feat/x")))
    assert report.ok
    assert report.deletions[0].verified


def test_a_ref_surviving_a_successful_delete_is_an_anomaly() -> None:
    """`git branch -D` exited 0 and the ref is still there. Reporting success
    here is how cleanup silently does nothing."""
    port = ScriptedCommands(
        git={
            "branch -D -- feat/x": ok(),
            "for-each-ref --format=%(refname) refs/heads/feat/x": ok("refs/heads/feat/x"),
        }
    )
    report = run(port, plan(target(TargetKind.BRANCH, "feat/x")))
    assert not report.ok
    assert report.anomalies[0].stage == "verify"
    assert not report.deletions[0].deleted


def test_a_broken_ref_probe_is_unverified_not_deleted() -> None:
    """`show-ref --verify` cannot express this: it exits nonzero both when the
    ref is absent and when the command failed, so a fatal error read as a
    successful deletion. `for-each-ref` exits 0 and answers in stdout."""
    port = ScriptedCommands(
        git={
            "branch -D -- feat/x": ok(),
            "for-each-ref --format=%(refname) refs/heads/feat/x": fail("fatal: bad repository"),
        }
    )
    report = run(port, plan(target(TargetKind.BRANCH, "feat/x")))
    assert not report.ok
    assert not report.deletions[0].deleted
    assert report.deletions[0].detail == "deletion unverified"
    assert "bad repository" in "\n".join(report.anomalies[0].transcript)


def test_a_failed_delete_carries_the_command_transcript() -> None:
    port = ScriptedCommands(
        git={"branch -D -- feat/x": fail("error: branch is checked out", code=1)}
    )
    report = run(port, plan(target(TargetKind.BRANCH, "feat/x")))
    anomaly = report.anomalies[0]
    assert anomaly.stage == "delete"
    joined = "\n".join(anomaly.transcript)
    assert "git branch -D -- feat/x" in joined
    assert "exit: 1" in joined
    assert "branch is checked out" in joined


# -- worktree ----------------------------------------------------------------


def test_worktree_removal_is_verified_against_the_listing() -> None:
    port = ScriptedCommands(
        git={
            "worktree remove -- /repo/wt": ok(),
            "worktree prune": ok(),
            "worktree list --porcelain": ok("worktree /repo\nHEAD abc\n"),
        }
    )
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt")))
    assert report.ok
    assert report.deletions[0].verified


def test_worktree_still_listed_after_removal_is_an_anomaly() -> None:
    port = ScriptedCommands(
        git={
            "worktree remove -- /repo/wt": ok(),
            "worktree prune": ok(),
            "worktree list --porcelain": ok("worktree /repo\n\nworktree /repo/wt\n"),
        }
    )
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt")))
    assert not report.ok
    assert report.anomalies[0].stage == "verify"


def test_a_clean_worktree_is_removed_without_forcing() -> None:
    """--force is not free: it is what turns git's own dirt check off. A
    worktree the survey found clean has nothing to force past, so spending it
    here would leave nothing to catch a tree that changed since."""
    port = ScriptedCommands(
        git={
            "worktree remove -- /repo/wt": ok(),
            "worktree prune": ok(),
            "worktree list --porcelain": ok("worktree /repo\n"),
        }
    )
    run(port, plan(target(TargetKind.WORKTREE, "/repo/wt")))

    removal = next(call for call in port.transcript if call[:3] == ("git", "worktree", "remove"))
    assert "--force" not in removal


def test_a_worktree_that_went_dirty_since_the_survey_is_not_destroyed() -> None:
    """The window between survey and execution is real -- an agent writes a
    file, and the tree that was judged clean no longer is. git refuses to
    remove it, and that refusal is the only thing standing between those
    changes and deletion, because nothing was salvaged: the survey saw no
    reason to.

    So the refusal must surface as an anomaly carrying git's own words, and
    the worktree must still be there."""
    port = ScriptedCommands(
        git={
            "worktree remove -- /repo/wt": fail(
                "fatal: '/repo/wt' contains modified or untracked files, use --force to delete it",
                code=128,
            )
        }
    )

    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt")))

    assert not report.ok
    assert not report.deletions[0].deleted
    assert "not there when it was surveyed" in report.anomalies[0].message
    assert any(
        "contains modified or untracked files" in line for line in report.anomalies[0].transcript
    )


def test_a_salvaged_worktree_is_forced_because_the_content_is_already_archived() -> None:
    port = _worktree_salvage_port()

    run(port, plan(target(TargetKind.WORKTREE, "/repo/wt", risk=Risk.DATA_LOSS)))

    removal = next(call for call in port.transcript if call[:3] == ("git", "worktree", "remove"))
    assert "--force" in removal


def test_an_unlistable_worktree_check_is_unverified_not_removed() -> None:
    """Absence from output that was never produced is not evidence. Empty
    stdout on a failed command previously read as 'gone'."""
    port = ScriptedCommands(
        git={
            "worktree remove -- /repo/wt": ok(),
            "worktree prune": ok(),
            "worktree list --porcelain": fail("fatal: not a git repository"),
        }
    )
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt")))
    assert not report.ok
    assert not report.deletions[0].deleted
    assert report.deletions[0].detail == "deletion unverified"


# -- remote branch -----------------------------------------------------------

REMOTE_HEAD = "0" * 40
"""What `make_branch` publishes as a tip, and so what the lease is taken at."""


def _remote_survey(name: str = "origin/feat/x"):  # type: ignore[no-untyped-def]
    """A survey that has actually seen the remote branch.

    The executor leases against the commit the survey judged, so a remote
    deletion test that omits the branch is testing the refusal path, not the
    deletion path."""
    return make_survey(
        branches=(make_branch(name, is_remote=True, remote="origin", upstream=None),)
    )


def test_remote_deletion_is_confirmed_against_the_server() -> None:
    port = ScriptedCommands(
        git={
            "push --force-with-lease": ok(),
            "ls-remote --heads origin feat/x": ok(""),
            "remote prune origin": ok(),
        }
    )
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")), _remote_survey())
    assert report.ok
    assert report.deletions[0].verified


def test_the_remote_delete_is_leased_to_the_commit_that_was_judged() -> None:
    """Every verdict about a remote branch came from a local cache of it. If
    the server has moved since the last fetch, those commits were never judged
    -- the lease is what makes the server refuse rather than discard them."""
    port = ScriptedCommands(
        git={
            "push --force-with-lease": ok(),
            "ls-remote --heads origin feat/x": ok(""),
            "remote prune origin": ok(),
        }
    )
    run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")), _remote_survey())

    push = next(call for call in port.transcript if call[:2] == ("git", "push"))
    assert f"--force-with-lease=feat/x:{REMOTE_HEAD}" in push
    # The ref is repo-derived, so it is terminated like every other one.
    assert push[-2:] == ("--", "feat/x")


def test_a_remote_branch_the_survey_never_saw_is_not_deleted_blind() -> None:
    """With no surveyed commit there is no value to lease against, and an
    unleased delete would take whatever the server currently holds."""
    port = ScriptedCommands()
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")))
    assert not report.ok
    assert port.transcript == []
    assert "refusing to delete it blind" in report.anomalies[0].message


def test_a_rejected_lease_is_reported_as_the_server_having_moved() -> None:
    port = ScriptedCommands(
        git={"push --force-with-lease": fail("! [rejected] (delete) -> feat/x (stale info)")}
    )
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")), _remote_survey())
    assert not report.ok
    assert "fetch and re-run" in report.anomalies[0].message
    assert not report.deletions[0].deleted


def test_remote_ref_surviving_a_successful_push_delete_is_an_anomaly() -> None:
    port = ScriptedCommands(
        git={
            "push --force-with-lease": ok(),
            "ls-remote --heads origin feat/x": ok("abc123\trefs/heads/feat/x"),
        }
    )
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")), _remote_survey())
    assert not report.ok
    assert "still exists" in report.anomalies[0].message


def test_an_unverifiable_remote_deletion_is_not_reported_as_success() -> None:
    """ls-remote failed, so the delete's success is unconfirmed. Unknown is
    not the same as done."""
    port = ScriptedCommands(
        git={
            "push --force-with-lease": ok(),
            "ls-remote --heads origin feat/x": fail("could not read from remote"),
        }
    )
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")), _remote_survey())
    assert not report.ok
    assert not report.deletions[0].deleted


def test_unparseable_remote_name_is_reported_not_guessed() -> None:
    port = ScriptedCommands()
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "bare")))
    assert not report.ok
    assert port.transcript == []


# -- salvage -----------------------------------------------------------------


WIP_BUNDLE = f"/salvage/{slug('wip')}.bundle"


def _branch_salvage_port(**overrides: object) -> ScriptedCommands:
    table = {
        f"bundle create {WIP_BUNDLE} wip": ok(),
        f"bundle verify {WIP_BUNDLE}": ok(),
        "branch -D -- wip": ok(),
        "for-each-ref --format=%(refname) refs/heads/wip": ok(""),
    }
    table.update(overrides)  # type: ignore[arg-type]
    return ScriptedCommands(git=table)  # type: ignore[arg-type]


def test_salvage_precedes_deletion() -> None:
    port = _branch_salvage_port()
    report = run(port, plan(target(TargetKind.BRANCH, "wip", risk=Risk.RECOVERABLE)))
    assert report.ok
    verbs = [t[1] for t in port.transcript]
    assert verbs.index("bundle") < verbs.index("branch")
    assert report.salvages[0].verified


def test_a_bundle_that_fails_to_write_aborts_the_deletion() -> None:
    port = _branch_salvage_port(**{f"bundle create {WIP_BUNDLE} wip": fail("disk full")})
    report = run(port, plan(target(TargetKind.BRANCH, "wip", risk=Risk.RECOVERABLE)))
    assert not report.ok
    assert "branch" not in [t[1] for t in port.transcript]
    assert "salvage failed" in report.deletions[0].detail


def test_a_bundle_that_does_not_verify_aborts_the_deletion() -> None:
    """An unverified bundle is not a safety net, so it does not buy a deletion."""
    port = _branch_salvage_port(**{f"bundle verify {WIP_BUNDLE}": fail("corrupt")})
    report = run(port, plan(target(TargetKind.BRANCH, "wip", risk=Risk.RECOVERABLE)))
    assert not report.ok
    assert "did not verify" in report.anomalies[0].message
    assert "branch" not in [t[1] for t in port.transcript]


def test_missing_salvage_directory_aborts_rather_than_deleting_unprotected() -> None:
    port = ScriptedCommands()
    report = run(
        port,
        plan(target(TargetKind.BRANCH, "wip", risk=Risk.RECOVERABLE), salvage_dir=None),
    )
    assert not report.ok
    assert port.transcript == []


# -- worktree salvage --------------------------------------------------------


def _worktree_salvage_port(
    *, create: CommandResult | None = None, listing: CommandResult | None = None
) -> ScriptedCommands:
    return ScriptedCommands(
        git={
            "worktree remove --force -- /repo/wt": ok(),
            "worktree prune": ok(),
            "worktree list --porcelain": ok("worktree /repo\n"),
        },
        archive_create=create if create is not None else ok(),
        archive_list=listing if listing is not None else ok("./\n./scratch.txt\n./.env\n"),
    )


def test_worktree_salvage_archives_the_whole_tree() -> None:
    port = _worktree_salvage_port()
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt", risk=Risk.DATA_LOSS)))
    assert report.ok
    source, dest = port.archives[0]
    assert source == "/repo/wt"
    assert dest.startswith("/salvage/") and dest.endswith(".tar.gz")
    assert report.salvages[0].verified
    assert "2 entries" in report.salvages[0].detail


def test_the_archive_is_written_before_the_worktree_is_removed() -> None:
    port = _worktree_salvage_port()
    run(port, plan(target(TargetKind.WORKTREE, "/repo/wt", risk=Risk.DATA_LOSS)))
    verbs = [t[0] for t in port.transcript]
    assert verbs.index("tar") < verbs.index("git")


def test_a_failing_archive_aborts_before_any_deletion() -> None:
    port = _worktree_salvage_port(create=fail("tar: no space left on device"))
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt", risk=Risk.DATA_LOSS)))
    assert not report.ok
    assert report.anomalies[0].stage == "salvage"
    assert "git" not in [t[0] for t in port.transcript]
    assert "salvage failed" in report.deletions[0].detail


def test_an_archive_that_cannot_be_read_back_aborts_the_deletion() -> None:
    """An archive nobody could open is not a safety net, so it does not buy a
    deletion."""
    port = _worktree_salvage_port(listing=fail("tar: unexpected EOF"))
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt", risk=Risk.DATA_LOSS)))
    assert not report.ok
    assert "could not be read back" in report.anomalies[0].message
    assert "git" not in [t[0] for t in port.transcript]


def test_an_empty_archive_is_not_treated_as_a_successful_capture() -> None:
    """tar writes an archive of nothing and reads it back without complaint,
    so a clean exit code is not proof that anything was captured."""
    port = _worktree_salvage_port(listing=ok("./\n"))
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt", risk=Risk.DATA_LOSS)))
    assert not report.ok
    assert "nothing was captured" in report.anomalies[0].message
    assert "git" not in [t[0] for t in port.transcript]


def test_the_archive_captures_ignored_files() -> None:
    """A worktree whose only content is a .env used to read clean, be swept at
    Risk.NONE, and not even be captured by salvage if it had been."""
    port = _worktree_salvage_port(listing=ok("./\n./.env\n"))
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt", risk=Risk.DATA_LOSS)))
    assert report.ok
    assert "1 entries" in report.salvages[0].detail


# -- cascade -----------------------------------------------------------------


def test_a_branch_whose_worktree_survived_is_skipped_not_attempted() -> None:
    """Attempting it buys a git error that reads as a new problem instead of
    the consequence of the one already reported."""
    port = ScriptedCommands(git={"worktree remove -- /repo/wt": fail("contains modified files")})
    survey = make_survey(branches=(make_branch("held", checked_out_at="/repo/wt"),))
    report = run(
        port,
        plan(target(TargetKind.WORKTREE, "/repo/wt"), target(TargetKind.BRANCH, "held")),
        survey,
    )
    assert "branch" not in [t[1] for t in port.transcript]
    branch_result = report.deletions[1]
    assert not branch_result.deleted
    assert "was not removed" in branch_result.detail


def test_an_unrelated_branch_still_deletes_when_a_worktree_fails() -> None:
    port = ScriptedCommands(
        git={
            "worktree remove -- /repo/wt": fail("contains modified files"),
            "branch -D -- other": ok(),
            "for-each-ref --format=%(refname) refs/heads/other": ok(""),
        }
    )
    survey = make_survey(branches=(make_branch("other", checked_out_at=None),))
    report = run(
        port,
        plan(target(TargetKind.WORKTREE, "/repo/wt"), target(TargetKind.BRANCH, "other")),
        survey,
    )
    assert report.deletions[1].verified


# -- helpers -----------------------------------------------------------------


def test_slug_is_filesystem_safe_and_readable() -> None:
    assert slug("feat/x y").startswith("feat-x-y-")
    assert slug("///").startswith("target-")


def test_slug_does_not_collide_where_the_readable_part_does() -> None:
    """`origin/feat/a` and `origin-feat-a` flatten to the same readable string.
    Sharing a filename means the second verified salvage overwrites the first
    and both deletions proceed -- one having destroyed the only copy."""
    assert slug("origin/feat/a") != slug("origin-feat-a")
    assert slug("feat+x") != slug("feat-x")
    assert slug("feat/x") == slug("feat/x")


def test_salvage_dir_lands_in_the_common_git_dir() -> None:
    """Not inside a worktree being removed, and never committed."""
    moment = datetime(2026, 7, 25, 17, 44, 0, tzinfo=UTC)
    resolved = default_salvage_dir(make_survey(), moment)
    assert resolved == "/repo/.git/gitclean-salvage/20260725T174400Z"
