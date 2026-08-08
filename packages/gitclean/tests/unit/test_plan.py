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
) -> Plan:
    # Always a plan. An objection belongs to the selector it is about and rides
    # in `Plan.refused`, so there is no return value that stands in for the
    # whole run having stopped.
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

    assert result.targets == ()
    [refusal] = result.refused
    assert refusal.code == "E_INVOKING_WORKTREE"
    assert "/repo" in refusal.message
    assert [t.name for t in refusal.blocked] == ["/repo"]


def test_the_invoking_worktree_is_refused_without_stopping_the_one_beside_it() -> None:
    """The objection is about one directory: this process is standing in it.
    It says nothing about another worktree the same command named, which is
    somewhere else entirely and still goes -- and an agent cleaning up several
    trees at once is precisely the caller who names the one it is running in
    by accident."""
    here = target("worktree:/repo", kind=TargetKind.WORKTREE, sweepable=False)
    elsewhere = target("worktree:/repo/wt", kind=TargetKind.WORKTREE, sweepable=False)

    result = plan_for((here, elsewhere), selectors=["worktree:/repo", "worktree:/repo/wt"])

    assert [t.id for t in result.targets] == ["worktree:/repo/wt"]
    [refusal] = result.refused
    assert refusal.code == "E_INVOKING_WORKTREE"
    assert "/repo" in refusal.message
    assert [t.id for t in refusal.blocked] == ["worktree:/repo"]


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
    """A worktree *under* the invoking one is still a different directory. The
    comparison is between whole paths, and a prefix test would refuse every
    tree a repository keeps beside its checkout."""
    targets = (target("worktree:/repo/wt", kind=TargetKind.WORKTREE, sweepable=False),)
    result = plan_for(targets, selectors=["worktree:/repo/wt"])
    assert [t.id for t in result.targets] == ["worktree:/repo/wt"]
    assert result.refused == ()


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
    """Selector refusals are plan-level, so aborting the run over one of them
    would let a single name already dealt with stop every other deletion the
    caller asked for in the same breath."""
    targets = (target("branch:x"), target("branch:y"))
    result = plan_for(targets, selectors=["x", "gone-already", "y"])
    assert isinstance(result, Plan)
    assert [t.id for t in result.targets] == ["branch:x", "branch:y"]
    assert [a.selector for a in result.absent] == ["gone-already"]


def test_a_refused_name_takes_only_itself_out_of_the_run() -> None:
    """A whole-run refusal costs everything beside it. One name this tool will
    not act on would stop every other deletion asked for in the same breath,
    and the only way forward would be a re-run with the offender removed -- a
    round trip spent teaching the tool something it has already worked out.

    A refusal is about the selector it names. What resolved beside it is still
    the caller's to have, and the run reports both."""
    survey = make_survey(
        not_offered=(NotOffered(name="origin/main", reason="the server's copy of the trunk"),)
    )
    targets = (target("branch:x"), target("branch:y"))

    result = plan_for(targets, survey=survey, selectors=["x", "origin/main", "y"])

    assert [t.id for t in result.targets] == ["branch:x", "branch:y"]
    assert [r.code for r in result.refused] == ["E_NOT_A_TARGET"]


def test_refusals_raised_while_resolving_keep_the_order_their_selectors_had() -> None:
    """Reading order is the order a caller can map back onto what they typed,
    so a list assembled by code, or by whichever target happened to be surveyed
    first, leaves somebody who named six things pairing refusals up by hand.

    Scoped to resolution deliberately. The two checks made of the selection as
    a whole -- the invoking worktree, and branches a worktree still holds --
    are appended after these, and the second is one refusal covering however
    many branches were occupied, so it has no single position among the
    selectors to hold. Claiming one flat selector order would be claiming
    something the shape of that refusal cannot deliver; `Plan.refused` says so.

    Asserted both ways round, because a single ordering is also what a fixed
    order of codes would produce."""
    survey = make_survey(
        not_offered=(NotOffered(name="origin/main", reason="the server's copy of the trunk"),)
    )
    targets = (target("remote:origin/feat/x", kind=TargetKind.REMOTE_BRANCH, sweepable=False),)

    result = plan_for(targets, survey=survey, selectors=["origin/main", "feat/x"])
    assert [r.code for r in result.refused] == ["E_NOT_A_TARGET", "E_BARE_NAME_IS_SERVER_REF"]

    swapped = plan_for(targets, survey=survey, selectors=["feat/x", "origin/main"])
    assert [r.code for r in swapped.refused] == ["E_BARE_NAME_IS_SERVER_REF", "E_NOT_A_TARGET"]


