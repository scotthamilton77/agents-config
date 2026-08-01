"""Tests for selection, refusal, and ordering."""

from __future__ import annotations

from conftest import make_branch, make_survey

from gitclean.model import MergeEvidence, NotOffered, Plan, Refusal, Target, TargetKind
from gitclean.plan import build_plan, resolve_selectors


def target(
    ident: str,
    *,
    kind: TargetKind = TargetKind.BRANCH,
    name: str | None = None,
    sweepable: bool = True,
) -> Target:
    resolved = name if name is not None else ident.split(":", 1)[1]
    return Target(
        id=ident,
        kind=kind,
        name=resolved,
        merge_evidence=MergeEvidence.ANCESTOR if sweepable else MergeEvidence.NONE,
        merge_proven=sweepable,
        sweepable=sweepable,
        withheld=None if sweepable else "no merge proof for this commit (evidence: none)",
        reasons=(),
        last_activity=None,
    )


def plan_for(
    targets: tuple[Target, ...],
    *,
    survey=None,  # type: ignore[no-untyped-def]
    selectors: list[str] | None = None,
) -> Plan | Refusal:
    return build_plan(
        targets,
        survey if survey is not None else make_survey(),
        selectors=selectors or [],
        dry_run=False,
        salvage_dir="/salvage",
    )


# -- the default sweep -------------------------------------------------------


def test_a_bare_cleanup_takes_the_sweepable_subset_and_nothing_else() -> None:
    """The plan does not re-derive the rule; classification already answered
    it, target by target, with the reason it answered that way."""
    targets = (
        target("branch:merged"),
        target("branch:unproven", sweepable=False),
        target("worktree:/repo/wt", kind=TargetKind.WORKTREE, sweepable=False),
    )
    result = plan_for(targets)
    assert isinstance(result, Plan)
    assert [t.name for t in result.targets] == ["merged"]


# -- a named target is an authorisation, not a proposal ----------------------


def test_naming_an_unsweepable_target_deletes_it_without_argument() -> None:
    """The caller has read the report and decided. Re-deriving safety
    underneath them, or demanding a flag, is how a tool ends up arguing with
    the person using it -- and `-D` leaves the commits in the reflog."""
    result = plan_for((target("branch:wip", sweepable=False),), selectors=["wip"])
    assert isinstance(result, Plan)
    assert [t.name for t in result.targets] == ["wip"]


def test_naming_the_trunk_deletes_it_rather_than_refusing() -> None:
    """Protection was a verdict, and verdicts are gone. What stops this in
    practice is git: `branch -D` refuses a branch a worktree holds, and the
    trunk is checked out somewhere in every repository anyone works in."""
    result = plan_for((target("branch:main", sweepable=False),), selectors=["main"])
    assert isinstance(result, Plan)
    assert [t.name for t in result.targets] == ["main"]


def test_naming_a_remote_branch_deletes_it() -> None:
    """The sweep never takes a server ref; naming one is the way to say you
    mean it, and no further flag is asked for."""
    targets = (target("remote:origin/merged", kind=TargetKind.REMOTE_BRANCH, sweepable=False),)
    result = plan_for(targets, selectors=["origin/merged"])
    assert isinstance(result, Plan)
    assert [t.name for t in result.targets] == ["origin/merged"]


def test_a_named_remote_ref_is_bundled_before_it_goes() -> None:
    """The server keeps no reflog, so this is the one deletion left with no
    undo behind it."""
    targets = (target("remote:origin/merged", kind=TargetKind.REMOTE_BRANCH, sweepable=False),)
    result = plan_for(targets, selectors=["origin/merged"])
    assert isinstance(result, Plan)
    assert result.salvage_dir == "/salvage"


def test_a_plan_of_local_targets_needs_no_salvage_directory() -> None:
    """`branch -D` leaves the commits in the reflog, and a worktree is removed
    by git, which refuses while the tree holds anything uncommitted."""
    result = plan_for((target("branch:merged"),))
    assert isinstance(result, Plan)
    assert result.salvage_dir is None


# -- the directory the run is standing in ------------------------------------


def test_naming_the_invoking_worktree_is_refused_with_its_path() -> None:
    """Removing it deletes the process's own working directory, and every git
    call after that fails against a path that is no longer there -- failures
    that read as unrelated problems."""
    targets = (target("worktree:/repo", kind=TargetKind.WORKTREE, sweepable=False),)

    result = plan_for(targets, selectors=["worktree:/repo"])

    assert isinstance(result, Refusal)
    assert result.code == "E_INVOKING_WORKTREE"
    assert "/repo" in result.message
    assert [t.name for t in result.blocked] == ["/repo"]


