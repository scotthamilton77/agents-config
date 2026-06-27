"""Build receipt entries and desired-key sets from staging plans and install outcomes.

``desired_staged_keys`` is plan-derived (what we want installed now, built even
under ``--prune-only``) and drives orphan detection; the entry builders
(``entries_from_outcomes`` / ``entries_from_route_outcomes``) record installed
state from per-item install outcomes.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from installer.core.model import FileKind, InstallOutcome, Outcome, StagingPlan
from installer.core.ownership import PRUNE_NAMESPACES, entry_for, route_entry_for
from installer.core.receipt import Receipt, ReceiptEntry, dir_content_digest

if TYPE_CHECKING:
    from installer.plugins.base import PluginAdapter


def entries_from_outcomes(
    outcomes: list[InstallOutcome], *, tool: str, dest_root: Path, home: Path
) -> list[ReceiptEntry]:
    """Receipt entries for a tool's wholesale-owned writes, with real sha256.

    Excludes DECLINED outcomes (the user's bytes) and any write outside the prune
    namespaces. A ``settings.json`` write is excluded even under a prune namespace:
    it is a merge-target holding the user's bytes (mirroring ``is_prunable``'s
    ``FileKind.SETTINGS_JSON`` guard), so recording it would make the user's merged
    file eligible for orphan pruning. Directory writes carry ``sha256=None`` and a
    recursive ``dir_digest`` of the just-installed tree (the owned state), so a
    later prune can relinquish a directory whose contents drifted; the kind is
    inferred from sha256 presence."""
    out: list[ReceiptEntry] = []
    for o in outcomes:
        if o.outcome is Outcome.DECLINED:
            continue
        rel = o.dest.relative_to(dest_root)
        if not rel.parts or rel.parts[0] not in PRUNE_NAMESPACES:
            continue
        if rel.name == FileKind.SETTINGS_JSON.value:
            continue
        is_file = o.sha256 is not None
        # dir_content_digest re-walks the just-installed tree. A transient unreadable
        # inner file raises OSError and aborts receipt finalization (fail loud): a
        # half-readable tree would record a digest that mis-classifies the directory
        # at the next prune boundary, so refusing to stamp a wrong receipt is safer
        # than recording one. (The prune path, by contrast, catches OSError and
        # relinquishes — it must never delete on uncertainty.)
        out.append(
            ReceiptEntry(
                path=o.dest.relative_to(home),
                owner=tool,
                root=dest_root.relative_to(home),
                kind="file" if is_file else "dir",
                sha256=o.sha256,
                dir_digest=None if is_file else dir_content_digest(o.dest),
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


def merge_receipt(
    prior: Receipt,
    *,
    installed: list[ReceiptEntry],
    pruned_paths: set[Path],
    relinquished_paths: set[Path],
    live_roots: set[Path],
) -> Receipt:
    """Mirrors-disk receipt: ``(prior - pruned - relinquished) | installed``.

    Prior entries survive unless their path was pruned or relinquished, so a
    partial run (e.g. ``--tools=claude``) never erases an untargeted tool's or a
    still-present plugin's recorded entries. ``installed`` wins on a path clash
    (it carries the freshly-computed sha256). ``roots`` accumulates the prior and
    live install roots (the persisted allowlist only grows)."""
    by_path: dict[Path, ReceiptEntry] = {
        e.path: e
        for e in prior.entries
        if e.path not in pruned_paths and e.path not in relinquished_paths
    }
    for e in installed:
        by_path[e.path] = e
    roots = tuple(sorted(set(prior.roots) | live_roots, key=str))
    return Receipt(roots=roots, entries=tuple(by_path.values()))


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


def desired_route_keys(plugins: Iterable[PluginAdapter], *, home: Path) -> set[tuple[str, Path]]:
    """Desired keys for the active plugins' currently-shipped route files.

    A plugin's route installs each ``source_dir.glob(glob)`` file at
    ``dest_dir/<name>``; those still-shipped files must count as desired so a
    ``--prune`` run does not delete an active plugin's current formulas. A prior
    file the plugin no longer ships is absent here, so it is still pruned."""
    keys: set[tuple[str, Path]] = set()
    for plugin in plugins:
        for route in plugin.routes(home):
            if not route.source_dir.is_dir():
                continue
            for src in sorted(route.source_dir.glob(route.glob)):
                if src.is_file():
                    keys.add((plugin.name, (route.dest_dir / src.name).relative_to(home)))
    return keys
