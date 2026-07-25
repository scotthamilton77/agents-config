"""Tests for the judgement rules. Each pins a decision the tool makes, not a
property of Python."""

from __future__ import annotations

from datetime import datetime

from conftest import iso, make_branch, make_pr, make_survey, make_worktree

from gitclean.classify import classify, classify_branch, classify_worktree
from gitclean.model import Disposition, MergeEvidence, Risk

NO_LOCALS: frozenset[str] = frozenset()


def _one(branch, survey=None, *, now: datetime, idle_days: int = 14):  # type: ignore[no-untyped-def]
    from datetime import timedelta

    return classify_branch(
        branch,
        survey or make_survey(),
        now=now,
        idle_window=timedelta(days=idle_days),
        local_names=NO_LOCALS,
    )


# -- the squash-merge case, which is the whole reason this tool exists --------


def test_squash_merged_branch_is_safe_despite_unmerged_commit_count(now: datetime) -> None:
    """A squash-merged branch still shows commits 'not in base' -- ancestry
    says unmerged. The evidence tier is what makes it sweepable."""
    branch = make_branch(
        unmerged_commits=3,
        merge_evidence=MergeEvidence.SQUASH_EQUAL,
        pr=make_pr(state="MERGED"),
    )
    target = _one(branch, now=now)
    assert target.disposition is Disposition.SAFE
    assert target.risk is Risk.NONE


def test_pr_merged_evidence_is_recorded_in_reasons(now: datetime) -> None:
    branch = make_branch(merge_evidence=MergeEvidence.PR_MERGED, pr=make_pr(state="MERGED"))
    target = _one(branch, now=now)
    assert any("pr_merged" in reason for reason in target.reasons)


# -- the closed-PR discard decision, and its expiry ---------------------------


def test_closed_pr_makes_an_unmerged_branch_safe(now: datetime) -> None:
    branch = make_branch(
        merge_evidence=MergeEvidence.PR_CLOSED_UNMERGED,
        pr=make_pr(state="CLOSED", updated_at=iso(2)),
        last_activity=iso(5),
        unmerged_commits=4,
    )
    target = _one(branch, now=now)
    assert target.disposition is Disposition.SAFE
    assert target.risk is Risk.NONE


def test_commits_after_the_close_make_the_discard_decision_stale(now: datetime) -> None:
    """The human said 'drop this' two days ago; the branch gained a commit
    yesterday. The decision no longer covers what is there now."""
    branch = make_branch(
        merge_evidence=MergeEvidence.PR_CLOSED_UNMERGED,
        pr=make_pr(state="CLOSED", updated_at=iso(2)),
        last_activity=iso(1),
        unmerged_commits=4,
        upstream=None,
    )
    target = _one(branch, now=now)
    assert target.disposition is not Disposition.SAFE
    assert target.risk is Risk.RECOVERABLE
    assert any("stale" in reason for reason in target.reasons)


# -- protection is absolute --------------------------------------------------


def test_default_branch_is_protected(now: datetime) -> None:
    branch = make_branch("main", is_default=True, merged=True)
    assert _one(branch, now=now).disposition is Disposition.PROTECTED


def test_current_branch_is_protected_even_when_merged(now: datetime) -> None:
    branch = make_branch("feat/thing", merge_evidence=MergeEvidence.ANCESTOR)
    survey = make_survey(current_branch="feat/thing")
    assert _one(branch, survey, now=now).disposition is Disposition.PROTECTED


# -- lifecycle ---------------------------------------------------------------


def test_open_pr_beats_idle_age(now: datetime) -> None:
    """A branch untouched for a year with a PR still open is not abandoned."""
    branch = make_branch(last_activity=iso(365), pr=make_pr(state="OPEN"))
    assert _one(branch, now=now).disposition is Disposition.ACTIVE


def test_idle_unmerged_branch_without_a_pr_is_abandoned(now: datetime) -> None:
    branch = make_branch(last_activity=iso(30))
    assert _one(branch, now=now).disposition is Disposition.ABANDONED


def test_recent_unmerged_branch_is_active(now: datetime) -> None:
    branch = make_branch(last_activity=iso(3))
    assert _one(branch, now=now).disposition is Disposition.ACTIVE


def test_idle_window_is_configurable(now: datetime) -> None:
    branch = make_branch(last_activity=iso(10))
    assert _one(branch, now=now, idle_days=30).disposition is Disposition.ACTIVE
    assert _one(branch, now=now, idle_days=7).disposition is Disposition.ABANDONED


# -- risk --------------------------------------------------------------------


def test_fully_pushed_branch_carries_no_risk(now: datetime) -> None:
    branch = make_branch(upstream="origin/feat/thing", unpushed_commits=0)
    assert _one(branch, now=now).risk is Risk.NONE


def test_never_pushed_branch_is_recoverable_only(now: datetime) -> None:
    branch = make_branch(upstream=None)
    assert _one(branch, now=now).risk is Risk.RECOVERABLE


def test_unpushed_commits_make_a_pushed_branch_risky(now: datetime) -> None:
    branch = make_branch(upstream="origin/feat/thing", unpushed_commits=2)
    assert _one(branch, now=now).risk is Risk.RECOVERABLE


