"""Pure: turns classified targets plus the caller's intent into a Plan or a Refusal.

Every refusal names the blocked targets, not just the flag that would silence
it. A refusal that reads only "pass --force" teaches the reader to pass
--force; a refusal that lists *which* three branches carry unpushed commits
lets them drop those three and proceed safely, which is nearly always the
better move.

``Disposition.PROTECTED`` is not overridable by --force. --force exists to
accept data loss the caller understands; it is not a way to delete the branch
you are standing on, which git would reject anyway.
"""

from __future__ import annotations

from pathlib import Path

from gitclean.model import (
    Disposition,
    Plan,
    Refusal,
    Risk,
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
    force: bool,
    include_remote: bool,
    dry_run: bool,
    salvage_dir: str | None,
) -> Plan | Refusal:
    if selectors:
        chosen, refusal = resolve_selectors(selectors, targets)
        if refusal is not None:
            return refusal
    else:
        chosen = [t for t in targets if t.disposition is Disposition.SAFE and t.risk is Risk.NONE]

    if not include_remote:
        remotes = [t for t in chosen if t.kind is TargetKind.REMOTE_BRANCH]
        if remotes and selectors:
            # Named outright, so silence is the wrong answer. Filtering these
            # away leaves a successful, empty plan, which reads as "there was
            # nothing to clean" -- the caller believes the server ref is gone
            # when it is untouched, and finds out later.
            names = ", ".join(t.name for t in remotes)
            return Refusal(
                code="E_REMOTE_NOT_ENABLED",
                message=f"remote branch deletion is off by default, so this run "
                f"cannot delete: {names}",
                blocked=tuple(remotes),
                remedy="re-run with --include-remote to delete refs on the server "
                "(they affect everyone fetching it), or drop these from the selection",
            )
        chosen = [t for t in chosen if t.kind is not TargetKind.REMOTE_BRANCH]

    protected = [t for t in chosen if t.disposition is Disposition.PROTECTED]
    if protected:
        names = ", ".join(t.name for t in protected)
        return Refusal(
            code="E_PROTECTED",
            message=f"refusing to delete protected target(s): {names}",
            blocked=tuple(protected),
            remedy="protected targets are never deletable; --force does not apply. "
            "Switch away from the branch, unlock the worktree, or drop it from the selection",
        )

    occupancy = _occupancy_blockers(chosen, survey_data)
    if occupancy and selectors:
        # Named explicitly: the caller believes this is deletable and is
        # wrong, so say so rather than silently doing less than they asked.
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
        # everything else that is genuinely safe. Skip it; `skipped` carries
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

    risky = [t for t in chosen if t.risk is not Risk.NONE]
    if risky and not force:
        lines = "; ".join(f"{t.name} ({t.risk.value})" for t in risky)
        return Refusal(
            code="E_DATA_LOSS",
            message=f"refusing: these would destroy work that exists nowhere else -- {lines}",
            blocked=tuple(risky),
            remedy="drop these from the selection to clean the rest, or re-run with --force "
            "(which bundles the content to the salvage directory before deleting)",
        )

    return Plan(
        targets=_ordered(chosen),
        salvage_dir=salvage_dir if any(t.salvage_needed for t in chosen) else None,
        dry_run=dry_run,
        skipped=tuple(skipped),
    )
