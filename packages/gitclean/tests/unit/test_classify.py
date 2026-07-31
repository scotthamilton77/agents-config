"""Tests for the judgement rules. Each pins a decision the tool makes, not a
property of Python.

Almost every test here is a question about one thing: what does an unattended
sweep take, and what does it decline to take while saying why. The rest of the
report is measurement, and measurement is the survey's business."""

from __future__ import annotations

from conftest import iso, make_branch, make_pr, make_survey, make_worktree

from gitclean.classify import classify, classify_branch, classify_worktree, trunk
from gitclean.model import MergeEvidence, Survey, Target

# A commit no fixture's trunk sits on, for the cases that must not collide with
# it: matching the trunk's commit is itself a rule under test.
ELSEWHERE = "e" * 40


def _one(branch, survey: Survey | None = None) -> Target:  # type: ignore[no-untyped-def]
    resolved = survey or make_survey()
    names, commits = trunk(resolved)
    return classify_branch(branch, resolved, trunk_names=names, trunk_commits=commits)


def _wt(worktree, survey: Survey | None = None) -> Target:  # type: ignore[no-untyped-def]
    resolved = survey or make_survey()
    names, commits = trunk(resolved)
    return classify_worktree(worktree, resolved, trunk_names=names, trunk_commits=commits)


# -- the squash-merge case, which is the whole reason this tool exists --------


def test_squash_merged_branch_is_swept_despite_unmerged_commit_count() -> None:
    """A squash-merged branch still shows commits 'not in base' -- ancestry
    says unmerged. The evidence tier is what makes it sweepable."""
    branch = make_branch(
        head=ELSEWHERE,
        unmerged_commits=3,
        merge_evidence=MergeEvidence.SQUASH_EQUAL,
        pr=make_pr(state="MERGED"),
    )
    target = _one(branch)
    assert target.merge_proven
    assert target.sweepable
    assert target.withheld is None


def test_pr_merged_evidence_is_recorded_in_reasons() -> None:
    branch = make_branch(
        head=ELSEWHERE, merge_evidence=MergeEvidence.PR_MERGED, pr=make_pr(state="MERGED")
    )
    assert any("pr_merged" in reason for reason in _one(branch).reasons)


def test_every_tier_that_counts_as_proof_authorises_a_sweep() -> None:
    """Four tiers prove a merge, and each one on its own is enough. Asserting
    the set rather than a member is what stops a tier quietly dropping out of
    it: a sweep that stopped honouring patch equality would still pass a suite
    that only ever asked about the squash case."""
    for evidence in (
        MergeEvidence.PR_MERGED,
        MergeEvidence.ANCESTOR,
        MergeEvidence.PATCH_EQUAL,
        MergeEvidence.SQUASH_EQUAL,
    ):
        target = _one(make_branch(head=ELSEWHERE, merge_evidence=evidence))
        assert target.sweepable, f"{evidence.value} did not authorise a sweep"
        assert target.withheld is None
        assert target.merge_proven


def test_a_merged_pr_that_does_not_cover_the_tip_stays_out_of_the_sweep() -> None:
    """The survey declined the PR verdict (evidence is NONE) but the merged PR
    is still attached. Reading state instead of evidence is what deleted
    post-merge commits."""
    branch = make_branch(
        head=ELSEWHERE,
        merge_evidence=MergeEvidence.NONE,
        pr=make_pr(state="MERGED", head_oid="b" * 40),
    )
    assert not _one(branch).sweepable


def test_a_declined_pr_verdict_says_why() -> None:
    """Without this the branch silently stops being sweepable and the reader is
    left diffing SHAs to find out what changed."""
    branch = make_branch(
        merge_evidence=MergeEvidence.NONE, pr=make_pr(state="MERGED", head_oid="b" * 40)
    )
    reasons = " ".join(_one(branch).reasons)
    assert "does not cover what is here" in reasons
    assert "bbbbbbbb" in reasons


def test_an_honoured_pr_verdict_adds_no_coverage_complaint() -> None:
    branch = make_branch(merge_evidence=MergeEvidence.PR_MERGED, pr=make_pr(state="MERGED"))
    assert not any("does not cover" in r for r in _one(branch).reasons)


