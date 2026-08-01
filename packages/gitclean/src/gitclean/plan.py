"""Pure: turns classified targets plus the caller's intent into a Plan or a Refusal.

A bare sweep takes exactly the targets classification marked ``sweepable`` and
nothing else. A named target is not re-adjudicated at all: naming it is the
authorisation, and re-deriving safety underneath the caller is how a tool ends
up arguing with the person using it. git's own refusals still stand where
nothing overrides them, and they carry better information than a re-derivation
would -- git knows what its working tree holds right now.

So the refusals left here are few, and each answers something the caller could
not have answered themselves: a name matching two things, a branch git will
reject because a worktree still holds it, and the directory this process is
standing in.

A name matching *nothing* used to be one of them, and was wrong. The caller
asked for that thing to be gone; it is gone. Refusing there reports a completed
job as a failure -- and because a selector refusal aborts the whole plan, one
name that had already been dealt with stopped every other deletion the caller
asked for.

What replaced it is narrower than "a miss is fine", because a miss has three
causes and only one of them is absence. The list can also be empty because the
ref read failed, or missing a name because this tool does not offer that ref as
a target -- and in both the branch is sitting right there. Those two refuse,
and the refusal codes say which, because the alternative is telling somebody
their branch is gone while it is not. Concluding absence from a list that was
never able to answer is the same mistake as reading an unanswered probe as a
clean working tree.
"""

from __future__ import annotations

from pathlib import Path

from gitclean.model import (
    Absent,
    NotOffered,
    Plan,
    Refusal,
    Skipped,
    Survey,
    Target,
    TargetKind,
)


def _selector_candidates(target: Target) -> set[str]:
    """Every string a caller may reasonably use to name this target."""
    names = {target.id, target.name}
    if target.kind is TargetKind.WORKTREE:
        names.add(Path(target.name).name)
    if target.kind is TargetKind.REMOTE_BRANCH and "/" in target.name:
        names.add(target.name.split("/", 1)[1])
    return names


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

    "Could not answer" covers a listing that did not run *and* one that ran
    without describing everything it listed. A row nobody could parse is a
    thing whose existence went unrecorded, which is the same hole as never
    having looked."""
    worktree_only = selector.startswith("worktree:") or selector.startswith("/")
    ref_only = selector.startswith(("branch:", "remote:"))
    unread: list[str] = []
    if not ref_only:
        if not survey_data.worktrees_known:
            unread.append("no worktree could be listed")
        elif survey_data.dropped_worktrees:
            unread.append(f"{survey_data.dropped_worktrees} worktree block(s) went unparsed")
    if not worktree_only:
        if not survey_data.branches_known:
            unread.append("no ref could be read")
        elif survey_data.dropped_refs:
            unread.append(f"{survey_data.dropped_refs} ref row(s) went unparsed")
    return unread


def resolve_selectors(
    selectors: list[str], targets: tuple[Target, ...], survey_data: Survey
) -> tuple[list[Target], list[Absent], Refusal | None]:
    """Map caller-supplied names onto targets.

    A miss is recorded and the remaining selectors are still resolved. But a
    miss only *means* absence when the survey was in a position to see the
    thing, and there are two ways it was not -- both of which reach here
    looking exactly like a name that matches nothing:

    - the listing that would have held it failed, so it is missing from a list
      that is empty for that reason rather than because the repository is
    - the name is a ref this tool deliberately does not offer as a target

    In neither case is "there is nothing to delete" a fact anybody measured,
    and saying it would leave a caller believing a deletion happened. Both
    refuse instead, which is what the tool does whenever the honest answer is
    that it cannot say.

    Where the survey *did* answer, the note states both remaining readings.
    Nothing here can distinguish a worktree removed thirty seconds ago from a
    name with a letter wrong -- the repository answers identically -- so
    asserting either one would be a claim the tool cannot support.
    """
    resolved: list[Target] = []
    absent: list[Absent] = []
    for selector in selectors:
        matches = [t for t in targets if selector in _selector_candidates(t)]
        if not matches:
            excluded = _not_offered(selector, survey_data)
            if excluded is not None:
                return (
                    [],
                    [],
                    Refusal(
                        code="E_NOT_A_TARGET",
                        message=f"{excluded.name} exists but is not something gitclean "
                        f"deletes: {excluded.reason}",
                        remedy="use git directly if that is genuinely what you want; "
                        "nothing in this run touched it",
                    ),
                )
            unread = _lists_that_could_not_answer(selector, survey_data)
            if unread:
                return (
                    [],
                    [],
                    Refusal(
                        code="E_SURVEY_INCOMPLETE",
                        message=f"nothing matched {selector!r}, and nothing follows from that "
                        f"here: {' and '.join(unread)}, so what would have matched was never "
                        f"listed -- it may be sitting right there",
                        remedy="fix what stopped the listing (the warnings say what it was) "
                        "and re-run; nothing was deleted",
                    ),
                )
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
            return (
                [],
                [],
                Refusal(
                    code="E_AMBIGUOUS_TARGET",
                    message=f"{selector!r} matches more than one target: {ids}",
                    blocked=tuple(matches),
                    remedy="re-run naming the exact `id`",
                ),
            )
        if matches[0] not in resolved:
            resolved.append(matches[0])
    return resolved, absent, None


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
        holder = next(
            (b.checked_out_at for b in survey_data.branches if b.name == target.name), None
        )
        if holder and f"worktree:{holder}" not in chosen_ids:
            blockers.append((target, holder))
    return blockers


def build_plan(
    targets: tuple[Target, ...],
    survey_data: Survey,
    *,
    selectors: list[str],
    dry_run: bool,
    salvage_dir: str | None,
) -> Plan | Refusal:
    absent: list[Absent] = []
    if selectors:
        chosen, absent, refusal = resolve_selectors(selectors, targets, survey_data)
        if refusal is not None:
            return refusal
        invoking = _invoking_worktree(chosen, survey_data)
        if invoking:
            return Refusal(
                code="E_INVOKING_WORKTREE",
                message=f"this run is executing inside {survey_data.repo_root}, so removing "
                f"it would delete the process's own working directory",
                blocked=tuple(invoking),
                remedy="run gitclean from another worktree, or from the main checkout, "
                "and name this one from there",
            )
    else:
        chosen = [t for t in targets if t.sweepable]

    occupancy = _occupancy_blockers(chosen, survey_data)
    if occupancy and selectors:
        # Named explicitly: the caller believes this is deletable and git is
        # about to disagree, so say so rather than silently doing less than
        # they asked for.
        detail = "; ".join(f"{t.name} is checked out at {path}" for t, path in occupancy)
        return Refusal(
            code="E_BRANCH_IN_USE",
            message=f"git will not delete a branch a worktree still holds: {detail}",
            blocked=tuple(t for t, _ in occupancy),
            remedy="add the holding worktree to the same cleanup so it is removed first",
        )
    skipped: list[Skipped] = []
    if occupancy:
        # Swept automatically: one occupied branch must not block cleaning
        # everything else that is provably merged. Skip it; `skipped` carries
        # the omission so a clean-looking run never hides what it left behind.
        blocked_ids = {t.id for t, _ in occupancy}
        chosen = [t for t in chosen if t.id not in blocked_ids]
        skipped.extend(
            Skipped(
                target_id=t.id,
                name=t.name,
                reason=f"checked out at {path}; remove that worktree to make it deletable",
            )
            for t, path in occupancy
        )

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
    )
