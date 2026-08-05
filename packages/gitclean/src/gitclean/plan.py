"""Pure: turns classified targets plus the caller's intent into a Plan or a Refusal.

A bare sweep takes exactly the targets classification marked ``sweepable`` and
nothing else. A named target is not re-adjudicated at all: naming it is the
authorisation, and re-deriving safety underneath the caller is how a tool ends
up arguing with the person using it. git's own refusals still stand where
nothing overrides them, and they carry better information than a re-derivation
would -- git knows what its working tree holds right now.

Between those two sits a merged pull request, and it is a sweep rather than a
naming. Nothing about it is authorised by somebody's judgement that a branch is
finished with: what authorises it is the mechanical fact that the pull request
merged, which a caller cannot assert and gh has to answer. So every check a
bare sweep applies is applied here too, unchanged -- the scope is narrowed to
the targets one pull request produced, and nothing else about the sweep moves.
That is the whole of the difference, and it is deliberate: a mode that both
narrowed the scope *and* relaxed the proof would be a naming wearing a sweep's
clothes.

So the refusals left here are few, and each answers something the caller could
not have answered themselves: a name matching two things, a branch git will
reject because a worktree still holds it, and the directory this process is
standing in.

None of them stops the rest. A refusal is about the selector it names, so what
resolved cleanly is still planned and still deleted, and the refusals ride
along beside it -- the run reports both and exits non-zero. Aborting the whole
selection over one bad name was the older behaviour and it was the worse one:
a name that had already been dealt with stopped every other deletion the caller
asked for, and the only way out was to re-run with the offender removed, which
is a round trip spent teaching the tool something it had already worked out.

A name matching *nothing* is not a refusal at all. The caller asked for that
thing to be gone; it is gone, and reporting a finished job as a failure is what
sends somebody back to raw git.

That is narrower than "a miss is fine", though, because a miss has four causes
and only one of them is absence. The list can also be empty because the ref
read failed, or missing a name because this tool does not offer that ref as a
target, or missing it because the only thing wearing that name is a copy on a
server -- which a bare name deliberately no longer reaches. In all three the
branch is sitting right there. Those refuse, and the codes say which, because
the alternative is telling somebody their branch is gone while it is not.
Concluding absence from a list that was never able to answer is the same
mistake as reading an unanswered probe as a clean working tree.
"""

from __future__ import annotations

from pathlib import Path

from gitclean.model import (
    Absent,
    NotOffered,
    Plan,
    PullRequestOutcome,
    Refusal,
    Skipped,
    Survey,
    Target,
    TargetKind,
)


def _selector_candidates(target: Target) -> set[str]:
    """Every string a caller may reasonably use to name this target.

    A server ref answers to its full `<remote>/<ref>` spelling and its
    `remote:` id, and to nothing shorter. The bare name a remote knows a branch
    by is, in any ordinary repository, the very string the local branch goes by
    -- so accepting it here made the commonest cleanup there is, deleting the
    branch whose work just merged, ambiguous between a local ref and a copy on
    a server that this tool declines to delete unnamed anyway. Requiring the
    full spelling contradicts nothing the tool offers: a bare name only ever
    reached a server ref where no local branch shared it, and where one did,
    the run refused rather than choosing."""
    names = {target.id, target.name}
    if target.kind is TargetKind.WORKTREE:
        names.add(Path(target.name).name)
    return names


def _bare_server_refs(selector: str, targets: tuple[Target, ...]) -> list[Target]:
    """Every server ref this selector names in each way except the one that counts.

    Consulted only once nothing matched, and it is what keeps that miss from
    being read as absence. The refs are right there; what is absent is a local
    target wearing the name. "Already gone" would be false about the only
    things that bear it, and staying silent would leave a caller believing a
    deletion they asked for had happened.

    All of them rather than the first, because a fork with `origin` and
    `upstream` carries the same branch name twice as a matter of course, and
    telling that caller about one copy would name half of what is there --
    which reads as the whole of it.

    Not asked of a selector that has already said it means something else: a
    `branch:` names a local ref, and `worktree:` or a path names a worktree."""
    if selector.startswith(("branch:", "worktree:", "/")):
        return []
    return [t for t in targets if t.kind is TargetKind.REMOTE_BRANCH and t.ref_name == selector]