def test_a_lower_tier_proving_the_merge_silences_the_coverage_complaint() -> None:
    """The PR verdict was declined but squash equivalence proved the merge, so
    the branch is merged. Saying "does not cover what is here" beside "merge
    proven by squash_equal" reads as a contradiction, not an explanation."""
    branch = make_branch(
        merged=True,
        merge_evidence=MergeEvidence.SQUASH_EQUAL,
        pr=make_pr(state="MERGED", head_oid="b" * 40),
    )
    assert not any("does not cover" in r for r in _one(branch).reasons)


# -- a closed PR is a fact, not an authority ---------------------------------


def test_a_closed_unmerged_pr_does_not_authorise_a_sweep() -> None:
    """Closing a PR says a person stopped wanting the change. It says nothing
    about whether the commits exist anywhere else, and they do not: they are
    still only on this branch. This is what deleted branches whose PR was
    closed while the work carried on under a different plan."""
    branch = make_branch(
        head=ELSEWHERE,
        merge_evidence=MergeEvidence.PR_CLOSED_UNMERGED,
        pr=make_pr(state="CLOSED", updated_at=iso(2)),
        last_activity=iso(5),
        unmerged_commits=4,
    )
    target = _one(branch)
    assert not target.merge_proven
    assert not target.sweepable
    assert "pr_closed_unmerged" in (target.withheld or "")


def test_a_closed_unmerged_pr_is_still_reported_as_the_fact_it_is() -> None:
    """It is the most useful line in the row for a human deciding what to name,
    so dropping it along with its authority would be the wrong half to remove."""
    branch = make_branch(
        merge_evidence=MergeEvidence.PR_CLOSED_UNMERGED, pr=make_pr(number=7, state="CLOSED")
    )
    assert any("PR #7 was closed without merging" in r for r in _one(branch).reasons)


# -- an unknown is never evidence for deletion -------------------------------


def test_an_uncounted_unmerged_total_never_yields_the_sweep() -> None:
    """`rev-list --count` failing must not resolve to 'nothing ahead of base'."""
    branch = make_branch(head=ELSEWHERE, unmerged_commits=None, upstream=None)
    target = _one(branch)
    assert not target.sweepable
    assert any("merge state unproven" in reason for reason in target.reasons)


def test_an_uncounted_unpushed_total_is_stated_as_unknown() -> None:
    """The count is not what authorises anything any more -- merge evidence is
    -- but a probe that went quiet still renders as a stated unknown on this
    branch's own row rather than vanishing."""
    branch = make_branch(upstream="origin/feat/thing", unpushed_commits=None)
    assert any("nothing proves these commits are pushed" in r for r in _one(branch).reasons)


def test_a_branch_with_no_timestamp_says_so_without_drawing_a_conclusion() -> None:
    """Unknown age is not old age -- and known age is not evidence of anything
    either, which is why nothing downstream reads this."""
    target = _one(make_branch(last_activity=None))
    assert any("age is unknown" in reason for reason in target.reasons)
    assert not any("abandon" in reason for reason in target.reasons)


def test_a_containment_check_that_did_not_answer_is_not_reported_as_a_mismatch() -> None:
    """git could not place the two commits, which is routine once the remote
    branch is gone. Printing the mismatch sentence points the reader at a
    difference between SHAs that no probe established."""
    branch = make_branch(
        merge_evidence=MergeEvidence.NONE,
        pr=make_pr(number=9, state="MERGED", head_oid="b" * 40),
        pr_covers_tip=None,
    )
    reasons = " ".join(_one(branch).reasons)
    assert "would not say whether PR #9's head" in reasons
    assert "does not cover what is here" not in reasons


def test_a_merge_probe_that_errored_is_named_on_the_branchs_own_row() -> None:
    """`evidence: none` is the same value whether every tier ran and none fired
    or two of them errored, and only one of those is a measurement."""
    branch = make_branch(
        head=ELSEWHERE,
        probe_failures=("the squash-equivalence probe against origin/main errored",),
    )
    assert any("squash-equivalence probe" in r for r in _one(branch).reasons)


