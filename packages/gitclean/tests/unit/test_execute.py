"""Tests for salvage, deletion, and verification.

The interesting cases are the ones where git reports success and the thing is
still there. A tool that trusts exit codes cannot tell those from real
successes, which is why every deletion re-asks."""

from __future__ import annotations

from datetime import UTC, datetime

from conftest import make_branch, make_survey

from gitclean.execute import Executor, default_salvage_dir, slug
from gitclean.model import Disposition, Plan, Risk, Target, TargetKind
from gitclean.ports import ScriptedCommands, fail, ok


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
            "branch -D feat/x": ok(),
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
            "branch -D feat/x": ok(),
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
            "branch -D feat/x": ok(),
            "for-each-ref --format=%(refname) refs/heads/feat/x": fail("fatal: bad repository"),
        }
    )
    report = run(port, plan(target(TargetKind.BRANCH, "feat/x")))
    assert not report.ok
    assert not report.deletions[0].deleted
    assert report.deletions[0].detail == "deletion unverified"
    assert "bad repository" in "\n".join(report.anomalies[0].transcript)


def test_a_failed_delete_carries_the_command_transcript() -> None:
    port = ScriptedCommands(git={"branch -D feat/x": fail("error: branch is checked out", code=1)})
    report = run(port, plan(target(TargetKind.BRANCH, "feat/x")))
    anomaly = report.anomalies[0]
    assert anomaly.stage == "delete"
    joined = "\n".join(anomaly.transcript)
    assert "git branch -D feat/x" in joined
    assert "exit: 1" in joined
    assert "branch is checked out" in joined


# -- worktree ----------------------------------------------------------------


def test_worktree_removal_is_verified_against_the_listing() -> None:
    port = ScriptedCommands(
        git={
            "worktree remove --force /repo/wt": ok(),
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
            "worktree remove --force /repo/wt": ok(),
            "worktree prune": ok(),
            "worktree list --porcelain": ok("worktree /repo\n\nworktree /repo/wt\n"),
        }
    )
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt")))
    assert not report.ok
    assert report.anomalies[0].stage == "verify"


def test_an_unlistable_worktree_check_is_unverified_not_removed() -> None:
    """Absence from output that was never produced is not evidence. Empty
    stdout on a failed command previously read as 'gone'."""
    port = ScriptedCommands(
        git={
            "worktree remove --force /repo/wt": ok(),
            "worktree prune": ok(),
            "worktree list --porcelain": fail("fatal: not a git repository"),
        }
    )
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt")))
    assert not report.ok
    assert not report.deletions[0].deleted
    assert report.deletions[0].detail == "deletion unverified"


# -- remote branch -----------------------------------------------------------


def test_remote_deletion_is_confirmed_against_the_server() -> None:
    port = ScriptedCommands(
        git={
            "push origin --delete feat/x": ok(),
            "ls-remote --heads origin feat/x": ok(""),
            "remote prune origin": ok(),
        }
    )
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")))
    assert report.ok
    assert report.deletions[0].verified


def test_remote_ref_surviving_a_successful_push_delete_is_an_anomaly() -> None:
    port = ScriptedCommands(
        git={
            "push origin --delete feat/x": ok(),
            "ls-remote --heads origin feat/x": ok("abc123\trefs/heads/feat/x"),
        }
    )
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")))
    assert not report.ok
    assert "still exists" in report.anomalies[0].message


def test_an_unverifiable_remote_deletion_is_not_reported_as_success() -> None:
    """ls-remote failed, so the delete's success is unconfirmed. Unknown is
    not the same as done."""
    port = ScriptedCommands(
        git={
            "push origin --delete feat/x": ok(),
            "ls-remote --heads origin feat/x": fail("could not read from remote"),
        }
    )
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")))
    assert not report.ok
    assert not report.deletions[0].deleted


def test_unparseable_remote_name_is_reported_not_guessed() -> None:
    port = ScriptedCommands()
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "bare")))
    assert not report.ok
    assert port.transcript == []


# -- salvage -----------------------------------------------------------------


