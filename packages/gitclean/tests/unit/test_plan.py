"""Tests for selection, refusal, and ordering."""

from __future__ import annotations

from conftest import make_branch, make_survey

from gitclean.model import (
    Counterpart,
    MergeEvidence,
    NotOffered,
    Plan,
    PullRequestOutcome,
    Refusal,
    Target,
    TargetKind,
)
from gitclean.plan import build_after_merge_plan, build_plan, resolve_selectors


def target(
    ident: str,
    *,
    kind: TargetKind = TargetKind.BRANCH,
    name: str | None = None,
    sweepable: bool = True,
    remote: str = "origin",
    pairing: tuple[Counterpart, ...] = (),
) -> Target:
    resolved = name if name is not None else ident.split(":", 1)[1]
    # The remote a server ref lives on, which only the survey can recover. Most
    # fixtures here are on `origin`, and the builder says so rather than leaving
    # the plan to work it out from a slash.
    on_remote = kind is TargetKind.REMOTE_BRANCH and resolved.startswith(f"{remote}/")
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
        remote=remote if on_remote else None,
        ref_name=resolved.removeprefix(f"{remote}/") if on_remote else None,
        pairing=pairing,
    )


def counterpart(relation: str, of: Target) -> Counterpart:
    """The relation a classified row carries, built from the row it points at.

    Taking the target rather than two strings is what stops a fixture
    describing a report that cannot exist: a counterpart naming a row carries
    that row's own id and name, and the two cannot drift apart here."""
    return Counterpart(relation=relation, name=of.name, id=of.id, known=True)


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


def test_a_worktree_miss_is_not_absence_when_no_worktree_could_be_listed() -> None:
    """The same defect as the ref read, on the other listing. `worktrees` is
    empty because `worktree list` failed, and a repository whose trees could
    not be described has not been shown to lack the one that was named."""
    survey = make_survey(worktrees_known=False)

    result = plan_for((), survey=survey, selectors=["worktree:/repo/wt"])

    assert isinstance(result, Refusal)
    assert result.code == "E_SURVEY_INCOMPLETE"
    assert "no worktree could be listed" in result.message


def test_a_failed_ref_read_does_not_block_naming_an_absent_worktree() -> None:
    """The commonest cleanup there is -- a worktree already removed, named
    after the fact -- and the worktree listing answered. Refusing it over a ref
    read that has nothing to do with this selector would take the tool's whole
    reason for accepting an absent name and give it back."""
    survey = make_survey(branches_known=False, worktrees_known=True)

    result = plan_for((), survey=survey, selectors=["worktree:/repo/wt"])

    assert isinstance(result, Plan)
    assert [a.selector for a in result.absent] == ["worktree:/repo/wt"]


def test_a_listing_that_ran_but_dropped_a_row_has_not_answered() -> None:
    """`branches_known` says the command exited 0, which is a smaller claim
    than describing everything it listed. A row nobody could parse is a ref
    whose existence went unrecorded, and that is the same hole as never having
    looked -- so it must not turn into "already gone"."""
    survey = make_survey(branches_known=True, dropped_refs=1)

    result = plan_for((), survey=survey, selectors=["branch:feat/x"])

    assert isinstance(result, Refusal)
    assert result.code == "E_SURVEY_INCOMPLETE"
    assert "1 ref row(s) went unparsed" in result.message


def test_a_dropped_worktree_block_is_the_same_hole_on_the_other_listing() -> None:
    survey = make_survey(worktrees_known=True, dropped_worktrees=2)

    result = plan_for((), survey=survey, selectors=["worktree:/repo/wt"])

    assert isinstance(result, Refusal)
    assert result.code == "E_SURVEY_INCOMPLETE"
    assert "2 worktree block(s) went unparsed" in result.message


def test_a_dropped_ref_row_does_not_block_naming_a_worktree() -> None:
    """The counts are read per listing, like the flags beside them. A ref row
    nobody could parse says nothing about the worktree listing."""
    survey = make_survey(dropped_refs=1)

    result = plan_for((), survey=survey, selectors=["worktree:/repo/wt"])

    assert isinstance(result, Plan)
    assert [a.selector for a in result.absent] == ["worktree:/repo/wt"]


def test_an_absolute_path_is_a_worktree_without_needing_the_prefix() -> None:
    """git will not create a ref whose short name begins with a slash, so an
    absolute path can only mean a worktree -- and the worktree listing is the
    only one that has to have answered for it."""
    survey = make_survey(branches_known=False, worktrees_known=True)

    result = plan_for((), survey=survey, selectors=["/repo/wt"])

    assert isinstance(result, Plan)
    assert [a.selector for a in result.absent] == ["/repo/wt"]