def test_unmerged_remote_branch_is_data_loss(now: datetime) -> None:
    """The server keeps no reflog, so a deleted remote ref is simply gone."""
    branch = make_branch("origin/feat/thing", is_remote=True, remote="origin")
    assert _one(branch, now=now).risk is Risk.DATA_LOSS


def test_discarded_remote_with_a_surviving_local_copy_is_free(now: datetime) -> None:
    from datetime import timedelta

    branch = make_branch(
        "origin/feat/thing",
        is_remote=True,
        remote="origin",
        merge_evidence=MergeEvidence.PR_CLOSED_UNMERGED,
        pr=make_pr(state="CLOSED", updated_at=iso(1)),
        last_activity=iso(2),
    )
    target = classify_branch(
        branch,
        make_survey(),
        now=now,
        idle_window=timedelta(days=14),
        local_names=frozenset({"feat/thing"}),
    )
    assert target.risk is Risk.NONE


def test_discarded_remote_without_a_local_copy_is_the_last_copy(now: datetime) -> None:
    from datetime import timedelta

    branch = make_branch(
        "origin/feat/thing",
        is_remote=True,
        remote="origin",
        merge_evidence=MergeEvidence.PR_CLOSED_UNMERGED,
        pr=make_pr(state="CLOSED", updated_at=iso(1)),
        last_activity=iso(2),
    )
    target = classify_branch(
        branch, make_survey(), now=now, idle_window=timedelta(days=14), local_names=NO_LOCALS
    )
    assert target.risk is Risk.RECOVERABLE


# -- worktrees ---------------------------------------------------------------


def test_dirty_worktree_is_active_regardless_of_branch_age(now: datetime) -> None:
    """The load-bearing rule: uncommitted work is unfinished, never stale."""
    from datetime import timedelta

    worktree = make_worktree(dirty_file_count=2, last_activity=iso(400))
    target = classify_worktree(worktree, {}, now=now, idle_window=timedelta(days=14))
    assert target.disposition is Disposition.ACTIVE
    assert target.risk is Risk.DATA_LOSS
    assert target.salvage_needed


def test_untracked_files_alone_make_a_worktree_dirty(now: datetime) -> None:
    from datetime import timedelta

    worktree = make_worktree(untracked_file_count=1, last_activity=iso(400))
    target = classify_worktree(worktree, {}, now=now, idle_window=timedelta(days=14))
    assert target.risk is Risk.DATA_LOSS


def test_main_worktree_is_protected(now: datetime) -> None:
    from datetime import timedelta

    target = classify_worktree(
        make_worktree("/repo", is_main=True), {}, now=now, idle_window=timedelta(days=14)
    )
    assert target.disposition is Disposition.PROTECTED


def test_locked_worktree_is_protected(now: datetime) -> None:
    from datetime import timedelta

    target = classify_worktree(
        make_worktree(locked=True), {}, now=now, idle_window=timedelta(days=14)
    )
    assert target.disposition is Disposition.PROTECTED


def test_prunable_worktree_is_safe(now: datetime) -> None:
    from datetime import timedelta

    target = classify_worktree(
        make_worktree(prunable=True), {}, now=now, idle_window=timedelta(days=14)
    )
    assert target.disposition is Disposition.SAFE
    assert target.risk is Risk.NONE


def test_clean_worktree_inherits_its_branch_disposition(now: datetime) -> None:
    survey = make_survey(
        branches=(make_branch("feat/thing", merge_evidence=MergeEvidence.PR_MERGED),),
        worktrees=(make_worktree("/repo/wt", branch="feat/thing"),),
        current_branch="main",
    )
    targets = classify(survey, now=now)
    worktree = next(t for t in targets if t.id == "worktree:/repo/wt")
    assert worktree.disposition is Disposition.SAFE
    assert worktree.risk is Risk.NONE


def test_worktree_holding_a_protected_branch_is_active_not_protected(now: datetime) -> None:
    """The branch cannot be deleted; the checkout still can be."""
    survey = make_survey(
        branches=(make_branch("main", is_default=True),),
        worktrees=(make_worktree("/repo/wt", branch="main"),),
    )
    targets = classify(survey, now=now)
    worktree = next(t for t in targets if t.id == "worktree:/repo/wt")
    assert worktree.disposition is Disposition.ACTIVE


def test_detached_worktree_falls_back_to_age(now: datetime) -> None:
    from datetime import timedelta

    stale = classify_worktree(
        make_worktree(branch=None, last_activity=iso(40)),
        {},
        now=now,
        idle_window=timedelta(days=14),
    )
    fresh = classify_worktree(
        make_worktree(branch=None, last_activity=iso(1)),
        {},
        now=now,
        idle_window=timedelta(days=14),
    )
    assert stale.disposition is Disposition.ABANDONED
    assert fresh.disposition is Disposition.ACTIVE


# -- ordering ----------------------------------------------------------------


def test_classify_orders_worktrees_before_branches(now: datetime) -> None:
    """Deletion order is a correctness requirement: git refuses to delete a
    branch a worktree still holds."""
    survey = make_survey(
        branches=(
            make_branch("feat/a"),
            make_branch("origin/feat/a", is_remote=True, remote="origin"),
        ),
        worktrees=(make_worktree("/repo/wt", branch="feat/a"),),
    )
    kinds = [t.kind.value for t in classify(survey, now=now)]
    assert kinds == ["worktree", "branch", "remote_branch"]