def test_a_branch_with_no_pr_evidence_says_so_rather_than_only_the_envelope() -> None:
    """`repo.gh_error` is one line at the top of the report for a whole list of
    rows. A reader scanning rows cannot tell that the only tier which sees a
    squash merge never ran for this one."""
    survey = make_survey(gh_error="gh not on PATH; merge evidence limited to git")
    branch = make_branch(head=ELSEWHERE, merge_evidence=MergeEvidence.NONE)
    assert any("no pull-request evidence was read" in r for r in _one(branch, survey).reasons)


def test_a_branch_already_proven_merged_does_not_complain_about_pr_evidence() -> None:
    """The gap changed no outcome here, and the sentence would only compete
    with the proof beside it."""
    survey = make_survey(gh_error="gh not on PATH; merge evidence limited to git")
    branch = make_branch(head=ELSEWHERE, merge_evidence=MergeEvidence.SQUASH_EQUAL)
    assert not any("no pull-request evidence" in r for r in _one(branch, survey).reasons)


def test_a_branch_the_pr_list_may_not_have_reached_says_so() -> None:
    """A truncated list leaves a branch with no PR sitting beside a branch that
    genuinely never had one, and nothing in the index says which is which."""
    survey = make_survey(pr_evidence_gap="only the 500 most recently updated PRs were read")
    branch = make_branch(head=ELSEWHERE, merge_evidence=MergeEvidence.NONE)
    assert any("may not have been read" in r for r in _one(branch, survey).reasons)


def test_a_branch_whose_pr_was_read_says_nothing_about_the_gap() -> None:
    survey = make_survey(pr_evidence_gap="only the 500 most recently updated PRs were read")
    branch = make_branch(head=ELSEWHERE, pr=make_pr(number=3, state="OPEN"))
    assert not any("may not have been read" in r for r in _one(branch, survey).reasons)


def test_a_worktree_says_when_no_ref_was_read_to_judge_its_commit_against() -> None:
    """With the ref read itself failed, nothing *could* have proved the commit
    this worktree holds merged -- which is a different statement from four
    tiers running and proving nothing."""
    survey = make_survey(branches_known=False)
    reasons = _wt(make_worktree(head=ELSEWHERE, branch=None), survey).reasons
    assert any("no ref could be read" in r for r in reasons)


def test_an_unmeasured_ignored_count_is_stated_rather_than_left_as_silence() -> None:
    """Zero ignored files and an unreadable tree both render as no line at all,
    and the ignored count is the only warning a reader gets that a sweep takes
    a .env living nowhere else with it."""
    target = _wt(make_worktree(head=ELSEWHERE, branch=None, ignored_file_count=None))
    assert any("was not measured" in r for r in target.reasons)
    assert "None" not in " ".join(target.reasons)


def test_a_worktree_with_no_timestamp_says_its_age_is_unknown() -> None:
    """Branches said this and worktrees did not, so a `show` that failed left
    the row silent."""
    target = _wt(make_worktree(head=ELSEWHERE, branch=None, last_activity=None))
    assert any("age is unknown" in r for r in target.reasons)


def test_an_open_pr_is_named_on_the_row() -> None:
    """It is the single most useful fact for a person deciding what to name,
    and it is a fact -- unlike the verdict that used to be computed from it."""
    branch = make_branch(pr=make_pr(number=12, state="OPEN"))
    assert any("PR #12 is open" in r for r in _one(branch).reasons)


def test_unpushed_commits_are_counted_on_the_row() -> None:
    """Nothing reads this to authorise anything any more. It stays because it
    is what tells a reader whether deleting the branch costs them the only
    copy, which is the decision the report exists to support."""
    branch = make_branch(upstream="origin/feat/thing", unpushed_commits=3)
    assert any("3 commit(s) not on origin/feat/thing" in r for r in _one(branch).reasons)