def test_a_bare_name_needs_both_listings_because_it_could_be_either() -> None:
    """Being unable to say which kind was meant is not a reason to trust
    whichever one happened to answer."""
    survey = make_survey(branches_known=False, worktrees_known=True)

    result = plan_for((), survey=survey, selectors=["ambiguous"])

    assert isinstance(result, Refusal)
    assert result.code == "E_SURVEY_INCOMPLETE"
    assert "no ref could be read" in result.message


_UNSPLIT = NotOffered(
    name="origin/feat/x",
    reason="the configured remote list could not be read, so which part of "
    "refs/remotes/origin/feat/x names a remote is unknown",
    unsplit=True,
)
"""What the survey records for a ref it could not split, and the whole of what
is known about it. The remote is `origin` and the branch `feat/x`, or the remote
is `origin/feat` and the branch `x` -- so both of those are names it may answer
to, and nothing here can say which."""


def test_a_ref_that_could_not_be_split_stops_a_miss_meaning_absence() -> None:
    """A server ref recorded only as `<remote>/<ref>`, because telling the two
    halves apart is what failed. Every other spelling of it -- including the
    bare one this tool offers for selecting a server ref -- matches nothing,
    and nothing is what a name that was never there matches too.

    `feat/x` is one of the two ways `origin/feat/x` may split, so it is a name
    this ref may answer to."""
    survey = make_survey(unsplit_refs=1, not_offered=(_UNSPLIT,))

    result = plan_for((target("branch:x"),), survey=survey, selectors=["feat/x"])

    assert isinstance(result, Refusal)
    assert result.code == "E_SURVEY_INCOMPLETE"
    assert "could not be split" in result.message


def test_a_match_does_not_settle_a_name_a_ref_nobody_split_may_also_answer_to() -> None:
    """The failed probe used to *widen* what a run would delete, which is the
    one thing an unanswered probe must never do.

    With the remote list read, `refs/remotes/origin/feat/x` becomes a target
    whose bare alias is `feat/x`, so `feat/x` matches two things and is refused
    as ambiguous. With the read failed, that ref never becomes a target at all
    -- so the same name matches exactly one thing and the local branch is
    deleted. The count of matches is not evidence while something that could
    have joined it went unnamed."""
    survey = make_survey(unsplit_refs=1, not_offered=(_UNSPLIT,))

    result = plan_for((target("branch:feat/x"),), survey=survey, selectors=["feat/x"])

    assert isinstance(result, Refusal)
    assert result.code == "E_AMBIGUOUS_TARGET"
    assert "origin/feat/x" in result.message
    assert "id" in result.remedy


def test_the_exact_id_still_resolves_past_a_ref_nobody_split() -> None:
    """The remedy has to work or the refusal is a dead end. An `id` says which
    kind is meant, and no server ref can answer to a `branch:` spelling however
    it splits."""
    survey = make_survey(unsplit_refs=1, not_offered=(_UNSPLIT,))

    result = plan_for((target("branch:feat/x"),), survey=survey, selectors=["branch:feat/x"])

    assert isinstance(result, Plan)
    assert [t.id for t in result.targets] == ["branch:feat/x"]


def test_a_name_no_splitting_of_that_ref_could_produce_is_unaffected() -> None:
    """The doubt is per-selector, and this is what that buys. `origin/feat/x`
    splits into `feat/x` or `x` and into nothing else, so a target called
    `other` cannot be the thing it collides with -- and a run-wide rule would
    refuse it anyway, which in a repository holding one stale tracking ref
    means refusing every name there is."""
    survey = make_survey(unsplit_refs=1, not_offered=(_UNSPLIT,))

    result = plan_for((target("branch:other"),), survey=survey, selectors=["other"])

    assert isinstance(result, Plan)
    assert [t.id for t in result.targets] == ["branch:other"]


def test_a_local_branch_selector_is_not_refused_over_a_server_ref() -> None:
    """`branch:` says a local branch outright, and local refs were read and
    split without trouble. Refusing this over a server ref nobody was talking
    about trades a false absence for a false refusal, which is not a trade --
    both are the tool answering a question it was not asked."""
    survey = make_survey(unsplit_refs=1)

    result = plan_for((target("branch:x"),), survey=survey, selectors=["branch:gone"])

    assert isinstance(result, Plan)
    assert [a.selector for a in result.absent] == ["branch:gone"]


def test_a_worktree_selector_is_not_refused_over_a_server_ref() -> None:
    """Same boundary from the other side: a path can only mean a worktree, and
    the worktree listing had nothing to do with splitting a ref."""
    survey = make_survey(unsplit_refs=1)

    result = plan_for((target("branch:x"),), survey=survey, selectors=["/repo/wt"])

    assert isinstance(result, Plan)
    assert [a.selector for a in result.absent] == ["/repo/wt"]


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