def test_a_named_deletion_still_works_without_a_known_trunk() -> None:
    """A repository that has simply never published origin/HEAD is still
    cleanable. The unverified trunk stops the unattended sweep and is reported
    on every row; it is not a bar to deleting a branch the caller named."""
    survey = make_survey(default_branch="main", default_branch_known=False)

    result = plan_for(
        (target("branch:feat/x", sweepable=False),), survey=survey, selectors=["feat/x"]
    )

    assert isinstance(result, Plan)
    assert [t.name for t in result.targets] == ["feat/x"]


def test_another_worktree_is_not_mistaken_for_the_invoking_one() -> None:
    targets = (target("worktree:/repo/wt", kind=TargetKind.WORKTREE, sweepable=False),)
    result = plan_for(targets, selectors=["worktree:/repo/wt"])
    assert isinstance(result, Plan)


# -- selector resolution -----------------------------------------------------


def test_a_selector_matching_nothing_is_a_job_already_done() -> None:
    """The caller asked for that thing to be gone. It is gone. Refusing there
    reports a completed job as a failure, and an agent told it failed retries,
    reaches for raw git, or escalates -- all worse than the no-op it should
    have been handed."""
    result = plan_for((target("branch:x"),), selectors=["nope"])
    assert isinstance(result, Plan)
    assert result.targets == ()
    assert [a.selector for a in result.absent] == ["nope"]


def test_a_selector_matching_nothing_states_both_readings() -> None:
    """Nothing here can tell a branch deleted a minute ago from a name with a
    letter wrong -- the repository answers identically -- so the note commits
    to neither and points at the list that would settle it."""
    result = plan_for((target("branch:x"),), selectors=["nope"])
    assert isinstance(result, Plan)
    note = result.absent[0].note
    assert "already gone" in note
    assert "the name is wrong" in note
    assert "--report" in note


def test_one_absent_name_does_not_abort_the_names_beside_it() -> None:
    """This is the whole cost of the old refusal. Selector refusals are
    plan-level, so a single name that had already been dealt with stopped every
    other deletion the caller asked for in the same breath."""
    targets = (target("branch:x"), target("branch:y"))
    result = plan_for(targets, selectors=["x", "gone-already", "y"])
    assert isinstance(result, Plan)
    assert [t.id for t in result.targets] == ["branch:x", "branch:y"]
    assert [a.selector for a in result.absent] == ["gone-already"]


def test_a_miss_is_not_absence_when_no_ref_could_be_read() -> None:
    """`branches` is empty here because `for-each-ref` failed, not because the
    repository has none -- and the list alone cannot tell those apart. Calling
    it absence would tell a caller their branch is gone while it sits
    untouched, which is the one thing this tool must never say."""
    survey = make_survey(branches_known=False)

    result = plan_for((), survey=survey, selectors=["feat/x"])

    assert isinstance(result, Refusal)
    assert result.code == "E_SURVEY_INCOMPLETE"
    assert "feat/x" in result.message
    assert result.remedy


def test_a_ref_this_tool_declines_to_offer_is_not_reported_as_gone() -> None:
    """The server's copy of the trunk exists and is deliberately kept out of
    the target list. "Nothing matched" is therefore true and "it is already
    gone" is false, and only the second is a thing to tell somebody."""
    survey = make_survey(
        not_offered=(NotOffered(name="origin/main", reason="the server's copy of the trunk"),)
    )

    result = plan_for((target("branch:x"),), survey=survey, selectors=["origin/main"])

    assert isinstance(result, Refusal)
    assert result.code == "E_NOT_A_TARGET"
    assert "origin/main" in result.message
    assert "the server's copy of the trunk" in result.message


def test_the_local_trunk_is_not_confused_with_the_servers_copy_of_it() -> None:
    """A short-name fallback in the not-offered lookup would match `main`
    against the recorded `origin/main` and refuse to delete a different ref
    that is a legal thing to name."""
    survey = make_survey(
        not_offered=(NotOffered(name="origin/main", reason="the server's copy of the trunk"),)
    )

    result = plan_for((target("branch:main", sweepable=False),), survey=survey, selectors=["main"])

    assert isinstance(result, Plan)
    assert [t.name for t in result.targets] == ["main"]