def test_a_miss_is_not_absence_when_no_ref_could_be_read() -> None:
    """`branches` is empty here because `for-each-ref` failed, not because the
    repository has none -- and the list alone cannot tell those apart. Calling
    it absence would tell a caller their branch is gone while it sits
    untouched, which is the one thing this tool must never say."""
    survey = make_survey(branches_known=False)

    result = plan_for((), survey=survey, selectors=["feat/x"])

    assert result.absent == ()
    [refusal] = result.refused
    assert refusal.code == "E_SURVEY_INCOMPLETE"
    assert "feat/x" in refusal.message
    assert refusal.remedy


def test_a_worktree_miss_is_not_absence_when_no_worktree_could_be_listed() -> None:
    """The same defect as the ref read, on the other listing. `worktrees` is
    empty because `worktree list` failed, and a repository whose trees could
    not be described has not been shown to lack the one that was named."""
    survey = make_survey(worktrees_known=False)

    result = plan_for((), survey=survey, selectors=["worktree:/repo/wt"])

    assert result.absent == ()
    [refusal] = result.refused
    assert refusal.code == "E_SURVEY_INCOMPLETE"
    assert "no worktree could be listed" in refusal.message


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

    assert result.absent == ()
    [refusal] = result.refused
    assert refusal.code == "E_SURVEY_INCOMPLETE"
    assert "1 ref row(s) went unparsed" in refusal.message


def test_a_dropped_worktree_block_is_the_same_hole_on_the_other_listing() -> None:
    survey = make_survey(worktrees_known=True, dropped_worktrees=2)

    result = plan_for((), survey=survey, selectors=["worktree:/repo/wt"])

    assert result.absent == ()
    [refusal] = result.refused
    assert refusal.code == "E_SURVEY_INCOMPLETE"
    assert "2 worktree block(s) went unparsed" in refusal.message


def test_a_dropped_block_stops_a_match_meaning_the_only_match() -> None:
    """One match is measured; the only match is a further claim about every row
    the listing was supposed to have described, and a block nobody could parse
    is a row that went unrecorded. It may have been a second worktree wearing
    this name, and removing the wrong one has no undo."""
    survey = make_survey(worktrees_known=True, dropped_worktrees=1)
    targets = (target("worktree:/repo/wt", kind=TargetKind.WORKTREE),)

    result = plan_for(targets, survey=survey, selectors=["worktree:/repo/wt"])

    assert result.targets == ()
    [refusal] = result.refused
    assert refusal.code == "E_SURVEY_INCOMPLETE"
    assert [t.id for t in refusal.blocked] == ["worktree:/repo/wt"]
    assert "1 worktree block(s) went unparsed" in refusal.message


def test_a_dropped_block_does_not_stop_a_branch_that_matches() -> None:
    """The counts are read per listing on the match path exactly as they are on
    the miss path. A `branch:` names a local ref, and no worktree block -- lost
    or listed -- can be a second thing wearing that name."""
    survey = make_survey(dropped_worktrees=1)
    targets = (target("branch:feat/x"),)

    result = plan_for(targets, survey=survey, selectors=["branch:feat/x"])

    assert result.refused == ()
    assert [t.name for t in result.targets] == ["feat/x"]


def test_a_dropped_ref_row_stops_a_branch_match_the_same_way() -> None:
    """The other listing, and the one no git shipping today can trigger: the
    fields are separated by `\\x1f` and the newline, and `git check-ref-format`
    bars both from a refname. Covered because the rule is about a row that went
    unrecorded rather than about which listing lost it, and because that
    unreachability is a fact about the ref format as it stands."""
    survey = make_survey(dropped_refs=1)
    targets = (target("branch:feat/x"),)

    result = plan_for(targets, survey=survey, selectors=["branch:feat/x"])

    assert result.targets == ()
    [refusal] = result.refused
    assert refusal.code == "E_SURVEY_INCOMPLETE"
    assert "1 ref row(s) went unparsed" in refusal.message


