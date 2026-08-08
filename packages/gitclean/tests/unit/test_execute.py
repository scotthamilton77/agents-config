"""Tests for salvage, deletion, and what a deletion reports.

The interesting cases are the ones where git and this tool could disagree
about what happened. For anything git deletes here, git's own account is the
report; the exception is a ref on a server, which a zero exit does not settle,
so those tests are about the second read of the remote."""

from __future__ import annotations

from datetime import UTC, datetime

from conftest import make_branch, make_survey, make_worktree
from test_survey import porcelain

from gitclean.execute import SALVAGE_PREFIX, Executor, default_salvage_dir, slug
from gitclean.model import MergeEvidence, Plan, Target, TargetKind
from gitclean.ports import CommandResult, ScriptedCommands, fail, ok


def target(kind: TargetKind, name: str, *, remote: str | None = "origin") -> Target:
    prefix = {
        TargetKind.WORKTREE: "worktree",
        TargetKind.BRANCH: "branch",
        TargetKind.REMOTE_BRANCH: "remote",
    }[kind]
    # Which remote a server ref lives on is something only the survey can say,
    # having had the configured remote list in hand. The fixture states it here
    # instead, and a target the survey could not split is built by giving a
    # name this remote does not account for.
    on_remote = kind is TargetKind.REMOTE_BRANCH and remote and name.startswith(f"{remote}/")
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
        remote=remote if on_remote else None,
        ref_name=name[len(remote) + 1 :] if on_remote and remote else None,
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
    port = ScriptedCommands(git={"ls-remote": ok(f"{REMOTE_HEAD}\trefs/heads/wip")})
    report = run(
        port,
        plan(target(TargetKind.REMOTE_BRANCH, "origin/wip"), dry_run=True),
    )
    assert "after salvage" in report.deletions[0].detail


def test_a_dry_run_does_not_promise_to_delete_a_ref_the_server_lost() -> None:
    """The preview exists to be believed before the real run, so it asks the
    same question the real run does. Announcing `would delete` for a ref that
    is not there sends a caller to a cleanup with nothing in it."""
    port = ScriptedCommands(git={"ls-remote": ok("")})
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/wip"), dry_run=True))

    assert report.ok
    assert report.deletions[0].already_absent
    assert "would delete" not in report.deletions[0].detail


def test_dry_run_announces_no_salvage_for_a_local_branch() -> None:
    """`branch -D` leaves the commits in the reflog, so there is nothing to
    bundle and saying otherwise would advertise a safety net nobody built."""
    port = ScriptedCommands()
    report = run(port, plan(target(TargetKind.BRANCH, "wip"), dry_run=True))
    assert "salvage" not in report.deletions[0].detail


# -- local branch ------------------------------------------------------------


def test_a_branch_delete_git_performed_is_reported_as_done() -> None:
    """One question, and its answer is the outcome. The scripted port raises on
    anything it was not given, so a run that asked a second question about the
    ref would fail here rather than pass quietly."""
    port = ScriptedCommands(git={"branch -D -- feat/x": ok()})
    report = run(port, plan(target(TargetKind.BRANCH, "feat/x")))
    assert report.ok
    assert report.deletions[0].deleted
    assert report.deletions[0].verified
    assert report.deletions[0].detail == "local ref deleted"


def test_a_ref_probe_that_would_not_answer_costs_the_deletion_nothing() -> None:
    """The case that earned the removal of the second question. It ran after a
    successful `branch -D`, and a git that would not answer it turned a
    deletion that had happened into a row saying it had not -- which sends a
    caller to re-run, or to raw git, over work already done."""
    port = ScriptedCommands(
        git={
            "branch -D -- feat/x": ok(),
            "for-each-ref --format=%(refname) refs/heads/feat/x": fail("fatal: bad repository"),
        }
    )
    report = run(port, plan(target(TargetKind.BRANCH, "feat/x")))
    assert report.ok
    assert report.deletions[0].deleted
    assert report.deletions[0].detail == "local ref deleted"


def test_a_ref_that_would_still_resolve_is_not_re_adjudicated() -> None:
    """What taking git at its word costs, stated rather than left to be found.
    The ref list would still show this branch, and nobody asks it: `branch -D`
    said what it did and that is the report."""
    port = ScriptedCommands(
        git={
            "branch -D -- feat/x": ok(),
            "for-each-ref --format=%(refname) refs/heads/feat/x": ok("refs/heads/feat/x"),
        }
    )
    report = run(port, plan(target(TargetKind.BRANCH, "feat/x")))
    assert report.ok
    assert report.deletions[0].deleted
    assert not any("for-each-ref" in call for call in port.transcript)


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