def _not_offered(selector: str, survey_data: Survey) -> NotOffered | None:
    """A ref that exists and that gitclean deliberately does not target.

    Matched on the full `<remote>/<ref>` spelling only. A bare-short fallback
    looks helpful and is a trap: `main` would match the recorded `origin/main`
    and refuse to delete the *local* trunk, a different ref that is a perfectly
    legal thing to name. This is only ever consulted once nothing matched, so
    the narrow comparison costs nothing real."""
    return next(
        (e for e in survey_data.not_offered if selector in {e.name, f"remote:{e.name}"}),
        None,
    )


def _unsplit_this_could_name(selector: str, survey_data: Survey) -> NotOffered | None:
    """A ref whose remote and branch name could not be told apart, and whose
    branch name this selector may be.

    Not a rival for the selection -- a bare name does not reach a server ref at
    all now, so nothing here competes for a match. It is the unsplittable twin
    of the case above: where the split succeeded, a bare name that hits only a
    server ref can be told exactly what to spell instead, and where it failed
    the spelling to suggest is the unanswered question. So the run reports the
    doubt rather than an absence it cannot support.

    The doubt is per-selector, and that is decidable rather than a guess. A
    remote-tracking ref is `refs/remotes/<remote>/<branch>`, and the two halves
    are joined by a slash -- so whichever remote the path belongs to, the branch
    name is one of the suffixes beginning after one of those slashes. Which one
    is exactly what went unanswered, so every one of them is possible, and the
    true name is certainly among them. A selector outside that set could not
    have been naming this ref however it splits.

    Run-wide doubt would be the other option and it is worse than it sounds: a
    tracking ref outliving `git remote remove` makes every ref under that
    prefix unsplittable, and a tool that then refuses every name in the
    repository has traded a deletion hazard for being unusable.

    Not asked of a selector that has already said it means something else. A
    `branch:` names a local ref, and `worktree:` or a path names a worktree;
    neither can be a server ref under any splitting."""
    if selector.startswith(("branch:", "worktree:", "/")):
        return None
    for entry in survey_data.not_offered:
        if not entry.unsplit:
            continue
        candidates = {entry.name, f"remote:{entry.name}"}
        candidates.update(
            entry.name.split("/", cut)[-1] for cut in range(1, entry.name.count("/") + 1)
        )
        if selector in candidates:
            return entry
    return None


def _lists_that_could_not_answer(selector: str, survey_data: Survey) -> list[str]:
    """Of the listings that could have contained this name, which did not run.

    Keyed on what the selector's own spelling can denote. The `worktree:` /
    `branch:` / `remote:` prefixes are the convention the ids use, and a caller
    who spelled out the kind has said which listing is the relevant one -- a
    failure in the other is then none of this selector's business, and refusing
    on it would block the commonest cleanup there is, a worktree already
    removed, over a ref read that had nothing to do with it. An absolute path
    says the same thing without the prefix: git will not create a ref whose
    short name begins with a slash, so nothing but a worktree can be meant.

    A bare name could be either -- a branch, or a worktree's basename -- so it
    needs both. Being unable to say which kind was meant is not a reason to
    trust whichever one happened to answer.

    "Could not answer" covers a listing that did not run, one that ran without
    describing everything it listed, *and* one holding a server ref whose
    branch name went unrecovered. A row nobody could parse is a thing whose
    existence went unrecorded, which is the same hole as never having looked --
    and so is a ref recorded only as `<remote>/<ref>` because the two halves
    could not be told apart. A bare name would not have selected that ref in
    any case, but where the split succeeds the caller is told the full spelling
    to use instead, and here that spelling is exactly what nobody could work
    out. Absence is the one answer that stays unavailable, since the branch may
    be alive on the server under the name they gave.

    That last one is asked of every selector but `branch:`, which says a local
    branch outright. Local refs were read and split fine; a miss there is a
    real miss, and refusing it over a remote ref nobody was talking about
    trades a false absence for a false refusal."""
    worktree_only = selector.startswith("worktree:") or selector.startswith("/")
    ref_only = selector.startswith(("branch:", "remote:"))
    unread: list[str] = []
    if not ref_only:
        if not survey_data.worktrees_known:
            unread.append("no worktree could be listed")
        elif survey_data.dropped_worktrees:
            unread.append(f"{survey_data.dropped_worktrees} worktree block(s) went unparsed")
        elif not survey_data.worktrees_framed:
            # Not "a path was truncated" -- nobody can say that. The listing
            # cannot prove it named every path, and a name matching nothing is
            # only absence when the look was capable of finding it. Asked of the
            # listing rather than of the selector, because a selector with no
            # newline in it proves nothing: a worktree at `/a/we<LF>ird/final`
            # is recorded as `/a/we`, and `final` is a perfectly newline-free
            # name for the thing that is still on disk.
            unread.append(
                "the worktree listing could not be framed so a path containing a newline stays "
                "whole, so it cannot show that every worktree it holds was named in full"
            )
    if not worktree_only:
        if not survey_data.branches_known:
            unread.append("no ref could be read")
        elif survey_data.dropped_refs:
            unread.append(f"{survey_data.dropped_refs} ref row(s) went unparsed")
        unsplit = _unsplit_this_could_name(selector, survey_data)
        if unsplit is not None:
            unread.append(
                f"the server ref recorded as {unsplit.name} could not be split into a remote and "
                f"a branch name, so whether the server holds a branch called {selector!r} is "
                f"exactly the question that went unanswered"
            )
    return unread