def test_an_unframed_listing_does_not_stop_a_match() -> None:
    """The trigger is a proven loss, not an unproven completeness, and these are
    different claims. `worktrees_framed` is false on every git too old to offer
    NUL framing, whether or not a path was truncated -- refusing a match on it
    would refuse every named cleanup on those versions in exchange for nothing
    anybody measured. It keeps withholding the conclusion it does undermine, on
    the miss path, and leaves a match alone."""
    survey = make_survey(worktrees_framed=False, dropped_worktrees=0)
    targets = (target("worktree:/repo/wt", kind=TargetKind.WORKTREE),)

    result = plan_for(targets, survey=survey, selectors=["worktree:/repo/wt"])

    assert result.refused == ()
    assert [t.name for t in result.targets] == ["/repo/wt"]


def test_a_match_refused_over_a_dropped_block_does_not_spend_the_other_names() -> None:
    """A refusal is about the selector it names. The caller asked for two
    things, one of them cannot be answered for, and the other is still theirs to
    have -- an unrelated name paying for it is the round trip this run exists
    not to cost."""
    survey = make_survey(dropped_worktrees=1)
    targets = (
        target("worktree:/repo/wt", kind=TargetKind.WORKTREE),
        target("branch:feat/x"),
    )

    result = plan_for(targets, survey=survey, selectors=["worktree:/repo/wt", "branch:feat/x"])

    assert [r.code for r in result.refused] == ["E_SURVEY_INCOMPLETE"]
    assert [t.name for t in result.targets] == ["feat/x"]


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

    assert result.absent == ()
    [refusal] = result.refused
    assert refusal.code == "E_SURVEY_INCOMPLETE"
    assert "no ref could be read" in refusal.message


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
    halves apart is what failed. `feat/x` is one of the two ways
    `origin/feat/x` may split, so it is a name this ref may answer to, and the
    ref is sitting right there.

    Had the split succeeded, this same miss would still refuse -- a bare name
    does not select a server ref -- but it would refuse by quoting the full
    spelling to use instead. Here that spelling is exactly what nobody could
    work out, so the refusal reports the unanswered question rather than a
    remedy it cannot name. Either way the one answer that stays unavailable is
    absence."""
    survey = make_survey(unsplit_refs=1, not_offered=(_UNSPLIT,))

    result = plan_for((target("branch:x"),), survey=survey, selectors=["feat/x"])

    assert result.absent == ()
    [refusal] = result.refused
    assert refusal.code == "E_SURVEY_INCOMPLETE"
    assert "could not be split" in refusal.message


def test_a_failed_split_cannot_change_what_a_bare_name_deletes() -> None:
    """An unanswered probe must never *widen* what a run deletes, and that is
    true by construction here rather than by a refusal.

    A bare alias on a server ref is what would put it at risk. With the remote
    list read, `refs/remotes/origin/feat/x` would be a target whose bare alias
    is `feat/x`, so the name would match two things and be refused as ambiguous;
    with the read failed, that ref never becomes a target and the same name
    matches exactly one. The number of things a name means would then move with
    a probe that measured nothing about the repository.

    A bare name does not reach a server ref under either reading, so the ref
    never joins the match and the local branch is the only thing `feat/x` can
    mean. The two fixtures below agree, and nothing is lost, because the
    server's copy is unreachable without its full spelling either way."""
    both_read = plan_for(
        (
            target("branch:feat/x"),
            target("remote:origin/feat/x", kind=TargetKind.REMOTE_BRANCH),
        ),
        selectors=["feat/x"],
    )
    assert [t.id for t in both_read.targets] == ["branch:feat/x"]
    assert both_read.refused == ()

    split_failed = plan_for(
        (target("branch:feat/x"),),
        survey=make_survey(unsplit_refs=1, not_offered=(_UNSPLIT,)),
        selectors=["feat/x"],
    )
    assert [t.id for t in split_failed.targets] == ["branch:feat/x"]
    assert split_failed.refused == ()


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

    assert result.absent == ()
    [refusal] = result.refused
    assert refusal.code == "E_NOT_A_TARGET"
    assert "origin/main" in refusal.message
    assert "the server's copy of the trunk" in refusal.message


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


