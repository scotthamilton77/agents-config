"""Pure: turns classified targets plus the caller's intent into a Plan or a Refusal.

A bare sweep takes exactly the targets classification marked ``sweepable`` and
nothing else. A named target is not re-adjudicated at all: naming it is the
authorisation, and re-deriving safety underneath the caller is how a tool ends
up arguing with the person using it. git's own refusals still stand where
nothing overrides them, and they carry better information than a re-derivation
would -- git knows what its working tree holds right now.

So the refusals left here are few, and each answers something the caller could
not have answered themselves: a name matching nothing, a name matching two
things, a branch git will reject because a worktree still holds it, and the
directory this process is standing in.
"""

from __future__ import annotations

from pathlib import Path

from gitclean.model import Plan, Refusal, Skipped, Survey, Target, TargetKind


def _selector_candidates(target: Target) -> set[str]:
    """Every string a caller may reasonably use to name this target."""
    names = {target.id, target.name}
    if target.kind is TargetKind.WORKTREE:
        names.add(Path(target.name).name)
    if target.kind is TargetKind.REMOTE_BRANCH and "/" in target.name:
        names.add(target.name.split("/", 1)[1])
    return names


def resolve_selectors(
    selectors: list[str], targets: tuple[Target, ...]
) -> tuple[list[Target], Refusal | None]:
    """Map caller-supplied names onto targets, refusing on miss or ambiguity."""
    resolved: list[Target] = []
    for selector in selectors:
        matches = [t for t in targets if selector in _selector_candidates(t)]
        if not matches:
            return [], Refusal(
                code="E_UNKNOWN_TARGET",
                message=f"no worktree or branch matches {selector!r}",
                remedy="run `gitclean --report` and select by the `id` field",
            )
        if len(matches) > 1:
            ids = ", ".join(t.id for t in matches)
            return [], Refusal(
                code="E_AMBIGUOUS_TARGET",
                message=f"{selector!r} matches more than one target: {ids}",
                blocked=tuple(matches),
                remedy="re-run naming the exact `id`",
            )
        if matches[0] not in resolved:
            resolved.append(matches[0])
    return resolved, None


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
    if selectors:
        chosen, refusal = resolve_selectors(selectors, targets)
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
    )
