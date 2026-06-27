"""Partition file orphans by on-disk hash before deletion.

A FILE orphan whose current bytes differ from the receipt's recorded sha256 was
modified by the user after we installed it; it is relinquished (kept on disk,
dropped from the receipt) rather than deleted. A directory orphan prunes when the
path is still a real directory or already gone, but a recorded dir path that has
type-drifted to a regular file or symlink is relinquished, not deleted — recursive
CONTENT-drift protection for still-real directories remains deferred. A file that
genuinely vanished prunes (its delete is a harmless no-op); a recorded FILE path
that is present but unreadable *as a regular file* — a directory now occupies it,
or a permission/FS error — is relinquished, never deleted: we cannot confirm it is
still our bytes, and the downstream prune would ``rmtree``/``unlink`` content we
no longer own (the delete would not be a no-op)."""

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
            # Cheap type-drift guard (recursive CONTENT-drift stays deferred): a
            # recorded dir path that is now a regular file or symlink is no longer
            # ours — the user replaced it. Relinquish (keep, drop from the receipt)
            # rather than unlink their file/link. A still-real directory or an
            # already-absent path prunes as before (backup makes a real dir
            # recoverable). is_symlink is tested first so a dir-symlink never counts
            # as a real directory.
            if orphan.path.is_symlink() or (orphan.path.exists() and not orphan.path.is_dir()):
                relinquished.add(orphan.path.relative_to(home))
            else:
                to_prune.append(orphan)
            continue
        rel = orphan.path.relative_to(home)
        recorded = recorded_sha_by_path.get(rel)
        try:
            actual = hashlib.sha256(orphan.path.read_bytes()).hexdigest()
        except FileNotFoundError:
            # Genuinely gone — the delete is a true no-op; prune drops the stale entry.
            to_prune.append(orphan)
            continue
        except OSError:
            # Present but unreadable as a regular file: a directory now occupies the
            # recorded FILE path, or a permission/FS error. We cannot confirm the
            # bytes are still ours, and the downstream prune would rmtree the dir (or
            # unlink content) we no longer own. Fail closed: relinquish (keep on
            # disk, drop from the receipt) rather than delete blind.
            relinquished.add(rel)
            continue
        if recorded is not None and actual != recorded:
            relinquished.add(rel)
        else:
            to_prune.append(orphan)
    return to_prune, relinquished