def test_a_worktree_removal_git_performed_is_reported_as_done() -> None:
    """`worktree remove` reporting success is the outcome, and the port raises
    on any question this does not script -- so a run that went back to the
    worktree listing afterwards would fail here."""
    port = ScriptedCommands(git={"worktree remove -- /repo/wt": ok()})
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt")))
    assert report.ok
    assert report.deletions[0].deleted
    assert report.deletions[0].verified
    assert report.deletions[0].detail == "worktree removed"


def test_a_removal_is_not_re_checked_against_a_listing() -> None:
    """The listing is not consulted after a removal git said it performed, and
    that settles four cases at once rather than one per listing defect.

    Each of them is a way for a confirmation to fail to confirm something that
    happened: a listing that will not run, one that loses a record to a
    truncation, one whose framing cannot spell the path being looked for, and
    one that answers with the worktree still in it. Three would report a
    removal that happened as one that had not. The fourth is the case such a
    check exists for, and the price of losing it is stated here rather than
    hidden: git said the tree is gone, and the report says so."""
    port = ScriptedCommands(
        git={
            "worktree remove -- /repo/wt": ok(),
            "worktree list --porcelain": ok(porcelain("worktree /repo\n\nworktree /repo/wt\n")),
        }
    )
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt")))

    assert report.ok
    assert report.deletions[0].deleted
    assert not any("list" in call for call in port.transcript)


def test_a_worktree_path_holding_a_newline_reaches_git_whole() -> None:
    """A path may contain a newline, and every hazard that creates is about
    reading it back out of git's output. The removal itself takes the path as
    one argument, so it is handed over whole."""
    path = "/repo/we\nird"
    port = ScriptedCommands(git={f"worktree remove -- {path}": ok()})
    report = run(port, plan(target(TargetKind.WORKTREE, path)))

    assert report.ok
    assert report.deletions[0].deleted
    removal = next(call for call in port.transcript if call[:3] == ("git", "worktree", "remove"))
    assert removal[-1] == path


def test_a_worktree_is_never_removed_with_force() -> None:
    """Not on a sweep, not when the caller names it. --force is what turns
    git's own checks off -- the dirt check, the lock, the main working tree --
    and overriding them means re-implementing in Python what git has just read
    off the disk. Naming a target authorises the deletion; it does not make
    this process a better judge of that directory than git is."""
    port = ScriptedCommands(git={"worktree remove -- /repo/wt": ok()})
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
    port = ScriptedCommands(git={"worktree remove -- /repo/wt": ok()})
    report = run(port, plan(target(TargetKind.WORKTREE, "/repo/wt")))
    assert report.ok
    assert not any("prune" in call for call in port.transcript)


def test_removing_a_worktree_that_holds_an_orphan_commit_says_what_it_cost() -> None:
    """git's interlocks cover uncommitted content and say nothing about a
    commit made in this tree on no branch: the tree is clean, git removes it
    happily, and the per-worktree reflog that held the commit goes with the
    record. Naming the tree authorises that, so the removal proceeds -- and
    what the caller is owed afterwards is the commit and the command that
    keeps it, on the row for the tree that held it."""
    head = "a" * 40
    port = ScriptedCommands(
        git={
            "rev-parse HEAD": ok(head),
            f"for-each-ref --count=1 --contains={head}": ok(""),
            "worktree remove -- /repo/wt": ok(),
        }
    )
    report = run(
        port,
        plan(target(TargetKind.WORKTREE, "/repo/wt")),
        make_survey(worktrees=(make_worktree("/repo/wt", head=head, branch=None),)),
    )

    assert report.ok
    assert report.deletions[0].deleted
    detail = report.deletions[0].detail
    assert head[:8] in detail
    assert "no ref contains" in detail
    assert f"git branch <name> {head[:8]}" in detail


def test_a_reachability_probe_that_will_not_answer_is_disclosed_not_decided() -> None:
    """A probe that failed made no measurement, so the row says that rather
    than choosing one of the two answers it might have given. Reporting "no ref
    contains it" would be a claim nobody checked; reporting nothing at all
    would hide a commit that may have just gone out of reach."""
    head = "a" * 40
    port = ScriptedCommands(
        git={
            "rev-parse HEAD": ok(head),
            f"for-each-ref --count=1 --contains={head}": fail("fatal: bad object"),
            "worktree remove -- /repo/wt": ok(),
        }
    )
    report = run(
        port,
        plan(target(TargetKind.WORKTREE, "/repo/wt")),
        make_survey(worktrees=(make_worktree("/repo/wt", head=head, branch=None),)),
    )

    assert report.ok
    assert report.deletions[0].deleted
    detail = report.deletions[0].detail
    assert head[:8] in detail
    assert "could not be read" in detail
    assert "unknown" in detail