def resolve_selectors(
    selectors: list[str], targets: tuple[Target, ...], survey_data: Survey
) -> tuple[list[Target], list[Absent], list[Refusal]]:
    """Map caller-supplied names onto targets.

    Every selector is resolved on its own, and one that cannot be resolved
    takes only itself out of the run. What it produces is a refusal in the
    returned list rather than a stop: the caller named several things, and the
    ones that resolved are still theirs to have.

    A miss is recorded and the remaining selectors are still resolved. But a
    miss only *means* absence when the survey was in a position to see the
    thing, and there are three ways it was not -- all of which reach here
    looking exactly like a name that matches nothing:

    - the listing that would have held it failed, so it is missing from a list
      that is empty for that reason rather than because the repository is
    - the name is a ref this tool deliberately does not offer as a target
    - the only thing wearing the name is a copy on a server, which a bare name
      does not select

    In none of them is "there is nothing to delete" a fact anybody measured,
    and saying it would leave a caller believing a deletion happened. All three
    refuse instead, which is what the tool does whenever the honest answer is
    that it cannot say.

    Where the survey *did* answer, the note states both remaining readings.
    Nothing here can distinguish a worktree removed thirty seconds ago from a
    name with a letter wrong -- the repository answers identically -- so
    asserting either one would be a claim the tool cannot support.
    """
    resolved: list[Target] = []
    absent: list[Absent] = []
    refused: list[Refusal] = []
    for selector in selectors:
        matches = [t for t in targets if selector in _selector_candidates(t)]
        if not matches:
            excluded = _not_offered(selector, survey_data)
            if excluded is not None:
                refused.append(
                    Refusal(
                        code="E_NOT_A_TARGET",
                        message=f"{excluded.name} exists but is not something gitclean "
                        f"deletes: {excluded.reason}",
                        remedy="use git directly if that is genuinely what you want; "
                        "nothing in this run touched it",
                    )
                )
                continue
            servers = _bare_server_refs(selector, targets)
            if servers:
                listed = ", ".join(t.name for t in servers)
                # Joined with `or` for the remedy, where the comma-joined list
                # would be actively misleading: a remedy that reads as something
                # to paste puts `origin/x, upstream/x` on the command line as a
                # single argv, comma and all, which names nothing at all. It is
                # a choice besides -- two remotes carrying the name is not two
                # copies the caller meant.
                choice = " or ".join(t.name for t in servers)
                refused.append(
                    Refusal(
                        code="E_BARE_NAME_IS_SERVER_REF",
                        message=f"nothing local matches {selector!r}: no worktree, and no branch "
                        f"in this repository. What carries that name here is {listed} -- a "
                        f"copy on a server, which a bare name does not select",
                        blocked=tuple(servers),
                        remedy=f"if a server's copy is what you meant, re-run naming that one in "
                        f"full: {choice}. A server keeps no reflog, so its refs go only when "
                        f"spelled out; if you meant a local branch, it is already gone",
                    )
                )
                continue
            unread = _lists_that_could_not_answer(selector, survey_data)
            if unread:
                refused.append(
                    Refusal(
                        code="E_SURVEY_INCOMPLETE",
                        message=f"nothing matched {selector!r}, and nothing follows from that "
                        f"here: {' and '.join(unread)}. So this run cannot tell you that name "
                        f"is gone -- what wears it may be sitting right there",
                        remedy="fix what stopped the listing (the warnings say what it was) "
                        "and re-run; nothing under this name was deleted",
                    )
                )
                continue
            absent.append(
                Absent(
                    selector=selector,
                    note=f"no worktree or branch matches {selector!r}, so there is nothing "
                    f"to delete -- it was already gone before this run, or the name is "
                    f"wrong. `gitclean --report` lists every `id` that exists",
                )
            )
            continue
        if len(matches) > 1:
            ids = ", ".join(t.id for t in matches)
            refused.append(
                Refusal(
                    code="E_AMBIGUOUS_TARGET",
                    message=f"{selector!r} matches more than one target: {ids}",
                    blocked=tuple(matches),
                    remedy="re-run naming the exact `id`",
                )
            )
            continue
        if matches[0] not in resolved:
            resolved.append(matches[0])
    return resolved, absent, refused


