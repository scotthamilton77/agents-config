"""Decide which staged items the receipt records (wholesale-owned, prune-eligible).

A merge-target (settings.json, append-merged instruction file) is never recorded:
dropping our contribution must not delete the whole file. Coincides with the
existing prune namespaces.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.model import FileKind, StagedItem
from installer.core.receipt import ReceiptEntry

PRUNE_NAMESPACES: tuple[str, ...] = ("commands", "skills", "agents", "rules")


def is_prunable(item: StagedItem) -> bool:
    """True iff this item is a wholesale file/dir under a prune namespace."""
    parts = item.dest_relpath.parts
    if not parts or parts[0] not in PRUNE_NAMESPACES:
        return False
    if item.kind == FileKind.SETTINGS_JSON:
        return False
    return item.kind in (FileKind.DIR, FileKind.NAMESPACED_MD, FileKind.OTHER)


def entry_for(item: StagedItem, *, tool: str, dest_root: Path, home: Path) -> ReceiptEntry | None:
    """Build a ReceiptEntry for a tool-tree item, or None if not prunable.

    sha256 is left None here; the builder (a later task) fills it for files from
    the actual install outcome.
    """
    if not is_prunable(item):
        return None
    return ReceiptEntry(
        path=(dest_root / item.dest_relpath).relative_to(home),
        owner=tool,
        root=dest_root.relative_to(home),
        kind=("dir" if item.kind == FileKind.DIR else "file"),
        sha256=None,
    )