def test_ambiguous_bare_name_is_refused_with_the_candidates() -> None:
    """`feat/x` names both the local branch and origin's copy. Guessing which
    one the caller meant is how the wrong ref gets deleted."""
    targets = (
        target("branch:feat/x"),
        target("remote:origin/feat/x", kind=TargetKind.REMOTE_BRANCH),
    )
    result = plan_for(targets, selectors=["feat/x"])
    assert isinstance(result, Refusal)
    assert result.code == "E_AMBIGUOUS_TARGET"
    assert len(result.blocked) == 2


def test_exact_id_disambiguates() -> None:
    targets = (
        target("branch:feat/x"),
        target("remote:origin/feat/x", kind=TargetKind.REMOTE_BRANCH),
    )
    result = plan_for(targets, selectors=["branch:feat/x"])
    assert isinstance(result, Plan)
    assert [t.id for t in result.targets] == ["branch:feat/x"]


def test_worktree_selectable_by_basename() -> None:
    targets = (target("worktree:/repo/wt/feature", kind=TargetKind.WORKTREE),)
    result = plan_for(targets, selectors=["feature"])
    assert isinstance(result, Plan)
    assert [t.id for t in result.targets] == ["worktree:/repo/wt/feature"]


def test_repeated_selector_is_not_planned_twice() -> None:
    targets = (target("branch:x"),)
    result = plan_for(targets, selectors=["x", "branch:x"])
    assert isinstance(result, Plan)
    assert len(result.targets) == 1


def test_resolve_selectors_returns_targets_in_request_order() -> None:
    targets = (target("branch:a"), target("branch:b"))
    resolved, absent, refusal = resolve_selectors(["b", "a"], targets, make_survey())
    assert refusal is None
    assert absent == []
    assert [t.name for t in resolved] == ["b", "a"]


def test_ambiguity_still_refuses_and_carries_nothing_forward() -> None:
    """A miss is a job done; ambiguity is a question. Two real things match and
    picking one destroys the other, so this is the refusal that stays -- and it
    resolves no selector beside it, because the caller is about to re-issue the
    whole command with a precise name."""
    targets = (
        target("branch:feat/x"),
        target("remote:origin/feat/x", kind=TargetKind.REMOTE_BRANCH),
        target("branch:other"),
    )
    resolved, absent, refusal = resolve_selectors(
        ["other", "feat/x", "nope"], targets, make_survey()
    )
    assert refusal is not None
    assert refusal.code == "E_AMBIGUOUS_TARGET"
    assert resolved == []
    assert absent == []


# -- worktree occupancy ------------------------------------------------------


def _occupied_survey():  # type: ignore[no-untyped-def]
    return make_survey(branches=(make_branch("held", checked_out_at="/repo/wt"),))


def test_named_occupied_branch_is_refused() -> None:
    """Not a safety judgement -- git is about to reject this outright, and
    saying so names the worktree that has to go first."""
    result = plan_for((target("branch:held"),), survey=_occupied_survey(), selectors=["held"])
    assert isinstance(result, Refusal)
    assert result.code == "E_BRANCH_IN_USE"


def test_automatic_sweep_skips_an_occupied_branch_instead_of_refusing() -> None:
    """One occupied branch must not block cleaning everything else."""
    targets = (target("branch:held"), target("branch:free"))
    result = plan_for(targets, survey=_occupied_survey())
    assert isinstance(result, Plan)
    assert [t.name for t in result.targets] == ["free"]


def test_a_skipped_target_is_reported_never_silently_dropped() -> None:
    result = plan_for((target("branch:held"),), survey=_occupied_survey())
    assert isinstance(result, Plan)
    assert [s.name for s in result.skipped] == ["held"]
    assert "/repo/wt" in result.skipped[0].reason


def test_occupancy_resolves_when_the_worktree_is_also_being_removed() -> None:
    targets = (
        target("worktree:/repo/wt", kind=TargetKind.WORKTREE),
        target("branch:held"),
    )
    result = plan_for(targets, survey=_occupied_survey())
    assert isinstance(result, Plan)
    assert [t.name for t in result.targets] == ["/repo/wt", "held"]


# -- ordering ----------------------------------------------------------------


def test_plan_orders_worktrees_then_local_then_remote() -> None:
    targets = (
        target("remote:origin/z", kind=TargetKind.REMOTE_BRANCH),
        target("branch:b"),
        target("worktree:/repo/w", kind=TargetKind.WORKTREE),
    )
    result = plan_for(targets, selectors=["remote:origin/z", "branch:b", "worktree:/repo/w"])
    assert isinstance(result, Plan)
    assert [t.kind.value for t in result.targets] == ["worktree", "branch", "remote_branch"]