# -- a bare name is local; a server ref is spelled out -----------------------


def test_a_bare_name_takes_the_local_branch_and_not_the_servers_copy_of_it() -> None:
    """The commonest cleanup there is: the branch whose work just merged, named
    the way a person says it. In any ordinary repository the server's copy
    wears that same bare name, so offering the spelling to both made the
    routine case ambiguous -- naming the branch that had just been merged was
    answered with a refusal and a demand for an `id`.

    Nothing about the server's copy is decided here. It is neither deleted nor
    an obstacle: it goes only when it is spelled out in full, and that rule is
    what makes the bare name unambiguous again."""
    targets = (
        target("branch:docs/thing"),
        target("remote:origin/docs/thing", kind=TargetKind.REMOTE_BRANCH),
    )

    result = plan_for(targets, selectors=["docs/thing"])

    assert [t.id for t in result.targets] == ["branch:docs/thing"]
    assert result.refused == ()
    # No server ref entered the plan, so there is nothing here that a bundle
    # would be the only undo for.
    assert result.salvage_dir is None


def test_a_bare_name_only_a_server_ref_wears_is_refused_rather_than_called_gone() -> None:
    """Nothing local answers to it, and ordinarily that is a job already done.
    Not here: the thing the caller named is on the server under exactly that
    name, so "already gone" would be false about the only ref that bears it,
    and a caller told that believes a deletion happened.

    The refusal is also what keeps the server's copy safe. It is the one
    deletion with no reflog behind it, so it goes only when it is named in
    full, and the remedy quotes the spelling that would do it."""
    server = target("remote:origin/feat/x", kind=TargetKind.REMOTE_BRANCH, sweepable=False)

    result = plan_for((server, target("branch:other")), selectors=["feat/x"])

    assert result.targets == ()
    assert result.absent == ()
    [refusal] = result.refused
    assert refusal.code == "E_BARE_NAME_IS_SERVER_REF"
    assert [t.id for t in refusal.blocked] == ["remote:origin/feat/x"]
    assert "origin/feat/x" in refusal.remedy


def test_every_server_copy_of_a_bare_name_is_named_not_just_the_first() -> None:
    """A fork carries the same branch name on two remotes as a matter of
    course, and a caller working in one has no reason to be thinking about the
    other. Naming one copy would describe half of what is there, and a reader
    handed half reads it as the whole -- so they delete the one they were told
    about and leave a ref they meant to be rid of, believing it gone.

    The remedy offers them as a choice and not as a list to paste. A remedy is
    read as something to type back, and `origin/feat/x, upstream/feat/x` typed
    back is one argument with a comma in it, which names nothing -- so a caller
    following the advice exactly would be told their own remedy matched
    nothing. Two remotes carrying a name is also not two copies anybody meant
    to be rid of."""
    survey = make_survey(remotes=("origin", "upstream"))
    targets = (
        target("remote:origin/feat/x", kind=TargetKind.REMOTE_BRANCH, sweepable=False),
        target("remote:upstream/feat/x", kind=TargetKind.REMOTE_BRANCH, remote="upstream"),
    )

    result = plan_for(targets, survey=survey, selectors=["feat/x"])

    assert result.targets == ()
    [refusal] = result.refused
    assert refusal.code == "E_BARE_NAME_IS_SERVER_REF"
    assert [t.id for t in refusal.blocked] == [
        "remote:origin/feat/x",
        "remote:upstream/feat/x",
    ]
    assert "origin/feat/x or upstream/feat/x" in refusal.remedy
    assert "origin/feat/x, upstream/feat/x" not in refusal.remedy
    # The message is a statement of what is there, so it stays a list; only the
    # remedy is read as something to type back.
    assert "origin/feat/x, upstream/feat/x" in refusal.message


