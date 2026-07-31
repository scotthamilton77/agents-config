"""Tests for salvage, deletion, and verification.

The interesting cases are the ones where git reports success and the thing is
still there. A tool that trusts exit codes cannot tell those from real
successes, which is why every deletion re-asks."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

from conftest import make_branch, make_survey, make_worktree

from gitclean import execute
from gitclean.execute import SALVAGE_PREFIX, Executor, default_salvage_dir, git_argv, slug
from gitclean.model import MergeEvidence, Plan, Target, TargetKind
from gitclean.ports import ScriptedCommands, fail, ok


def target(kind: TargetKind, name: str) -> Target:
    prefix = {
        TargetKind.WORKTREE: "worktree",
        TargetKind.BRANCH: "branch",
        TargetKind.REMOTE_BRANCH: "remote",
    }[kind]
    return Target(
        id=f"{prefix}:{name}",
        kind=kind,
        name=name,
        merge_evidence=MergeEvidence.ANCESTOR,
        merge_proven=True,
        sweepable=True,
        withheld=None,
        reasons=(),
        last_activity=None,
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


def test_dry_run_announces_the_salvage_step_for_a_server_ref() -> None:
    port = ScriptedCommands()
    report = run(
        port,
        plan(target(TargetKind.REMOTE_BRANCH, "origin/wip"), dry_run=True),
    )
    assert "after salvage" in report.deletions[0].detail


def test_dry_run_announces_no_salvage_for_a_local_branch() -> None:
    """`branch -D` leaves the commits in the reflog, so there is nothing to
    bundle and saying otherwise would advertise a safety net nobody built."""
    port = ScriptedCommands()
    report = run(port, plan(target(TargetKind.BRANCH, "wip"), dry_run=True))
    assert "salvage" not in report.deletions[0].detail


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
            "worktree list --porcelain": ok("worktree /repo\n\nworktree /repo/wt\n"),
        }
    )
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt")))
    assert not report.ok
    assert report.anomalies[0].stage == "verify"


def test_a_worktree_is_never_removed_with_force() -> None:
    """Not on a sweep, not when the caller names it. --force is what turns
    git's own checks off -- the dirt check, the lock, the main working tree --
    and overriding them means re-implementing in Python what git has just read
    off the disk. Naming a target authorises the deletion; it does not make
    this process a better judge of that directory than git is."""
    port = ScriptedCommands(
        git={
            "worktree remove -- /repo/wt": ok(),
            "worktree list --porcelain": ok("worktree /repo\n"),
        }
    )
    run(port, plan(target(TargetKind.WORKTREE, "/repo/wt")))

    removal = next(call for call in port.transcript if call[:3] == ("git", "worktree", "remove"))
    assert "--force" not in removal


def test_a_worktree_that_went_dirty_since_the_survey_is_not_destroyed() -> None:
    """The window between survey and execution is real -- an agent writes a
    file, and the tree that was judged clean no longer is. git's refusal is the
    only thing standing between those changes and deletion, and it knows
    something this process does not: what that directory holds right now.

    So the refusal surfaces as an anomaly carrying git's own words, and the
    worktree is still there. A person who reads that and still wants it gone
    runs one `git worktree remove --force` themselves."""
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
    assert "git refused to remove worktree" in report.anomalies[0].message
    assert any(
        "contains modified or untracked files" in line for line in report.anomalies[0].transcript
    )


def test_removing_a_worktree_prunes_nothing() -> None:
    """`worktree prune` destroys the administrative records of worktrees this
    run never planned to touch -- outside the plan, unsalvaged, and absent from
    `skipped`. The executor acts on planned targets only."""
    port = ScriptedCommands(
        git={
            "worktree remove -- /repo/wt": ok(),
            "worktree list --porcelain": ok("worktree /repo\n"),
        }
    )
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt")))
    assert report.ok
    assert not any("prune" in call for call in port.transcript)


def test_an_unlistable_worktree_check_is_unverified_not_removed() -> None:
    """Absence from output that was never produced is not evidence. Empty
    stdout on a failed command previously read as 'gone'."""
    port = ScriptedCommands(
        git={
            "worktree remove -- /repo/wt": ok(),
            "worktree list --porcelain": fail("fatal: not a git repository"),
        }
    )
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt")))
    assert not report.ok
    assert not report.deletions[0].deleted
    assert report.deletions[0].detail == "deletion unverified"


def test_a_reachability_probe_that_will_not_answer_declines_the_removal() -> None:
    """The one place a named target is refused on reachability grounds, and the
    refusal has to hold when the probe itself fails.

    git's interlocks cover uncommitted content and say nothing about a commit
    made in this tree on no branch: the tree is clean, git removes it happily,
    and the per-worktree reflog that held the commit dies with the record. So
    an unanswered probe is read as a stranding. Being wrong that way costs a
    worktree someone removes by hand; being wrong the other way costs the
    commit.

    The removal is scripted to succeed, so nothing but the guard stops it."""
    head = "a" * 40
    port = ScriptedCommands(
        git={
            "rev-parse HEAD": ok(head),
            f"for-each-ref --count=1 --contains={head}": fail("fatal: bad object"),
            "worktree remove -- /repo/wt": ok(),
            "worktree list --porcelain": ok("worktree /repo\n"),
        }
    )
    report = run(
        port,
        plan(target(TargetKind.WORKTREE, "/repo/wt")),
        make_survey(worktrees=(make_worktree("/repo/wt", head=head, branch=None),)),
    )

    assert not report.ok
    assert not report.deletions[0].deleted
    assert head[:8] in report.deletions[0].detail
    assert report.anomalies[0].stage == "delete"
    assert "would strand" in report.anomalies[0].message
    # The refusal is a claim about what git said, so it travels with what git
    # said. A reader cannot re-derive the probe from the prose.
    assert "for-each-ref" in "\n".join(report.anomalies[0].transcript)
    assert not any(call[:3] == ("git", "worktree", "remove") for call in port.transcript)


def test_a_commit_made_since_the_survey_is_not_stranded_by_the_removal() -> None:
    """The survey is a snapshot; the deletion happens after it. An agent
    committing in that tree in between leaves the recorded commit sitting on a
    branch -- where it answers "contained" -- and the new one held only by the
    record this call is about to delete.

    So asking about the surveyed commit is not a weaker check, it is the wrong
    one: it clears in exactly the case it exists to refuse."""
    surveyed, made_since = "a" * 40, "b" * 40
    port = ScriptedCommands(
        git={
            "rev-parse HEAD": ok(made_since),
            f"for-each-ref --count=1 --contains={surveyed}": ok("refs/heads/keeps-it"),
            f"for-each-ref --count=1 --contains={made_since}": ok(""),
            "worktree remove -- /repo/wt": ok(),
            "worktree list --porcelain": ok("worktree /repo\n"),
        }
    )
    report = run(
        port,
        plan(target(TargetKind.WORKTREE, "/repo/wt")),
        make_survey(worktrees=(make_worktree("/repo/wt", head=surveyed, branch=None),)),
    )

    assert not report.ok
    assert made_since[:8] in report.deletions[0].detail
    assert not any(call[:3] == ("git", "worktree", "remove") for call in port.transcript)


# -- remote branch -----------------------------------------------------------

REMOTE_HEAD = "0" * 40
"""What `make_branch` publishes as a tip, and so what the lease is taken at."""

FEAT_BUNDLE = f"/salvage/{slug('origin/feat/x')}.bundle"


def _remote_survey(name: str = "origin/feat/x"):  # type: ignore[no-untyped-def]
    """A survey that has actually seen the remote branch.

    The executor leases against the commit the survey judged, so a remote
    deletion test that omits the branch is testing the refusal path, not the
    deletion path."""
    return make_survey(
        branches=(make_branch(name, is_remote=True, remote="origin", upstream=None),)
    )


def _remote_port(**overrides: object) -> ScriptedCommands:
    """Every server deletion is bundled first, so every one of these scripts
    the bundle. A test that omitted it would be exercising the salvage-failure
    path while claiming to be about the push."""
    table = {
        "branch --no-track": ok(),
        f"branch -D -- {SALVAGE_PREFIX}": ok(),
        f"bundle create {FEAT_BUNDLE}": ok(),
        f"bundle verify {FEAT_BUNDLE}": ok(),
        "push --force-with-lease": ok(),
        "ls-remote": ok(""),
    }
    table.update(overrides)  # type: ignore[arg-type]
    return ScriptedCommands(git=table)  # type: ignore[arg-type]


def test_remote_deletion_is_confirmed_against_the_server() -> None:
    port = _remote_port()
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")), _remote_survey())
    assert report.ok
    assert report.deletions[0].verified


def test_the_remote_delete_is_leased_to_the_commit_that_was_judged() -> None:
    """Every verdict about a remote branch came from a local cache of it. If
    the server has moved since the last fetch, those commits were never judged
    -- the lease is what makes the server refuse rather than discard them."""
    port = _remote_port()
    run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")), _remote_survey())

    push = next(call for call in port.transcript if call[:2] == ("git", "push"))
    assert f"--force-with-lease=feat/x:{REMOTE_HEAD}" in push
    # The ref is repo-derived, so it is terminated like every other one.
    assert push[-2:] == ("--", "feat/x")


def test_deleting_a_remote_branch_prunes_nothing() -> None:
    """`remote prune` drops every tracking ref the server no longer has, not
    just the one that was planned -- refs this run never judged."""
    port = _remote_port()
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")), _remote_survey())
    assert report.ok
    assert not any("prune" in call for call in port.transcript)


def test_a_remote_branch_the_survey_never_saw_is_not_deleted_blind() -> None:
    """With no surveyed commit there is no value to lease against, and an
    unleased delete would take whatever the server currently holds."""
    port = _remote_port()
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")))
    assert not report.ok
    assert "push" not in [t[1] for t in port.transcript]
    assert "refusing to delete it blind" in report.anomalies[0].message


def test_a_remote_target_naming_no_remote_is_never_pushed_to() -> None:
    """`refs/remotes/bare` is a legal ref layout with no remote in it, so a
    target can reach the delete carrying nothing to push to. There is no
    guessing a remote here: the run says what it cannot parse and stops."""
    port = _remote_port(
        **{
            "branch --no-track": ok(),
            f"branch -D -- {SALVAGE_PREFIX}": ok(),
            f"bundle create /salvage/{slug('bare')}.bundle": ok(),
            f"bundle verify /salvage/{slug('bare')}.bundle": ok(),
        }
    )
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "bare")), _remote_survey("bare"))

    assert not report.ok
    assert "push" not in [call[1] for call in port.transcript]
    assert "cannot split bare" in report.anomalies[0].message


def test_a_rejected_lease_is_reported_as_the_server_having_moved() -> None:
    port = _remote_port(
        **{"push --force-with-lease": fail("! [rejected] (delete) -> feat/x (stale info)")}
    )
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")), _remote_survey())
    assert not report.ok
    assert "fetch and re-run" in report.anomalies[0].message
    assert not report.deletions[0].deleted


def test_the_survival_probe_asks_the_server_for_the_exact_ref() -> None:
    """A short name is a pattern git matches on path-component boundaries, and
    a full ref path is not -- it is also the spelling no git command can read
    as an option."""
    port = _remote_port()
    run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")), _remote_survey())

    probe = next(call for call in port.transcript if call[1] == "ls-remote")
    assert probe[-1] == "refs/heads/feat/x"


def test_remote_ref_surviving_a_successful_push_delete_is_an_anomaly() -> None:
    port = _remote_port(**{"ls-remote": ok("abc123\trefs/heads/feat/x")})
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")), _remote_survey())
    assert not report.ok
    assert "still exists" in report.anomalies[0].message


def test_a_sibling_ref_on_the_server_is_not_read_as_the_target_surviving() -> None:
    """`ls-remote <remote> feat/x` matches on path-component boundaries, so an
    unrelated `a/feat/x` answers a question about `feat/x`. Reading that as the
    target having survived turns a deletion git performed into a reported
    failure, and the exit code says the run went wrong."""
    port = _remote_port(**{"ls-remote": ok("dbfd823\trefs/heads/a/feat/x")})
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")), _remote_survey())
    assert report.ok
    assert report.deletions[0].verified


def test_an_unverifiable_remote_deletion_is_not_reported_as_success() -> None:
    """ls-remote failed, so the delete's success is unconfirmed. Unknown is
    not the same as done."""
    port = _remote_port(**{"ls-remote": fail("could not read from remote")})
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")), _remote_survey())
    assert not report.ok
    assert not report.deletions[0].deleted


def test_unparseable_remote_name_is_reported_not_guessed() -> None:
    """`bare` names no remote, so there is nothing to push to. git says so when
    the salvage is attempted, and no push is ever issued."""
    port = ScriptedCommands(git={"branch --no-track": fail("fatal: not a valid object name")})
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "bare")))
    assert not report.ok
    assert "push" not in [t[1] for t in port.transcript]


# -- salvage, and the one place it is still earned -----------------------------

REMOTE = "origin/wip"
WIP_BUNDLE = f"/salvage/{slug(REMOTE)}.bundle"


def _remote_salvage_port(**overrides: object) -> ScriptedCommands:
    table = {
        "branch --no-track": ok(),
        f"branch -D -- {SALVAGE_PREFIX}": ok(),
        f"bundle create {WIP_BUNDLE}": ok(),
        f"bundle verify {WIP_BUNDLE}": ok(),
        "push --force-with-lease": ok(),
        "ls-remote": ok(""),
    }
    table.update(overrides)  # type: ignore[arg-type]
    return ScriptedCommands(git=table)  # type: ignore[arg-type]


def test_a_server_ref_is_bundled_before_it_is_deleted() -> None:
    """`push --delete` is irreversible for everyone fetching and the server
    keeps no reflog, so this is the only deletion left with no undo behind it
    -- and the only one still worth a bundle."""
    port = _remote_salvage_port()
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, REMOTE)), _remote_survey(REMOTE))
    assert report.ok
    verbs = [t[1] for t in port.transcript]
    assert verbs.index("bundle") < verbs.index("push")
    assert report.salvages[0].verified


def test_a_local_branch_is_not_bundled() -> None:
    """`branch -D` leaves the commits in the reflog for git's configured
    expiry. Bundling them as well bought disk usage and a restore route nobody
    took, in front of a deletion that already had one."""
    port = ScriptedCommands(
        git={
            "branch -D -- wip": ok(),
            "for-each-ref --format=%(refname) refs/heads/wip": ok(""),
        }
    )
    report = run(port, plan(target(TargetKind.BRANCH, "wip")))
    assert report.ok
    assert report.salvages == ()
    assert "bundle" not in [t[1] for t in port.transcript]


def test_the_bundle_is_taken_from_a_branch_this_run_makes_and_removes() -> None:
    """A bundle of `refs/remotes/...` holds no head: it verifies cleanly and
    clones back an empty repository, so the deletion it authorised is backed by
    nothing. The copy under refs/heads is what makes the archive restorable,
    and it goes away again in the same run."""
    port = _remote_salvage_port()
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, REMOTE)), _remote_survey(REMOTE))
    assert report.ok

    scratch = f"{SALVAGE_PREFIX}/{slug(REMOTE)}"
    verbs = [call for call in port.transcript if call[1] in {"branch", "bundle", "push"}]
    assert verbs == [
        ("git", "branch", "--no-track", scratch, f"refs/remotes/{REMOTE}"),
        ("git", "bundle", "create", WIP_BUNDLE, f"refs/heads/{scratch}"),
        ("git", "bundle", "verify", WIP_BUNDLE),
        ("git", "branch", "-D", "--", scratch),
        ("git", "push", f"--force-with-lease=wip:{REMOTE_HEAD}", "origin", "--delete", "--", "wip"),
    ]
    assert report.salvages[0].detail == f"restore with: git clone {WIP_BUNDLE} -b {scratch}"


def test_a_scratch_branch_that_will_not_go_away_is_reported() -> None:
    """The bundle is written and the deletion stands on it, so this does not
    abort anything -- but a branch this run created and could not remove is a
    surprise, and the next report would show it as work nobody recognises."""
    port = _remote_salvage_port(
        **{f"branch -D -- {SALVAGE_PREFIX}": fail("error: cannot lock ref")}
    )
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, REMOTE)), _remote_survey(REMOTE))

    assert report.deletions[0].verified
    assert report.salvages[0].verified
    assert "could not be removed" in report.anomalies[0].message


def test_a_bundle_that_fails_to_write_aborts_the_deletion() -> None:
    port = _remote_salvage_port(**{f"bundle create {WIP_BUNDLE}": fail("disk full")})
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, REMOTE)), _remote_survey(REMOTE))
    assert not report.ok
    assert "push" not in [t[1] for t in port.transcript]
    assert "salvage failed" in report.deletions[0].detail


def test_a_bundle_that_does_not_verify_aborts_the_deletion() -> None:
    """An unverified bundle is not a safety net, so it does not buy a deletion."""
    port = _remote_salvage_port(**{f"bundle verify {WIP_BUNDLE}": fail("corrupt")})
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, REMOTE)), _remote_survey(REMOTE))
    assert not report.ok
    assert "did not verify" in report.anomalies[0].message
    assert "push" not in [t[1] for t in port.transcript]


def test_missing_salvage_directory_aborts_rather_than_deleting_unprotected() -> None:
    port = ScriptedCommands()
    report = run(
        port,
        plan(target(TargetKind.REMOTE_BRANCH, REMOTE), salvage_dir=None),
        _remote_survey(REMOTE),
    )
    assert not report.ok
    assert port.transcript == []


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


def test_every_git_call_is_assembled_by_the_one_argv_constructor() -> None:
    """The terminator used to be a habit applied call site by call site, and
    the two sites that forgot it were the two nobody could type by hand: a
    bundle of a ref named `-m`, and a survival probe for one. Neither shows up
    in review as a missing argument -- it looks exactly like the sites that
    were right.

    So the property is asserted over the module rather than over one call: a
    site that builds its own argument list is the failure, whatever that list
    happens to contain today."""
    tree = ast.parse(Path(execute.__file__).read_text(encoding="utf-8"))
    unrouted = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and ast.unparse(node.func).endswith("_port.git")
        and not (
            node.args
            and isinstance(node.args[0], ast.Call)
            and ast.unparse(node.args[0].func) == "git_argv"
        )
    ]
    assert unrouted == []


def test_the_constructor_terminates_a_name_git_would_read_as_an_option() -> None:
    assert git_argv("branch", "-D", name="-m") == ["branch", "-D", "--", "-m"]


def test_the_constructor_leaves_a_full_ref_path_unterminated() -> None:
    """`bundle create` hands its arguments to rev-list, where `--` introduces a
    pathspec: terminating there produces `Refusing to create empty bundle`
    rather than protection. A `refs/...` path needs no terminator -- no git
    command reads one as an option."""
    assert git_argv("bundle", "create", "/salvage/x.bundle", name="refs/heads/-m") == [
        "bundle",
        "create",
        "/salvage/x.bundle",
        "refs/heads/-m",
    ]


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
