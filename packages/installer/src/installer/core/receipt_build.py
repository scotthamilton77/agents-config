"""Build receipt entries and desired-key sets from staging plans.

desired_staged_keys is ALWAYS plan-derived (what we want installed now, built
even under --prune-only) and drives orphan detection. entries_from_plans is the
tracer source for the receipt write; a later task replaces it with an
install-outcome-derived builder for write correctness.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.model import InstallOutcome, Outcome, StagingPlan
from installer.core.ownership import PRUNE_NAMESPACES, entry_for, route_entry_for
from installer.core.receipt import ReceiptEntry


def entries_from_plans(
    plans: dict[str, StagingPlan], *, dest_roots: dict[str, Path], home: Path
) -> list[ReceiptEntry]:
    out: list[ReceiptEntry] = []
    for tool, plan in plans.items():
        dest_root = dest_roots[tool]
        for item in plan.items.values():
            entry = entry_for(item, tool=tool, dest_root=dest_root, home=home)
            if entry is not None:
                out.append(entry)
    return out


def entries_from_outcomes(
    outcomes: list[InstallOutcome], *, tool: str, dest_root: Path, home: Path
) -> list[ReceiptEntry]:
    """Receipt entries for a tool's wholesale-owned writes, with real sha256.

    Excludes DECLINED outcomes (the user's bytes) and anything outside the prune
    namespaces (settings.json, assembled instruction files). Directory writes
    carry ``sha256=None``; the kind is inferred from sha256 presence."""
    out: list[ReceiptEntry] = []
    for o in outcomes:
        if o.outcome is Outcome.DECLINED:
            continue
        rel = o.dest.relative_to(dest_root)
        if not rel.parts or rel.parts[0] not in PRUNE_NAMESPACES:
            continue
        out.append(
            ReceiptEntry(
                path=o.dest.relative_to(home),
                owner=tool,
                root=dest_root.relative_to(home),
                kind="file" if o.sha256 is not None else "dir",
                sha256=o.sha256,
            )
        )
    return out


def entries_from_route_outcomes(
    outcomes: list[InstallOutcome], *, plugin: str, home: Path
) -> list[ReceiptEntry]:
    """Receipt entries for a plugin's routed-file writes (e.g. ~/.beads/...).

    Excludes DECLINED outcomes. Each entry's ``root`` is derived from the file's
    own parent dir (its top segment under home), so multiple routes with
    different dest dirs but the same root collapse correctly."""
    out: list[ReceiptEntry] = []
    for o in outcomes:
        if o.outcome is Outcome.DECLINED:
            continue
        out.append(
            route_entry_for(
                o.dest, plugin=plugin, dest_dir=o.dest.parent, home=home, sha256=o.sha256
            )
        )
    return out


def desired_staged_keys(
    plans: dict[str, StagingPlan],
    *,
    dest_roots: dict[str, Path],
    home: Path,
    scope_owners: set[str],
) -> set[tuple[str, Path]]:
    keys: set[tuple[str, Path]] = set()
    for tool, plan in plans.items():
        if tool not in scope_owners:
            continue
        dest_root = dest_roots[tool]
        for item in plan.items.values():
            entry = entry_for(item, tool=tool, dest_root=dest_root, home=home)
            if entry is not None:
                keys.add((tool, entry.path))
    return keys