_ORDER = {TargetKind.WORKTREE: 0, TargetKind.BRANCH: 1, TargetKind.REMOTE_BRANCH: 2}


def _ordered(targets: list[Target]) -> tuple[Target, ...]:
    """Worktrees before the branches they hold, local before remote. git
    refuses to delete a branch a worktree still occupies, so this ordering is
    a correctness requirement, not presentation."""
    return tuple(sorted(targets, key=lambda t: (_ORDER[t.kind], t.name)))


def _invoking_worktree(chosen: list[Target], survey_data: Survey) -> list[Target]:
    """The directory this process is running in, if the caller named it.

    Removing it deletes the working directory out from under the run: every
    later git call in the same process fails against a path that is no longer
    there, and the failures read as unrelated problems."""
    root = Path(survey_data.repo_root)
    return [t for t in chosen if t.kind is TargetKind.WORKTREE and Path(t.name) == root]


def _occupancy_blockers(chosen: list[Target], survey_data: Survey) -> list[tuple[Target, str]]:
    """Branch targets whose holding worktree is not also being removed."""
    chosen_ids = {t.id for t in chosen}
    blockers: list[tuple[Target, str]] = []
    for target in chosen:
        if target.kind is not TargetKind.BRANCH:
            continue
        surveyed = survey_data.local_branch(target.name)
        holder = surveyed.checked_out_at if surveyed else None
        if holder and f"worktree:{holder}" not in chosen_ids:
            blockers.append((target, holder))
    return blockers


def _skip_occupied(
    chosen: list[Target], occupancy: list[tuple[Target, str]]
) -> tuple[list[Target], list[Skipped]]:
    """Drop the branches git will refuse because a worktree still holds them,
    and say which.

    What a sweep does about occupancy, wherever the sweep got its candidates
    from: one occupied branch must not block cleaning everything else that is
    provably merged, so it is skipped rather than refused -- and the ``Skipped``
    row carries the omission, because a clean-looking run that quietly did less
    than the caller assumes reads as "everything was cleaned".

    One function rather than one per sweeping mode. Two copies of this would be
    two places to disagree about whether an occupied branch stops a run."""
    blocked = {t.id for t, _ in occupancy}
    return (
        [t for t in chosen if t.id not in blocked],
        [
            Skipped(
                target_id=t.id,
                name=t.name,
                reason=f"checked out at {path}; remove that worktree to make it deletable",
            )
            for t, path in occupancy
        ],
    )


