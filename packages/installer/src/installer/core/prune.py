"""Orphan scan — identify retired dest entries to prune.

An orphan is a top-level entry directly inside a tool's scoped namespace dir
(``commands``/``skills``/``agents``/``rules``) or ``~/.beads/formulas`` that:

1. is NOT present in this run's ``StagingPlan`` (nothing staged it), AND
2. matches a prune-list glob keyed ``tool/namespace/basename``.

Item granularity is the top-level entry — the scan does not recurse into nested
skill directories. Legacy ``*.backup-*`` entries (in-place backups from older
``backup()`` implementations) are skipped so they are never treated as orphans.
Sibling ``<namespace>-backup/`` dirs live at the grandparent level and are never
visited by this scan.

``~/.beads/formulas`` is scanned whenever pruning runs, regardless of beads
plugin detection: if beads is not an active plugin, no plan staged any formula,
so every dest formula registers as an orphan (strict mode).

Matching is ``fnmatch`` on the ``tool/namespace/basename`` key. Pure: it reads
the destination filesystem and the in-memory plans, and returns ``list[Orphan]``
without mutating anything.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from installer.core.model import Orphan, Tool

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from installer.core.installer_toml import InstallerToml
    from installer.core.model import StagingPlan
    from installer.tools.base import ToolAdapter

# Tool-tree namespaces scanned for orphans. Narrower than
# ``adapter.scoped_namespaces()`` only incidentally — kept explicit so the scan
# set is independent of adapter changes.
_PRUNE_SUBDIRS = ("commands", "skills", "agents", "rules")

# Beads' formulas live outside any tool tree; scanned unconditionally under a
# fixed ``beads/formulas`` key.
_BEADS_TOOL = "beads"
_BEADS_NAMESPACE = "formulas"


def _staged_basenames(plan: StagingPlan | None, namespace: str) -> set[str]:
    """Top-level entry names the plan stages under ``namespace``.

    The plan keys items by ``dest_relpath`` (e.g. ``skills/foo``); the
    first-level child name under ``namespace`` is what a dest entry is compared
    against. A ``None`` plan (e.g. a namespace no plan targets) stages nothing.
    """
    if plan is None:
        return set()
    return {
        item.dest_relpath.parts[1]
        for item in plan.items.values()
        if len(item.dest_relpath.parts) >= 2 and item.dest_relpath.parts[0] == namespace
    }


def _scan_namespace(
    *,
    tool: str,
    namespace: str,
    dest: Path,
    staged: set[str],
    prune_globs: Sequence[str],
) -> list[Orphan]:
    """Collect orphans in one dest namespace dir (bash ``_scan_namespace``).

    An entry is an orphan when it is not a legacy ``*.backup-*`` file, is not
    staged, and its ``tool/namespace/basename`` key matches a prune glob.
    """
    if not dest.is_dir():
        return []

    orphans: list[Orphan] = []
    for entry in sorted(dest.iterdir()):
        base = entry.name
        if ".backup-" in base:
            continue
        if base in staged:
            continue
        key = f"{tool}/{namespace}/{base}"
        if not any(fnmatch(key, pattern) for pattern in prune_globs):
            continue
        orphans.append(
            Orphan(
                tool=tool,
                namespace=namespace,
                path=entry,
                kind="dir" if entry.is_dir() else "file",
            )
        )
    return orphans


def scan_orphans(
    adapters: Iterable[ToolAdapter],
    *,
    plans: dict[Tool, StagingPlan],
    home: Path,
    config: InstallerToml,
) -> list[Orphan]:
    """Scan every active tool's namespaces plus ``~/.beads/formulas`` for orphans.

    For each adapter, walk the prune subdirs under its ``dest_dir(home)``,
    comparing each top-level entry against the tool's plan and the prune globs.
    Then scan ``~/.beads/formulas`` once with a fixed ``beads`` tool bucket
    (strict mode: nothing in the per-tool plans stages a beads formula, so an
    unmatched-by-plan formula is an orphan when a glob matches). Returns all
    orphans in tool-then-namespace iteration order; an empty prune list yields
    no orphans.
    """
    prune_globs = config.prune_globs
    orphans: list[Orphan] = []

    for adapter in adapters:
        plan = plans.get(Tool(adapter.name))
        dest_root = adapter.dest_dir(home)
        for namespace in _PRUNE_SUBDIRS:
            orphans.extend(
                _scan_namespace(
                    tool=adapter.name,
                    namespace=namespace,
                    dest=dest_root / namespace,
                    staged=_staged_basenames(plan, namespace),
                    prune_globs=prune_globs,
                )
            )

    orphans.extend(
        _scan_namespace(
            tool=_BEADS_TOOL,
            namespace=_BEADS_NAMESPACE,
            dest=home / ".beads" / _BEADS_NAMESPACE,
            staged=set(),
            prune_globs=prune_globs,
        )
    )
    return orphans
