"""Build receipt entries and desired-key sets from staging plans.

desired_staged_keys is ALWAYS plan-derived (what we want installed now, built
even under --prune-only) and drives orphan detection. entries_from_plans is the
tracer source for the receipt write; a later task replaces it with an
install-outcome-derived builder for write correctness.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.model import StagingPlan
from installer.core.ownership import entry_for
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
