"""Minimal single-file sync engine (B.2).

Copies one source file to one destination, resolving both ends through a
`ToolAdapter`. The smallest slice of the eventual Phase-7 sync described in
`docs/specs/2026-05-17-python-installer-rewrite.md`: later stories grow it
to walk a `StagingPlan`, route conflicts through the merge registry, and
place path-aware backups.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from installer.core.model import Counters
from installer.core.paths import is_safe_relpath

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.tools.base import ToolAdapter


def sync(
    adapter: ToolAdapter,
    relpath: Path,
    *,
    repo_root: Path,
    home: Path,
    io: IOPort,
    dry_run: bool = False,
) -> Counters:
    """Install one file from the adapter's source tree to its dest tree.

    Resolves ``adapter.source_dir(repo_root) / relpath`` and
    ``adapter.dest_dir(home) / relpath``. Rejects a ``relpath`` that is
    absolute or contains a ``..`` component with `ValueError`, since either
    would let ``Path / relpath`` write outside the adapter tree. Skips when
    the destination
    already holds matching bytes (sha-256); otherwise writes the source
    bytes — unless ``dry_run`` is set, in which case it previews the
    would-be write through ``io`` and touches nothing. Returns a
    `Counters` with exactly one of created / updated / skipped incremented.
    """
    if not is_safe_relpath(relpath):
        raise ValueError(f"relpath escapes the adapter tree: {relpath}")  # noqa: TRY003  # single call-site; subclass not justified

    counters = Counters()
    source = adapter.source_dir(repo_root) / relpath
    dest = adapter.dest_dir(home) / relpath

    content = source.read_bytes()
    dest_exists = dest.is_file()

    if dest_exists and _sha256(dest.read_bytes()) == _sha256(content):
        counters.skipped += 1
        return counters

    if dry_run:
        verb = "update" if dest_exists else "create"
        io.info(f"would {verb} {dest}")
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    if dest_exists:
        counters.updated += 1
    else:
        counters.created += 1
    return counters


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()