def test_the_commit_disclosed_is_the_one_the_tree_holds_now() -> None:
    """The survey is a snapshot; the deletion happens after it. An agent
    committing in that tree in between leaves the recorded commit sitting on a
    branch -- where it answers "contained" -- and the new one held only by the
    record this call is about to delete.

    So a disclosure built from the surveyed commit is not a smaller one, it is
    about the wrong commit: it reports nothing at risk in exactly the case
    where something is."""
    surveyed, made_since = "a" * 40, "b" * 40
    port = ScriptedCommands(
        git={
            "rev-parse HEAD": ok(made_since),
            f"for-each-ref --count=1 --contains={surveyed}": ok("refs/heads/keeps-it"),
            f"for-each-ref --count=1 --contains={made_since}": ok(""),
            "worktree remove -- /repo/wt": ok(),
        }
    )
    report = run(
        port,
        plan(target(TargetKind.WORKTREE, "/repo/wt")),
        make_survey(worktrees=(make_worktree("/repo/wt", head=surveyed, branch=None),)),
    )

    assert report.ok
    assert made_since[:8] in report.deletions[0].detail
    assert surveyed[:8] not in report.deletions[0].detail


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


def _salvage_calls(bundle: str) -> dict[str, CommandResult]:
    """Every git question one whole salvage asks, answered the way a real one
    answers them -- including the restore.

    A script that stopped at `bundle create` would leave the run aborting on an
    unproven archive while the test claimed to be about the push."""
    return {
        "branch --no-track": ok(),
        f"branch -D -- {SALVAGE_PREFIX}": ok(),
        f"rev-parse --verify refs/heads/{SALVAGE_PREFIX}": ok(REMOTE_HEAD),
        f"bundle create {bundle}": ok(),
        f"clone --bare --quiet {bundle}": ok(),
        f"for-each-ref --count=1 --contains={REMOTE_HEAD}": ok(
            f"{REMOTE_HEAD} commit\trefs/heads/{SALVAGE_PREFIX}/x"
        ),
    }


def _remote_port(**overrides: object) -> ScriptedCommands:
    """Every server deletion is bundled first, so every one of these scripts
    the bundle. A test that omitted it would be exercising the salvage-failure
    path while claiming to be about the push.

    `ls-remote` is asked twice with two different answers, and that is a fact
    about the domain rather than about call order: the deletion in between is
    what changes what the server has. One answer for both would make a liar of
    one of them -- say `ok("")` throughout and the run finds the ref already
    gone and never pushes at all."""
    table: dict[str, CommandResult | list[CommandResult]] = {
        **_salvage_calls(FEAT_BUNDLE),
        "push --force-with-lease": ok(),
        "ls-remote": [ok(f"{REMOTE_HEAD}\trefs/heads/feat/x"), ok("")],
    }
    table.update(overrides)  # type: ignore[arg-type]
    return ScriptedCommands(git=table)