def _pull_request_scope(head_ref: str, targets: tuple[Target, ...]) -> list[Target]:
    """Everything one pull request produced that this report has a row for: the
    branch it was opened from, the worktree holding that branch, and the copy of
    that branch on the server.

    The counterparts are reached by following ``pairing``, which is the relation
    the survey measured, and never by taking a path or a ref apart. Both of
    those are strings whose halves cannot be recovered by looking for a
    delimiter -- a worktree path may contain anything at all, and a remote's own
    name may contain the slash in `<remote>/<ref>` -- so a scope built by
    splitting would silently take in a neighbour's worktree, or miss the one it
    was aiming at. Following the id is what publishing the id is for.

    The server copy is gathered so that it can be *reported*. It is part of what
    the pull request produced, and a scope that simply left it out would let a
    caller read a clean run as the branch being gone everywhere, which is the
    one place this mode could quietly mislead."""
    branch = next((t for t in targets if t.kind is TargetKind.BRANCH and t.name == head_ref), None)
    if branch is None:
        return []
    by_id = {t.id: t for t in targets}
    scope = [by_id[c.id] for c in branch.pairing if c.id is not None]
    scope.append(branch)
    return scope


def build_after_merge_plan(
    targets: tuple[Target, ...],
    survey_data: Survey,
    *,
    pull_request: PullRequestOutcome | str,
    dry_run: bool,
) -> Plan | Refusal:
    """A sweep narrowed to what one merged pull request produced.

    The refusals here are all about the authorising fact, because that fact is
    the only thing this mode has that a bare sweep does not. It cannot be
    asserted by the caller and it cannot be inferred from the repository: a
    merged pull request is something gh answers for, so a gh that did not answer
    means this run has no authority at all -- not a degraded one -- and a pull
    request that closed without merging is not an authority either. Closing one
    says somebody stopped wanting the change; it never says its commits exist
    anywhere else, and they do not.

    Past that point nothing is taken on the pull request's word. A merged pull
    request describes the commit its head pointed at, not whatever the branch of
    that name holds now, so what the sweep takes is decided by the same six
    questions classification asks of everything else. A branch in scope that
    fails one of them is reported with the measurement that stopped it and left
    exactly where it is.

    ``salvage_dir`` has no parameter here, and that is a property of the mode
    rather than an omission: salvage is retained only where no reflog exists,
    which is the server, and no server ref can enter this plan."""
    if isinstance(pull_request, str):
        return Refusal(
            code="E_PR_UNREADABLE",
            message=f"this run deletes only what a merged pull request produced, and whether "
            f"one merged could not be established: {pull_request}",
            remedy="fix what stopped the pull-request read and re-run, or name what you want "
            "gone to --cleanup, which asks nothing of gh; nothing here was touched",
        )
    if pull_request.state != "MERGED":
        return Refusal(
            code="E_PR_NOT_MERGED",
            message=f"pull request #{pull_request.number} is {pull_request.state}, not merged: "
            f"the one thing authorising this mode to delete is that the change landed, and a "
            f"pull request that closed without merging says somebody stopped wanting it rather "
            f"than that its commits exist anywhere else",
            remedy=f"nothing was deleted; if you want {pull_request.head_ref} gone regardless, "
            f"name it to --cleanup -- that authorisation is yours to give, and this mode "
            f"deliberately will not infer it",
        )
    if pull_request.merged_at is None:
        return Refusal(
            code="E_PR_UNREADABLE",
            message=f"gh reports pull request #{pull_request.number} as MERGED and recorded no "
            f"time at which it merged, so the two things it says about that decision do not "
            f"agree; a merge this cannot read is not one it acts on",
            remedy="check what gh reports for that pull request and re-run, or name what you "
            "want gone to --cleanup; nothing here was touched",
        )

    scope = _pull_request_scope(pull_request.head_ref, targets)
    if not scope:
        # A job already done is a success. The branch a merged pull request
        # finishes with is routinely deleted by the forge, by whatever removed
        # the worktree, or by the agent that ran this a moment ago -- and being
        # told a completed job failed is what sends a caller to raw git.
        return Plan(
            targets=(),
            salvage_dir=None,
            dry_run=dry_run,
            absent=(
                Absent(
                    selector=pull_request.head_ref,
                    note=f"pull request #{pull_request.number} merged, and nothing it produced "
                    f"is still here: no local branch named {pull_request.head_ref!r}, and so no "
                    f"worktree holding one. The cleanup was already done",
                ),
            ),
        )

    chosen: list[Target] = []
    skipped: list[Skipped] = []
    for candidate in scope:
        if candidate.kind is TargetKind.REMOTE_BRANCH:
            # Whatever its state, and not by way of the sweep rule that would
            # have caught it anyway: a merged pull request is an authority over
            # this repository's copy of the work, and deleting the server's copy
            # is irreversible for everyone fetching it.
            skipped.append(
                Skipped(
                    target_id=candidate.id,
                    name=candidate.name,
                    reason=f"the copy on the server, which a merged pull request does not "
                    f"authorise deleting: the server keeps no reflog, so it goes only when it "
                    f"is named -- `gitclean --cleanup {candidate.name}` bundles it first",
                )
            )
        elif candidate.withheld is not None:
            # `sweepable` asked in the spelling that carries the answer: the two
            # are the same question, and only one of them can be reported.
            skipped.append(
                Skipped(target_id=candidate.id, name=candidate.name, reason=candidate.withheld)
            )
        else:
            chosen.append(candidate)

    chosen, occupied = _skip_occupied(chosen, _occupancy_blockers(chosen, survey_data))
    skipped.extend(occupied)
    return Plan(
        targets=_ordered(chosen),
        salvage_dir=None,
        dry_run=dry_run,
        skipped=tuple(skipped),
    )