def test_the_full_name_still_selects_the_servers_copy_past_a_local_branch() -> None:
    """The remedy has to reach the ref or the refusal above is a dead end --
    and it has to reach it in a repository where the local branch of that name
    is still present, which is the only shape the refusal ever appears in."""
    targets = (
        target("branch:feat/x"),
        target("remote:origin/feat/x", kind=TargetKind.REMOTE_BRANCH, sweepable=False),
    )

    result = plan_for(targets, selectors=["origin/feat/x"])

    assert [t.id for t in result.targets] == ["remote:origin/feat/x"]
    assert result.refused == ()


def test_the_id_still_selects_the_servers_copy_too() -> None:
    """The other spelling that names one ref and no other. `--report` prints
    this one on every row, so it is what an agent copies out of the report."""
    targets = (
        target("branch:feat/x"),
        target("remote:origin/feat/x", kind=TargetKind.REMOTE_BRANCH, sweepable=False),
    )

    result = plan_for(targets, selectors=["remote:origin/feat/x"])

    assert [t.id for t in result.targets] == ["remote:origin/feat/x"]
    assert result.refused == ()


def test_a_branch_selector_is_not_diverted_to_a_server_ref_of_that_bare_name() -> None:
    """`branch:` says a local ref outright. The server's copy is not something
    that selector could have meant however it is spelled, so the miss is a
    plain miss -- and the caller is told the job is done rather than handed a
    refusal about a ref they were not talking about."""
    server = target("remote:origin/feat/x", kind=TargetKind.REMOTE_BRANCH, sweepable=False)

    result = plan_for((server,), selectors=["branch:feat/x"])

    assert result.refused == ()
    assert [a.selector for a in result.absent] == ["branch:feat/x"]


def test_ambiguous_bare_name_is_refused_with_the_candidates() -> None:
    """A worktree answers to its basename and a branch to its name, and neither
    of those is derived from the other -- so `feat` can still mean two things
    at once, and nothing but the caller knows which. Guessing is how the wrong
    one gets deleted, so the refusal names both and asks for an `id`.

    A local branch beside the server's copy of it is not this case: a bare name
    does not reach a server ref, so that pair does not collide. What is left is
    a collision between the two listings."""
    targets = (
        target("branch:feat"),
        target("worktree:/repo/wt/feat", kind=TargetKind.WORKTREE),
    )
    result = plan_for(targets, selectors=["feat"])
    assert result.targets == ()
    [refusal] = result.refused
    assert refusal.code == "E_AMBIGUOUS_TARGET"
    assert {t.id for t in refusal.blocked} == {"branch:feat", "worktree:/repo/wt/feat"}


def test_exact_id_disambiguates() -> None:
    targets = (
        target("branch:feat/x"),
        target("remote:origin/feat/x", kind=TargetKind.REMOTE_BRANCH),
    )
    result = plan_for(targets, selectors=["branch:feat/x"])
    assert isinstance(result, Plan)
    assert [t.id for t in result.targets] == ["branch:feat/x"]


def test_the_bare_name_a_server_ref_answers_to_is_the_one_the_remote_knows() -> None:
    """A bare name does not *select* a server ref, but it is still matched
    against one to tell a caller the ref is there -- and it has to be matched
    against the right name. The remote knows `team/origin/feat/x` as `feat/x`,
    so that is the name the refusal answers to and the full spelling is what its
    remedy quotes.

    Dropping everything before the first slash would answer to `origin/feat/x`
    instead: a name nothing in this repository has. Reporting that one as
    already gone is a claim about a ref that does not exist, and it would arrive
    while the ref the caller was reaching for sat untouched."""
    targets = (
        target(
            "remote:team/origin/feat/x",
            kind=TargetKind.REMOTE_BRANCH,
            remote="team/origin",
        ),
    )

    [refusal] = plan_for(targets, selectors=["feat/x"]).refused
    assert refusal.code == "E_BARE_NAME_IS_SERVER_REF"
    assert "team/origin/feat/x" in refusal.remedy

    result = plan_for(targets, selectors=["origin/feat/x"])
    assert result.targets == ()
    assert result.refused == ()
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
    resolved, absent, refusals = resolve_selectors(["b", "a"], targets, make_survey())
    assert refusals == []
    assert absent == []
    assert [t.name for t in resolved] == ["b", "a"]


