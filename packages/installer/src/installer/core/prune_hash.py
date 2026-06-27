"""Decide which orphans are safe to prune vs must be relinquished.

A FILE orphan is pruned only while its on-disk bytes still match the receipt's
recorded sha256 (or the file is genuinely gone); a user-modified, type-drifted, or
unreadable path is relinquished — kept on disk, dropped from the receipt. A DIR
orphan is pruned only while the path is still a real directory (recursive
content-drift protection is deferred); a dir path that drifted to a file or symlink
is relinquished. The same per-orphan decision (``is_prunable``) is evaluated at scan
time AND re-evaluated at the deletion boundary, so a path that changes between the
two (the TOCTOU window of the interactive confirm prompt) is never deleted."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from installer.core.model import Orphan


def is_prunable(
    orphan: Orphan, *, home: Path, recorded_sha_by_path: dict[Path, str | None]
) -> bool:
    """Whether ``orphan`` is currently safe to prune (vs relinquish / keep).

    ``True`` — our pristine content, or the path is genuinely absent: safe to delete.
    ``False`` — drifted, replaced, or unreadable: relinquish, leave the user's content.

    Evaluated against the LIVE filesystem, so it is correct at both scan time
    (``partition_file_orphans`` buckets prune vs relinquish) and again at the
    deletion boundary (``run_prune`` re-checks just before backup/delete), closing
    the TOCTOU window between the scan and the actual delete.

    - dir: prunable only while still a real directory (or already gone); a path that
      type-drifted to a file or symlink is the user's now (recursive CONTENT-drift
      for still-real dirs stays deferred). ``is_symlink`` is tested first so a
      dir-symlink never counts as a real directory.
    - file: prunable when the bytes still match the recorded sha256, or the file
      genuinely vanished (``FileNotFoundError`` — the delete is a no-op). A digest
      mismatch (user-modified) or an unreadable path (a directory now occupies it,
      or a permission/FS error) is NOT prunable — we cannot confirm the bytes are
      ours and the delete would not be a no-op."""
    if orphan.kind == "dir":
        return not orphan.path.is_symlink() and (not orphan.path.exists() or orphan.path.is_dir())
    try:
        actual = hashlib.sha256(orphan.path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    recorded = recorded_sha_by_path.get(orphan.path.relative_to(home))
    return recorded is None or actual == recorded


def partition_file_orphans(
    orphans: Sequence[Orphan],
    *,
    home: Path,
    recorded_sha_by_path: dict[Path, str | None],
) -> tuple[list[Orphan], set[Path]]:
    """Split orphans into (to_prune, relinquished_home_relative_paths).

    An orphan that is not currently prunable (see ``is_prunable``) is relinquished:
    kept on disk and dropped from the receipt."""
    to_prune: list[Orphan] = []
    relinquished: set[Path] = set()
    for orphan in orphans:
        if is_prunable(orphan, home=home, recorded_sha_by_path=recorded_sha_by_path):
            to_prune.append(orphan)
        else:
            relinquished.add(orphan.path.relative_to(home))
    return to_prune, relinquished