def test_a_server_refs_bare_alias_is_the_name_the_remote_knows() -> None:
    """The convenience spelling for `team/origin/feat/x` is `feat/x`, because
    that is what the server calls the branch. Dropping everything before the
    first slash offers `origin/feat/x` instead -- a name nothing in the
    repository has, handed to a caller as though it were theirs."""
    targets = (
        target(
            "remote:team/origin/feat/x",
            kind=TargetKind.REMOTE_BRANCH,
            remote="team/origin",
        ),
    )

    assert isinstance(plan_for(targets, selectors=["feat/x"]), Plan)
    result = plan_for(targets, selectors=["origin/feat/x"])
    assert isinstance(result, Plan)
    assert result.targets == ()
    assert [a.selector for a in result.absent] == ["origin/feat/x"]


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


def test_the_occupancy_check_reads_the_local_branch_not_a_server_ref_of_that_name() -> None:
    """`Branch.name` is the short name for a local ref and `<remote>/<ref>` for
    a server one, and the two collide: a local branch `origin/held` and origin's
    copy of `held` are both `origin/held`. A search that only compares names
    can answer with the server ref, whose `checked_out_at` is always None,
    and the branch its worktree still holds then reads as free.

    Which one an unfiltered search finds today is decided by git listing
    refs/heads before refs/remotes. That is not a rule this depends on, and
    building the survey the other way round is how the test says so."""
    survey = make_survey(
        branches=(
            make_branch("origin/held", is_remote=True, remote="origin", ref_name="held"),
            make_branch("origin/held", ref="refs/heads/origin/held", checked_out_at="/repo/wt"),
        )
    )

    result = plan_for(
        (target("branch:origin/held"),), survey=survey, selectors=["branch:origin/held"]
    )

    assert isinstance(result, Refusal)
    assert result.code == "E_BRANCH_IN_USE"
    assert "/repo/wt" in result.message


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


# -- after a merged pull request ---------------------------------------------


def _merged(number: int = 438, head_ref: str = "feat/shipped") -> PullRequestOutcome:
    return PullRequestOutcome(
        number=number, state="MERGED", head_ref=head_ref, merged_at="2026-08-01T00:00:00Z"
    )


def after_merge(
    targets: tuple[Target, ...],
    *,
    pull_request: PullRequestOutcome | str | None = None,
    survey=None,  # type: ignore[no-untyped-def]
) -> Plan | Refusal:
    return build_after_merge_plan(
        targets,
        survey if survey is not None else make_survey(),
        pull_request=pull_request if pull_request is not None else _merged(),
        dry_run=False,
    )


def _shipped_pair() -> tuple[Target, Target]:
    """A merged branch and the worktree holding it, pointing at each other.

    Built as a pair because that is how the survey reports them: the scope is
    reached by following the relation, so a fixture whose rows do not name each
    other is testing a report that never occurs."""
    worktree = target(
        "worktree:/repo/wt-shipped", kind=TargetKind.WORKTREE, name="/repo/wt-shipped"
    )
    branch = target("branch:feat/shipped", pairing=(counterpart("worktree", worktree),))
    return branch, worktree


def test_a_merged_pull_request_sweeps_its_branch_and_the_worktree_holding_it() -> None:
    """The round trip this mode exists to remove. Nothing is named and nothing
    is skipped: the scope is what the pull request produced, and both rows
    cleared the same checks a bare sweep applies."""
    branch, worktree = _shipped_pair()

    result = after_merge((branch, worktree, target("branch:someone-elses-work")))

    assert isinstance(result, Plan)
    assert [t.name for t in result.targets] == ["/repo/wt-shipped", "feat/shipped"]
    assert result.skipped == ()


def test_nothing_a_different_pull_request_produced_enters_the_scope() -> None:
    """The whole reason a bare sweep was not an option. An agent cleaning up
    after itself must take its own two rows and leave every other branch in the
    repository exactly where it is, however provably merged they are."""
    branch, worktree = _shipped_pair()
    others = (
        target("branch:someone-elses-work"),
        target("worktree:/repo/wt-theirs", kind=TargetKind.WORKTREE, name="/repo/wt-theirs"),
    )

    result = after_merge((branch, worktree, *others))

    assert isinstance(result, Plan)
    assert {t.name for t in result.targets} == {"/repo/wt-shipped", "feat/shipped"}


def test_a_pull_request_that_closed_without_merging_is_not_a_deletion_authority() -> None:
    """Closing a pull request says somebody stopped wanting the change. It
    never says the commits landed anywhere else, and they did not."""
    branch, worktree = _shipped_pair()
    closed = PullRequestOutcome(number=438, state="CLOSED", head_ref="feat/shipped", merged_at=None)

    result = after_merge((branch, worktree), pull_request=closed)

    assert isinstance(result, Refusal)
    assert result.code == "E_PR_NOT_MERGED"
    assert "CLOSED" in result.message