def test_ambiguity_refuses_that_name_and_nothing_else() -> None:
    """A miss is a job done; ambiguity is a question. Two real things match and
    picking one destroys the other, so this is the refusal that stays.

    What it does not do is take the rest of the command with it. The question
    is about one name -- the others were unambiguous, and the caller is going
    to re-issue only the offending one with an `id`. Discarding their resolved
    targets would make the re-run repeat every name that already worked, and a
    caller who edits that line under time pressure is the one who drops a name
    they meant to keep."""
    targets = (
        target("branch:feat"),
        target("worktree:/repo/wt/feat", kind=TargetKind.WORKTREE),
        target("branch:other"),
    )
    resolved, absent, refusals = resolve_selectors(
        ["other", "feat", "nope"], targets, make_survey()
    )
    assert [r.code for r in refusals] == ["E_AMBIGUOUS_TARGET"]
    assert [t.id for t in resolved] == ["branch:other"]
    # And the selector after the ambiguous one was still resolved, rather than
    # never reached: resolution does not stop at the first objection.
    assert [a.selector for a in absent] == ["nope"]


# -- worktree occupancy ------------------------------------------------------


def _occupied_survey():  # type: ignore[no-untyped-def]
    return make_survey(branches=(make_branch("held", checked_out_at="/repo/wt"),))


def test_a_named_occupied_branch_is_planned_and_left_to_git() -> None:
    """Naming it is the authorisation. git will not delete a branch a worktree
    still holds, and its refusal is taken at the moment of the deletion and
    names the worktree in its own words -- so the plan carries the target
    rather than an objection worked out from a survey taken earlier."""
    result = plan_for((target("branch:held"),), survey=_occupied_survey(), selectors=["held"])
    assert [t.id for t in result.targets] == ["branch:held"]
    assert result.skipped == ()
    assert result.refused == ()


def test_a_named_occupied_branch_does_not_hold_up_the_rest_of_the_command() -> None:
    """Whatever git makes of the occupied one, the other names in the same
    command were resolved and are planned. One branch a worktree holds is not a
    reason to do none of the work asked for."""
    result = plan_for(
        (target("branch:held"), target("branch:free")),
        survey=_occupied_survey(),
        selectors=["held", "free"],
    )

    assert sorted(t.id for t in result.targets) == ["branch:free", "branch:held"]
    assert result.skipped == ()
    assert result.refused == ()


def test_the_occupancy_check_reads_the_local_branch_not_a_server_ref_of_that_name() -> None:
    """`Branch.name` is the short name for a local ref and `<remote>/<ref>` for
    a server one, and the two collide: a local branch `origin/held` and origin's
    copy of `held` are both `origin/held`. A search that only compares names
    can answer with the server ref, whose `checked_out_at` is always None,
    and the branch its worktree still holds then reads as free -- so the sweep
    takes a branch git is about to refuse, and reports the refusal as a
    surprise rather than as the omission it planned.

    Which one an unfiltered search finds today is decided by git listing
    refs/heads before refs/remotes. That is not a rule this depends on, and
    building the survey the other way round is how the test says so."""
    survey = make_survey(
        branches=(
            make_branch("origin/held", is_remote=True, remote="origin", ref_name="held"),
            make_branch("origin/held", ref="refs/heads/origin/held", checked_out_at="/repo/wt"),
        )
    )

    result = plan_for((target("branch:origin/held"),), survey=survey)

    assert result.targets == ()
    assert [s.target_id for s in result.skipped] == ["branch:origin/held"]
    assert "/repo/wt" in result.skipped[0].reason


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


def test_a_bare_sweep_still_skips_an_occupied_branch_rather_than_refusing_it() -> None:
    """The line between the two modes, and it is the one thing splitting the
    refusal out per selector must not blur. Nobody named this branch, so no
    instruction was contradicted -- an unattended sweep that turned an occupied
    branch into a refusal would exit non-zero, and report a run as failed, on a
    repository where everything it was actually asked to do was done."""
    result = plan_for((target("branch:held"), target("branch:free")), survey=_occupied_survey())

    assert [t.id for t in result.targets] == ["branch:free"]
    assert [s.target_id for s in result.skipped] == ["branch:held"]
    assert result.refused == ()


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
