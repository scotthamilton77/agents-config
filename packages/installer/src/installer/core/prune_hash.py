"""Partition file orphans by on-disk hash before deletion.

A FILE orphan whose current bytes differ from the receipt's recorded sha256 was
modified by the user after we installed it; it is relinquished (kept on disk,
dropped from the receipt) rather than deleted. Directory orphans always prune
(recursive content-hash drift protection is deferred). A file that vanished or is
unreadable falls through to prune (the delete is a harmless no-op)."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from installer.core.model import Orphan


def partition_file_orphans(
    orphans: Sequence[Orphan],
    *,
    home: Path,
    recorded_sha_by_path: dict[Path, str | None],
) -> tuple[list[Orphan], set[Path]]:
    """Split orphans into (to_prune, relinquished_home_relative_paths)."""
    to_prune: list[Orphan] = []
    relinquished: set[Path] = set()
    for orphan in orphans:
        if orphan.kind == "dir":
            to_prune.append(orphan)
            continue
        rel = orphan.path.relative_to(home)
        recorded = recorded_sha_by_path.get(rel)
        try:
            actual = hashlib.sha256(orphan.path.read_bytes()).hexdigest()
        except OSError:
            to_prune.append(orphan)
            continue
        if recorded is not None and actual != recorded:
            relinquished.add(rel)
        else:
            to_prune.append(orphan)
    return to_prune, relinquished