def _branch_salvage_port(**overrides: object) -> ScriptedCommands:
    table = {
        "bundle create /salvage/wip.bundle wip": ok(),
        "bundle verify /salvage/wip.bundle": ok(),
        "branch -D wip": ok(),
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
    port = _branch_salvage_port(**{"bundle create /salvage/wip.bundle wip": fail("disk full")})
    report = run(port, plan(target(TargetKind.BRANCH, "wip", risk=Risk.RECOVERABLE)))
    assert not report.ok
    assert "branch" not in [t[1] for t in port.transcript]
    assert "salvage failed" in report.deletions[0].detail


def test_a_bundle_that_does_not_verify_aborts_the_deletion() -> None:
    """An unverified bundle is not a safety net, so it does not buy a deletion."""
    port = _branch_salvage_port(**{"bundle verify /salvage/wip.bundle": fail("corrupt")})
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


def _worktree_salvage_port(**overrides: object) -> ScriptedCommands:
    ref = "refs/gitclean/salvage/repo-wt"
    table = {
        "stash create": ok("deadbeef"),
        f"update-ref {ref} deadbeef": ok(),
        f"bundle create /salvage/repo-wt/tracked-changes.bundle {ref}": ok(),
        "bundle verify /salvage/repo-wt/tracked-changes.bundle": ok(),
        f"update-ref -d {ref}": ok(),
        "ls-files --others --exclude-standard": ok("scratch.txt\n"),
        "worktree remove --force /repo/wt": ok(),
        "worktree prune": ok(),
        "worktree list --porcelain": ok("worktree /repo\n"),
    }
    table.update(overrides)  # type: ignore[arg-type]
    return ScriptedCommands(git=table)  # type: ignore[arg-type]


def test_worktree_salvage_bundles_tracked_changes_and_copies_untracked() -> None:
    port = _worktree_salvage_port()
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt", risk=Risk.DATA_LOSS)))
    assert report.ok
    assert port.copies == [("/repo/wt/scratch.txt", "/salvage/repo-wt/untracked/scratch.txt")]
    assert "untracked scratch.txt" in report.salvages[0].detail


def test_the_temporary_salvage_ref_is_always_cleaned_up() -> None:
    """It exists only to give `git bundle` a ref to package; leaving it behind
    would put a phantom ref in the repo gitclean itself would later survey."""
    port = _worktree_salvage_port()
    run(port, plan(target(TargetKind.WORKTREE, "/repo/wt", risk=Risk.DATA_LOSS)))
    assert ("git", "update-ref", "-d", "refs/gitclean/salvage/repo-wt") in port.transcript


def test_the_temporary_ref_is_cleaned_up_even_when_the_bundle_fails() -> None:
    port = _worktree_salvage_port(
        **{
            "bundle create /salvage/repo-wt/tracked-changes.bundle "
            "refs/gitclean/salvage/repo-wt": fail("empty bundle")
        }
    )
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt", risk=Risk.DATA_LOSS)))
    assert not report.ok
    assert ("git", "update-ref", "-d", "refs/gitclean/salvage/repo-wt") in port.transcript


def test_a_stash_that_captures_nothing_still_salvages_untracked_files() -> None:
    port = _worktree_salvage_port(**{"stash create": ok("")})
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt", risk=Risk.DATA_LOSS)))
    assert report.ok
    assert port.copies


def test_a_dirty_worktree_that_yields_nothing_is_not_deleted() -> None:
    """Classified dirty but nothing captured means the survey and the tree
    disagree. Deleting on a contradiction is exactly the wrong move."""
    port = _worktree_salvage_port(
        **{"stash create": ok(""), "ls-files --others --exclude-standard": ok("")}
    )
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt", risk=Risk.DATA_LOSS)))
    assert not report.ok
    assert "worktree" not in [t[1] for t in port.transcript if t[1] == "worktree"]


def test_a_failing_stash_aborts_before_any_deletion() -> None:
    port = _worktree_salvage_port(**{"stash create": fail("not a git repository")})
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt", risk=Risk.DATA_LOSS)))
    assert not report.ok
    assert report.anomalies[0].stage == "salvage"


def test_a_failing_update_ref_aborts_before_any_deletion() -> None:
    port = _worktree_salvage_port(
        **{"update-ref refs/gitclean/salvage/repo-wt deadbeef": fail("permission denied")}
    )
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt", risk=Risk.DATA_LOSS)))
    assert not report.ok
    assert "salvage ref" in report.anomalies[0].message


# -- cascade -----------------------------------------------------------------


def test_a_branch_whose_worktree_survived_is_skipped_not_attempted() -> None:
    """Attempting it buys a git error that reads as a new problem instead of
    the consequence of the one already reported."""
    port = ScriptedCommands(
        git={"worktree remove --force /repo/wt": fail("contains modified files")}
    )
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
            "worktree remove --force /repo/wt": fail("contains modified files"),
            "branch -D other": ok(),
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


def test_slug_is_filesystem_safe() -> None:
    assert slug("feat/x y") == "feat-x-y"
    assert slug("///") == "target"


def test_salvage_dir_lands_in_the_common_git_dir() -> None:
    """Not inside a worktree being removed, and never committed."""
    moment = datetime(2026, 7, 25, 17, 44, 0, tzinfo=UTC)
    resolved = default_salvage_dir(make_survey(), moment)
    assert resolved == "/repo/.git/gitclean-salvage/20260725T174400Z"