def test_no_target_carries_a_lifecycle_word() -> None:
    """The report states measurements. "Abandoned" and "active" are claims
    about what a person intends, and nothing in a repository measures that."""
    survey = make_survey(
        branches=(
            make_branch("main", head="a" * 40, is_default=True),
            make_branch("feat/old", head="b" * 40, last_activity=iso(400)),
        ),
        worktrees=(make_worktree("/repo/wt", head="b" * 40, branch="feat/old"),),
    )
    prose = " ".join(r for t in classify(survey) for r in (*t.reasons, t.withheld or "")).lower()
    for word in ("abandoned", "active", "protected", "idle", "stale"):
        assert word not in prose


# -- the trunk ---------------------------------------------------------------


def test_the_local_trunk_is_never_swept_even_though_it_is_an_ancestor() -> None:
    """`main` is an ancestor of `origin/main`, so the merge tiers prove it
    merged and the first rule alone would delete the trunk. Measured on a real
    repository, not imagined: `branch:main` carries evidence `ancestor`."""
    branch = make_branch(
        "main", head=ELSEWHERE, is_default=True, merge_evidence=MergeEvidence.ANCESTOR
    )
    target = _one(branch, make_survey(default_branch="main", base_ref="origin/main"))
    assert target.merge_proven
    assert not target.sweepable
    assert "trunk" in (target.withheld or "")


def test_the_remote_counterpart_of_the_trunk_is_matched_by_name_not_by_string() -> None:
    """`main` and `origin/main` are different strings for the same trunk.
    Comparing the caller-facing name against `base_ref` never matched, which is
    how the local trunk stayed sweepable."""
    survey = make_survey(
        branches=(make_branch("main", head="a" * 40, is_default=True),),
        base_ref="origin/main",
        default_branch="main",
    )
    names, _ = trunk(survey)
    assert {"main", "origin/main"} <= names


def test_a_branch_sitting_on_the_trunk_commit_is_left_for_a_human() -> None:
    """Names are not the only way to be the trunk. A stale `old-main` parked on
    exactly the trunk's commit is indistinguishable from it by content, and
    leaving it in the report costs a branch nobody deleted.

    It is told apart from the trunk *itself* in the report, though. A branch
    cut from the trunk and never committed to sits on that commit too, and
    telling its owner "this is the trunk" is a confident falsehood about the
    thing being looked at -- the defect class this design exists to remove.
    Both are held back; only one of them is the trunk."""
    survey = make_survey(
        branches=(
            make_branch("main", head="a" * 40, is_default=True),
            make_branch("old-main", head="a" * 40, merge_evidence=MergeEvidence.ANCESTOR),
        )
    )
    targets = {t.id: t for t in classify(survey)}
    parked, real = targets["branch:old-main"], targets["branch:main"]

    assert not parked.sweepable and not real.sweepable
    assert "points at the trunk's tip" in (parked.withheld or "")
    assert parked.withheld != real.withheld


def test_nothing_is_swept_while_the_default_branch_is_unverified() -> None:
    """A dangling `origin/HEAD` leaves the run unable to tell trunk from cruft.
    Sweeping anyway is how a repository whose trunk is named `trunk` loses it."""
    survey = make_survey(default_branch="main", default_branch_known=False)
    branch = make_branch(head=ELSEWHERE, merge_evidence=MergeEvidence.ANCESTOR)
    target = _one(branch, survey)
    assert not target.sweepable
    assert "could not be verified" in (target.withheld or "")


# -- server refs -------------------------------------------------------------


def test_a_merged_remote_branch_is_reported_never_swept() -> None:
    """Deleting a server ref is irreversible for everyone fetching it and has
    no reflog behind it, so it takes an explicit name every time."""
    branch = make_branch(
        "origin/feat/thing",
        head=ELSEWHERE,
        is_remote=True,
        remote="origin",
        merge_evidence=MergeEvidence.PR_MERGED,
        pr=make_pr(state="MERGED"),
    )
    target = _one(branch)
    assert target.merge_proven
    assert not target.sweepable
    assert "server" in (target.withheld or "")


# -- worktrees ---------------------------------------------------------------