def build_plan(
    targets: tuple[Target, ...],
    survey_data: Survey,
    *,
    selectors: list[str],
    dry_run: bool,
    salvage_dir: str | None,
) -> Plan:
    """Always a plan, never a refusal for the run as a whole.

    Nothing a caller can put on a command line makes the *other* things they
    named undeletable, so there is no longer a way for this to answer with a
    stop. Each objection belongs to the target it is about, travels in
    ``Plan.refused``, and the run exits non-zero for having raised any."""
    absent: list[Absent] = []
    refused: list[Refusal] = []
    if selectors:
        chosen, absent, refused = resolve_selectors(selectors, targets, survey_data)
        invoking = _invoking_worktree(chosen, survey_data)
        if invoking:
            chosen = [t for t in chosen if t not in invoking]
            refused.append(
                Refusal(
                    code="E_INVOKING_WORKTREE",
                    message=f"this run is executing inside {survey_data.repo_root}, so removing "
                    f"it would delete the process's own working directory",
                    blocked=tuple(invoking),
                    remedy="run gitclean from another worktree, or from the main checkout, "
                    "and name this one from there",
                )
            )
    else:
        chosen = [t for t in targets if t.sweepable]

    occupancy = _occupancy_blockers(chosen, survey_data)
    chosen, skipped = _skip_occupied(chosen, occupancy)
    if occupancy and selectors:
        # Named explicitly: the caller believes this is deletable and git is
        # about to disagree, so say so rather than silently doing less than
        # they asked for. Reported as a refusal rather than the sweep's quiet
        # `Skipped` row, and in place of it -- one omission, said once, in the
        # register the caller's own naming earned.
        detail = "; ".join(f"{t.name} is checked out at {path}" for t, path in occupancy)
        refused.append(
            Refusal(
                code="E_BRANCH_IN_USE",
                message=f"git will not delete a branch a worktree still holds: {detail}",
                blocked=tuple(t for t, _ in occupancy),
                remedy="add the holding worktree to the same cleanup so it is removed first",
            )
        )
        skipped = []

    return Plan(
        targets=_ordered(chosen),
        # Salvage is retained only where no reflog exists, which is the server.
        # A local branch deleted with `-D` leaves its commits in the reflog for
        # the configured expiry, and bundling them as well bought disk usage
        # and a restore route nobody took.
        salvage_dir=(
            salvage_dir if any(t.kind is TargetKind.REMOTE_BRANCH for t in chosen) else None
        ),
        dry_run=dry_run,
        skipped=tuple(skipped),
        absent=tuple(absent),
        refused=tuple(refused),
    )