def test_an_open_pull_request_is_not_a_deletion_authority_either() -> None:
    """The failure that would hurt most: deleting the branch of a pull request
    still under review takes the only copy of work nobody has merged."""
    branch, worktree = _shipped_pair()
    still_open = PullRequestOutcome(
        number=438, state="OPEN", head_ref="feat/shipped", merged_at=None
    )

    result = after_merge((branch, worktree), pull_request=still_open)

    assert isinstance(result, Refusal)
    assert result.code == "E_PR_NOT_MERGED"


def test_a_pull_request_read_that_did_not_answer_authorises_nothing() -> None:
    """The authorising fact is the only thing this mode has that a sweep does
    not, so a read that failed leaves it with no authority at all -- not a
    degraded one that falls back to sweeping."""
    branch, worktree = _shipped_pair()

    result = after_merge((branch, worktree), pull_request="gh is not on PATH")

    assert isinstance(result, Refusal)
    assert result.code == "E_PR_UNREADABLE"
    assert "gh is not on PATH" in result.message


def test_a_merge_stated_without_a_time_is_not_one_this_acts_on() -> None:
    """State and merge time are one fact stated twice, and a fact stated twice
    is established only when both statements agree."""
    branch, worktree = _shipped_pair()
    undated = PullRequestOutcome(
        number=438, state="MERGED", head_ref="feat/shipped", merged_at=None
    )

    result = after_merge((branch, worktree), pull_request=undated)

    assert isinstance(result, Refusal)
    assert result.code == "E_PR_UNREADABLE"


def test_the_servers_copy_is_reported_and_never_swept() -> None:
    """A merged pull request authorises deleting this repository's copy of the
    work. The server keeps no reflog, so its copy still goes only when named --
    and the row saying so is what stops a clean run reading as gone everywhere."""
    server = target("remote:origin/feat/shipped", kind=TargetKind.REMOTE_BRANCH)
    worktree = target(
        "worktree:/repo/wt-shipped", kind=TargetKind.WORKTREE, name="/repo/wt-shipped"
    )
    branch = target(
        "branch:feat/shipped",
        pairing=(counterpart("worktree", worktree), counterpart("upstream", server)),
    )

    result = after_merge((branch, worktree, server))

    assert isinstance(result, Plan)
    assert "remote:origin/feat/shipped" not in [t.id for t in result.targets]
    reported = {s.target_id: s.reason for s in result.skipped}
    assert "the copy on the server" in reported["remote:origin/feat/shipped"]


def test_a_branch_the_sweep_would_withhold_is_left_exactly_where_it_is() -> None:
    """The pull request describes the commit its head pointed at, not whatever
    the branch of that name holds now. So the six questions are still asked, and
    a branch that fails one is reported with the measurement that stopped it."""
    worktree = target(
        "worktree:/repo/wt-shipped", kind=TargetKind.WORKTREE, name="/repo/wt-shipped"
    )
    branch = target(
        "branch:feat/shipped", sweepable=False, pairing=(counterpart("worktree", worktree),)
    )

    result = after_merge((branch, worktree))

    assert isinstance(result, Plan)
    assert [t.name for t in result.targets] == ["/repo/wt-shipped"]
    reported = {s.target_id: s.reason for s in result.skipped}
    assert reported["branch:feat/shipped"] == branch.withheld


def test_an_occupied_branch_is_skipped_rather_than_stopping_the_run() -> None:
    """What a sweep does about occupancy, and this is a sweep. git refuses to
    delete a branch a worktree still holds, so the branch is skipped with the
    holder named and everything else in scope still goes."""
    held = target("branch:held", pairing=())
    survey = make_survey(branches=(make_branch("held", checked_out_at="/repo/elsewhere"),))

    result = after_merge((held,), pull_request=_merged(head_ref="held"), survey=survey)

    assert isinstance(result, Plan)
    assert result.targets == ()
    assert [s.target_id for s in result.skipped] == ["branch:held"]
    assert "/repo/elsewhere" in result.skipped[0].reason


def test_a_pull_request_whose_branch_is_already_gone_is_a_completed_job() -> None:
    """Routine rather than exceptional: the forge deletes the branch on merge,
    or the agent ran this a moment ago. Reporting a finished job as a failure is
    what sends a caller back to raw git."""
    result = after_merge((target("branch:something-else"),))

    assert isinstance(result, Plan)
    assert result.targets == ()
    assert result.skipped == ()
    assert [a.selector for a in result.absent] == ["feat/shipped"]


def test_a_pull_request_plan_never_carries_a_salvage_directory() -> None:
    """Salvage is retained only where no reflog exists, which is the server --
    and no server ref can enter this plan. A directory here would be a bundle
    nothing writes and a route nobody takes."""
    branch, worktree = _shipped_pair()

    result = after_merge((branch, worktree))

    assert isinstance(result, Plan)
    assert result.salvage_dir is None