def test_a_worktree_is_judged_on_the_commit_it_holds() -> None:
    """Not on the branch's verdict -- on the evidence about the commit that
    branch points at, which is the commit the worktree holds."""
    survey = make_survey(
        branches=(
            make_branch("main", head="a" * 40, is_default=True),
            make_branch("feat/thing", head="c" * 40, merge_evidence=MergeEvidence.SQUASH_EQUAL),
        ),
        worktrees=(make_worktree("/repo/wt", head="c" * 40, branch="feat/thing"),),
    )
    target = next(t for t in classify(survey) if t.id == "worktree:/repo/wt")
    assert target.merge_evidence is MergeEvidence.SQUASH_EQUAL
    assert target.sweepable


def test_a_detached_worktree_holding_an_orphan_commit_is_never_swept() -> None:
    """The commit is on no branch, so nothing proves it is anywhere else. A
    clean working tree says the *files* are committed; it says nothing about
    where that commit lives, and reading it as 'holds no content' is what
    stranded orphan commits with no salvage and no flag."""
    survey = make_survey(
        branches=(make_branch("main", head="a" * 40, is_default=True),),
        worktrees=(make_worktree("/repo/wt", head="0" * 40, branch=None),),
    )
    target = next(t for t in classify(survey) if t.id == "worktree:/repo/wt")
    assert target.merge_evidence is MergeEvidence.NONE
    assert not target.sweepable
    assert "detached HEAD" in " ".join(target.reasons)


def test_a_detached_worktree_says_its_date_came_from_the_commit() -> None:
    """A detached checkout has no branch to date it from, so the date on its
    row is the commit's. A worktree made this morning at a two-year-old tag
    therefore reads as two years idle.

    Nothing decides anything on that number now -- the lifecycle verdict that
    used to call it abandoned is gone -- but a reader who saw only the date
    would draw the same conclusion by hand, so the row says what was
    measured."""
    survey = make_survey(
        branches=(make_branch("main", head="a" * 40, is_default=True),),
        worktrees=(
            make_worktree(
                "/repo/wt", head="0" * 40, branch=None, last_activity="2024-01-01T00:00:00+00:00"
            ),
        ),
    )
    reasons = " ".join(next(t for t in classify(survey) if t.id == "worktree:/repo/wt").reasons)
    assert "dated 2024-01-01 from the commit it holds" in reasons
    assert "not when this checkout was made" in reasons


def test_a_worktree_on_a_branch_does_not_disclaim_its_date() -> None:
    """The disclaimer is for the case that earns it. A worktree holding a
    branch is dated from that branch, which is what the field claims."""
    survey = make_survey(
        branches=(make_branch("main", head="a" * 40, is_default=True),),
        worktrees=(make_worktree("/repo/wt", head="0" * 40, branch="feat/thing"),),
    )
    reasons = " ".join(next(t for t in classify(survey) if t.id == "worktree:/repo/wt").reasons)
    assert "from the commit it holds" not in reasons


def test_a_detached_worktree_on_a_merged_commit_is_swept() -> None:
    """The unification cuts both ways: a detached checkout of a commit some
    merged branch also names is proven merged like anything else."""
    survey = make_survey(
        branches=(
            make_branch("main", head="a" * 40, is_default=True),
            make_branch("feat/done", head="c" * 40, merge_evidence=MergeEvidence.ANCESTOR),
        ),
        worktrees=(make_worktree("/repo/wt", head="c" * 40, branch=None),),
    )
    assert next(t for t in classify(survey) if t.id == "worktree:/repo/wt").sweepable


def test_a_dirty_worktree_is_reported_with_its_counts_and_never_swept() -> None:
    survey = make_survey(
        branches=(make_branch("feat/thing", head=ELSEWHERE, merge_evidence=MergeEvidence.ANCESTOR),)
    )
    worktree = make_worktree(head=ELSEWHERE, dirty_file_count=2, untracked_file_count=3)
    target = _wt(worktree, survey)
    assert not target.sweepable
    assert "2 modified and 3 untracked" in (target.withheld or "")


