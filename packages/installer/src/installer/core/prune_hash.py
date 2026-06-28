"""Decide which orphans are safe to prune vs must be relinquished.

A FILE orphan is pruned only while its on-disk bytes still match the receipt's
recorded sha256 (or the file is genuinely gone); a user-modified, type-drifted, or
unreadable path is relinquished — kept on disk, dropped from the receipt. A DIR
orphan is pruned only while the path is still a real directory AND (when a digest
was recorded) its recursive content digest still matches the owned state; a dir
that drifted to a file or symlink, or whose contents the user edited, is
relinquished. A legacy dir entry recorded before digests existed degrades to the
type-check-only guard. The same per-orphan decision (``is_safe_to_prune``) is evaluated at scan
time AND re-evaluated at the deletion boundary, so a path that changes between the
two (the TOCTOU window of the interactive confirm prompt) is never deleted."""

from __future__ import annotations

from typing import TYPE_CHECKING

from installer.core.hashing import sha256_file
from installer.core.receipt import dir_content_digest

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from installer.core.model import Orphan


def is_safe_to_prune(
    orphan: Orphan,
    *,
    home: Path,
    recorded_sha_by_path: dict[Path, str | None],
    recorded_digest_by_path: dict[Path, str | None] | None = None,
) -> bool:
    """Whether ``orphan`` is currently safe to prune (vs relinquish / keep).

    ``True`` — our pristine content, or the path is genuinely absent: safe to delete.
    ``False`` — drifted, replaced, or unreadable: relinquish, leave the user's content.

    Evaluated against the LIVE filesystem, so it is correct at both scan time
    (``partition_file_orphans`` buckets prune vs relinquish) and again at the
    deletion boundary (``run_prune`` re-checks just before backup/delete), closing
    the TOCTOU window between the scan and the actual delete.

    - dir: prunable while still a real directory (or already gone) AND, when a
      digest was recorded for it, its live recursive content digest still matches
      the owned state; a path that type-drifted to a file or symlink, or whose
      contents the user edited, is relinquished. A legacy entry with no recorded
      digest degrades to the type-check-only guard. ``is_symlink`` is tested first
      so a dir-symlink never counts as a real directory.
    - file: prunable when the bytes still match the recorded sha256, or the file
      genuinely vanished (``FileNotFoundError`` — the delete is a no-op). A digest
      mismatch (user-modified) or an unreadable path (a directory now occupies it,
      or a permission/FS error) is NOT prunable — we cannot confirm the bytes are
      ours and the delete would not be a no-op."""
    if orphan.kind == "dir":
        if orphan.path.is_symlink():
            return False
        if not orphan.path.exists():
            return True  # already gone; the delete is a no-op
        if not orphan.path.is_dir():
            return False  # type-drifted to a file — the user's now
        recorded = (recorded_digest_by_path or {}).get(orphan.path.relative_to(home))
        if recorded is None:
            return True  # legacy entry with no recorded digest: type-check only
        try:
            return dir_content_digest(orphan.path) == recorded
        except OSError:
            return False  # unreadable inner file: cannot confirm ownership — relinquish
    try:
        actual = sha256_file(orphan.path).hex()
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
    recorded_digest_by_path: dict[Path, str | None] | None = None,
) -> tuple[list[Orphan], set[Path]]:
    """Split orphans into (to_prune, relinquished_home_relative_paths).

    An orphan that is not currently safe to prune (see ``is_safe_to_prune``) is
    relinquished: kept on disk and dropped from the receipt."""
    to_prune: list[Orphan] = []
    relinquished: set[Path] = set()
    for orphan in orphans:
        if is_safe_to_prune(
            orphan,
            home=home,
            recorded_sha_by_path=recorded_sha_by_path,
            recorded_digest_by_path=recorded_digest_by_path,
        ):
            to_prune.append(orphan)
        else:
            relinquished.add(orphan.path.relative_to(home))
    return to_prune, relinquished