def test_remote_deletion_is_confirmed_against_the_server() -> None:
    """`deleted` is asserted alongside `verified` because a target that was
    already absent satisfies `ok` and `verified` too. Without this line the
    test passes on a fixture whose server never had the ref, which is a
    different code path than the one it is named for."""
    port = _remote_port()
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "origin/feat/x")), _remote_survey())
    assert report.ok
    assert report.deletions[0].verified
    assert report.deletions[0].deleted


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
    guessing a remote here: the run says what it cannot parse and stops.

    Which remote a ref belongs to is decided once, in the survey, against the
    configured remote list. By the time a target is here that answer either
    travelled with it or does not exist, and re-deriving it from the first
    slash is the thing this refuses to do -- git takes a path where it expects
    a remote, so the guess reaches a repository nobody named."""
    port = _remote_port(**_salvage_calls(f"/salvage/{slug('bare')}.bundle"))  # type: ignore[arg-type]
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, "bare")), _remote_survey("bare"))

    assert not report.ok
    assert "push" not in [call[1] for call in port.transcript]
    assert "without a remote and a branch name" in report.anomalies[0].message


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


def test_the_server_is_named_by_its_whole_remote_name() -> None:
    """A remote may be called `team/origin`, and git accepts a *path* wherever
    it expects a remote -- so `team`, the first component, reaches a sibling
    directory that happens to be a repository and answers about it instead. The
    answer is empty and well-formed, which here means `already gone`."""
    port = _remote_port(**{"ls-remote": ok("")})
    settled = plan(target(TargetKind.REMOTE_BRANCH, "team/origin/feat/x", remote="team/origin"))
    run(port, settled, _remote_survey("team/origin/feat/x"))

    probe = next(call for call in port.transcript if call[1] == "ls-remote")
    assert probe[3] == "team/origin"
    assert "team" not in probe[3:]


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
    port = _remote_port(
        **{
            "ls-remote": [
                ok(f"{REMOTE_HEAD}\trefs/heads/feat/x"),
                ok("dbfd823\trefs/heads/a/feat/x"),
            ]
        }
    )
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
    table: dict[str, CommandResult | list[CommandResult]] = {
        **_salvage_calls(WIP_BUNDLE),
        "push --force-with-lease": ok(),
        # Present, then gone. See _remote_port for why one answer will not do.
        "ls-remote": [ok(f"{REMOTE_HEAD}\trefs/heads/wip"), ok("")],
    }
    table.update(overrides)  # type: ignore[arg-type]
    return ScriptedCommands(git=table)


def test_a_server_ref_is_bundled_before_it_is_deleted() -> None:
    """`push --delete` is irreversible for everyone fetching and the server
    keeps no reflog, so this is the only deletion left with no undo behind it
    -- and the only one still worth a bundle."""
    port = _remote_salvage_port()
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, REMOTE)), _remote_survey(REMOTE))
    assert report.ok
    verbs = [t[1] for t in port.transcript]
    assert verbs.index("bundle") < verbs.index("push")
    # And the restore too: an archive nobody opened is not what the report
    # calls verified.
    assert verbs.index("clone") < verbs.index("push")
    assert report.salvages[0].verified


def test_a_server_ref_the_forge_already_deleted_costs_nothing() -> None:
    """A forge that drops the branch when its PR merges is the common setup,
    and the stale tracking ref it leaves behind is the only reason this target
    is in the plan at all. Found from the rejected push instead, the same fact
    costs an archive of the whole history, written for a ref that was never
    there to lose, and lands as an anomaly over a job already finished."""
    port = _remote_salvage_port(**{"ls-remote": ok("")})
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, REMOTE)), _remote_survey(REMOTE))

    assert report.ok
    assert report.deletions[0].already_absent
    assert report.salvages == ()
    # One read-only question and nothing else: no scratch branch, no bundle,
    # no clone, no push.
    assert [call[1] for call in port.transcript] == ["ls-remote"]


def test_an_already_absent_ref_is_not_evidence_the_run_did_something() -> None:
    """`deleted` is the field that says the tool acted, and a caller counting
    what a cleanup achieved must not be handed work it never did."""
    port = _remote_salvage_port(**{"ls-remote": ok("")})
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, REMOTE)), _remote_survey(REMOTE))

    assert not report.deletions[0].deleted
    assert report.deletions[0].verified


def test_an_already_absent_ref_says_which_stale_ref_conjured_it() -> None:
    """The target exists because refs/remotes still names it, so the row that
    reports nothing to do should say where the phantom came from -- otherwise
    the next report shows it again and reads as a cleanup that did not work."""
    port = _remote_salvage_port(**{"ls-remote": ok("")})
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, REMOTE)), _remote_survey(REMOTE))

    assert "fetch --prune origin" in report.deletions[0].detail


def test_a_probe_that_will_not_answer_never_claims_the_ref_is_gone() -> None:
    """Not knowing whether the server still has it is not evidence that it
    does not. The ordinary route runs, which is the one keeping a lease in
    front of the delete -- and being wrong this way costs a bundle, while being
    wrong the other way skips a deletion the caller asked for."""
    port = _remote_salvage_port(**{"ls-remote": fail("could not read from remote")})
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, REMOTE)), _remote_survey(REMOTE))

    assert not any(d.already_absent for d in report.deletions)
    assert "push" in [call[1] for call in port.transcript]


def test_a_local_branch_is_not_bundled() -> None:
    """`branch -D` leaves the commits in the reflog for git's configured
    expiry. Bundling them as well buys disk usage and a restore route nobody
    takes, in front of a deletion that already has one."""
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
    assert port.transcript == [
        # The server is asked first, and nothing above is spent until it says
        # the ref is there to lose.
        ("git", "ls-remote", "--heads", "origin", "refs/heads/wip"),
        ("git", "branch", "--no-track", scratch, f"refs/remotes/{REMOTE}"),
        ("git", "rev-parse", "--verify", f"refs/heads/{scratch}"),
        ("git", "bundle", "create", WIP_BUNDLE, f"refs/heads/{scratch}"),
        ("git", "clone", "--bare", "--quiet", WIP_BUNDLE, "/scratch/restored"),
        ("git", "for-each-ref", "--count=1", f"--contains={REMOTE_HEAD}"),
        ("git", "branch", "-D", "--", scratch),
        ("git", "push", f"--force-with-lease=wip:{REMOTE_HEAD}", "origin", "--delete", "--", "wip"),
        ("git", "ls-remote", "--heads", "origin", "refs/heads/wip"),
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


def test_a_bundle_that_will_not_open_aborts_the_deletion() -> None:
    """An archive nobody can open is not a safety net, so it buys no deletion.

    `git bundle verify` is the obvious thing to ask, and it answers about the
    repository it runs in -- the one holding every object already. It reports a
    complete history for a bundle `git clone` refuses, so a report resting on
    it says verified in front of a deletion with no undo."""
    port = _remote_salvage_port(
        **{f"clone --bare --quiet {WIP_BUNDLE}": fail("remote did not send all necessary objects")}
    )
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, REMOTE)), _remote_survey(REMOTE))
    assert not report.ok
    assert "does not restore" in report.anomalies[0].message
    assert any("clone" in line for line in report.anomalies[0].transcript)
    assert report.salvages == ()
    assert "push" not in [t[1] for t in port.transcript]


def test_a_restore_that_does_not_hold_the_commit_aborts_the_deletion() -> None:
    """Opening is not restoring. A bundle of a remote-tracking ref clones back
    an empty repository, so the archive exists, the clone succeeds, and the
    commit the deletion takes is in none of it."""
    port = _remote_salvage_port(
        **{f"for-each-ref --count=1 --contains={REMOTE_HEAD}": fail("error: no such commit")}
    )
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, REMOTE)), _remote_survey(REMOTE))
    assert not report.ok
    assert REMOTE_HEAD[:8] in report.anomalies[0].message
    assert report.salvages == ()
    assert "push" not in [t[1] for t in port.transcript]


def test_a_restore_whose_probe_answers_nothing_aborts_the_deletion() -> None:
    """`for-each-ref` exits 0 with no output when no ref contains the commit,
    which is the same news as the probe failing and must not read as a yes."""
    port = _remote_salvage_port(**{f"for-each-ref --count=1 --contains={REMOTE_HEAD}": ok("")})
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, REMOTE)), _remote_survey(REMOTE))
    assert not report.ok
    assert "reachable from no ref" in report.anomalies[0].message
    assert report.salvages == ()
    assert "push" not in [t[1] for t in port.transcript]


def test_an_unreadable_scratch_tip_aborts_before_anything_is_bundled() -> None:
    """The claim is about a commit, not about a file. With no commit to look
    for, a restore has nothing it could be checked against."""
    port = _remote_salvage_port(
        **{
            f"rev-parse --verify refs/heads/{SALVAGE_PREFIX}": fail(
                "fatal: needed a single revision"
            )
        }
    )
    report = run(port, plan(target(TargetKind.REMOTE_BRANCH, REMOTE)), _remote_survey(REMOTE))
    assert not report.ok
    assert "nothing to be checked against" in report.anomalies[0].message
    assert report.salvages == ()
    assert "bundle" not in [t[1] for t in port.transcript]


def test_missing_salvage_directory_aborts_rather_than_deleting_unprotected() -> None:
    """The assertion is that nothing was *changed*, which is narrower than
    `transcript == []` and is the claim this test is about. One read-only
    question precedes the abort: whether the server still has the ref. It has
    to, and in that order -- a ref the server no longer holds needs no bundle,
    so refusing it for want of somewhere to put one would be an error raised
    about a job that does not exist."""
    port = ScriptedCommands(git={"ls-remote": ok(f"{REMOTE_HEAD}\trefs/heads/wip")})
    report = run(
        port,
        plan(target(TargetKind.REMOTE_BRANCH, REMOTE), salvage_dir=None),
        _remote_survey(REMOTE),
    )
    assert not report.ok
    assert [call[1] for call in port.transcript] == ["ls-remote"]


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