def test_an_unstatable_worktree_is_unknown_not_clean() -> None:
    survey = make_survey(
        branches=(make_branch("feat/thing", head=ELSEWHERE, merge_evidence=MergeEvidence.ANCESTOR),)
    )
    worktree = make_worktree(head=ELSEWHERE, dirty_file_count=None, untracked_file_count=None)
    target = _wt(worktree, survey)
    assert not target.sweepable
    assert "unknown" in (target.withheld or "")


def test_a_prunable_worktree_is_unknown_not_empty() -> None:
    """git says prunable when the recorded path is merely unreachable -- moved
    aside, or on an unmounted volume. Asserting the tree is empty was the one
    place an unknown was manufactured into the answer that authorises
    deletion."""
    survey = make_survey(
        branches=(make_branch("feat/thing", head=ELSEWHERE, merge_evidence=MergeEvidence.ANCESTOR),)
    )
    target = _wt(make_worktree(head=ELSEWHERE, prunable=True), survey)
    assert not target.sweepable
    assert "unreachable from here" in (target.withheld or "")
    # Nothing was probed, so the survey holds no counts -- and a row that
    # renders "None modified file(s)" quotes an unknown as though it were a
    # measurement, which is the same mistake in the report that asserting
    # (0, 0, 0) was in the verdict.
    assert "None" not in " ".join((*target.reasons, target.withheld or ""))


def test_ignored_files_do_not_stop_a_sweep_but_are_named_before_it() -> None:
    """The settled trade: caches and virtualenvs must not put a manual triage
    in front of every cleanup. The reason line is then the only place a reader
    learns what goes with the worktree, so it is not optional."""
    survey = make_survey(
        branches=(
            make_branch("main", head="a" * 40, is_default=True),
            make_branch("feat/thing", head="c" * 40, merge_evidence=MergeEvidence.PR_MERGED),
        ),
        worktrees=(
            make_worktree("/repo/wt", head="c" * 40, branch="feat/thing", ignored_file_count=9),
        ),
    )
    target = next(t for t in classify(survey) if t.id == "worktree:/repo/wt")
    assert target.sweepable
    assert any("9 ignored file(s) would be deleted with it" in r for r in target.reasons)


def test_a_worktree_with_no_ignored_files_says_nothing_about_them() -> None:
    assert not any("ignored" in r for r in _wt(make_worktree(branch=None)).reasons)


def test_the_worktree_the_run_is_executing_in_is_never_swept() -> None:
    """Removing it deletes the process's own working directory, and every git
    call after that fails against a path that is no longer there."""
    survey = make_survey(
        branches=(
            make_branch("main", head="a" * 40, is_default=True),
            make_branch("feat/thing", head="c" * 40, merge_evidence=MergeEvidence.ANCESTOR),
        ),
        worktrees=(make_worktree("/repo", head="c" * 40, branch="feat/thing", is_main=True),),
    )
    target = next(t for t in classify(survey) if t.id == "worktree:/repo")
    assert not target.sweepable
    assert "executing in" in (target.withheld or "")


def test_a_worktree_holding_the_trunk_is_not_swept() -> None:
    """`main` is an ancestor of `origin/main`, so the commit a trunk checkout
    holds is provably merged and the first rule waves it through."""
    survey = make_survey(
        branches=(
            make_branch(
                "main", head="a" * 40, is_default=True, merge_evidence=MergeEvidence.ANCESTOR
            ),
        ),
        worktrees=(make_worktree("/repo/wt", head="a" * 40, branch="main"),),
    )
    target = next(t for t in classify(survey) if t.id == "worktree:/repo/wt")
    assert not target.sweepable
    assert "trunk" in (target.withheld or "")


# -- ordering ----------------------------------------------------------------


def test_classify_orders_worktrees_before_branches() -> None:
    """Deletion order is a correctness requirement: git refuses to delete a
    branch a worktree still holds."""
    survey = make_survey(
        branches=(
            make_branch("feat/a", head="c" * 40),
            make_branch("origin/feat/a", head="c" * 40, is_remote=True, remote="origin"),
        ),
        worktrees=(make_worktree("/repo/wt", head="c" * 40, branch="feat/a"),),
    )
    kinds = [t.kind.value for t in classify(survey)]
    assert kinds == ["worktree", "branch", "remote_branch"]
