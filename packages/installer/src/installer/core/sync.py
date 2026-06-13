"""Minimal single-file sync engine (B.2 + G.1 backup).

Copies one source file to one destination, resolving both ends through a
`ToolAdapter`. The smallest slice of the eventual Phase-7 sync described in
`docs/specs/2026-05-17-python-installer-rewrite.md`: later stories grow it
to walk a `StagingPlan` and route conflicts through the merge registry.

Path-aware backup (G.1) ports the bash installer's ``backup()``
(`scripts/install.sh:352-388`): before overwriting an existing
destination, the original is copied to a timestamped backup so a failed
write leaves it recoverable.
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from installer.core.model import Counters
from installer.core.paths import is_safe_relpath

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.tools.base import ToolAdapter

# Namespaces whose backups route to a sibling ``<namespace>-backup/`` dir
# rather than an in-place suffix. Mirrors the bash ``backup()`` case list
# (`scripts/install.sh:369-379`).
_SCOPED_NAMESPACES = frozenset({"commands", "skills", "agents", "rules", "formulas"})

# Backup timestamp format, matching ``date +%Y%m%d-%H%M%S`` in
# `scripts/install.sh:365`.
_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"


def sync(
    adapter: ToolAdapter,
    relpath: Path,
    *,
    repo_root: Path,
    home: Path,
    io: IOPort,
    dry_run: bool = False,
    timestamp: str | None = None,
) -> Counters:
    """Install one file from the adapter's source tree to its dest tree.

    Resolves ``adapter.source_dir(repo_root) / relpath`` and
    ``adapter.dest_dir(home) / relpath``. Rejects a ``relpath`` that is
    absolute or contains a ``..`` component with `ValueError`, since either
    would let ``Path / relpath`` write outside the adapter tree. Skips when
    the destination
    already holds matching bytes (sha-256); otherwise writes the source
    bytes — unless ``dry_run`` is set, in which case it previews the
    would-be write through ``io`` and touches nothing.

    When overwriting an existing destination (dest present, bytes differ,
    not ``dry_run``), the original is backed up *before* the write so a
    failed write leaves it recoverable (G.1). ``timestamp`` is the
    backup's ``YYYYMMDD-HHMMSS`` suffix; injected so tests assert exact
    backup names, it defaults to the current local time at the call
    boundary.

    Returns a `Counters` with exactly one of created / updated / skipped
    incremented, plus ``backed_up`` when an overwrite was preserved.
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
        if dest_exists:
            ts = timestamp if timestamp is not None else _now_timestamp()
            _backup(dest, ts)
            counters.backed_up += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    if dest_exists:
        counters.updated += 1
    else:
        counters.created += 1
    return counters


def _backup(dest: Path, timestamp: str) -> None:
    """Copy ``dest`` to a timestamped backup before it is overwritten.

    Ports the routing decision in the bash ``backup()``
    (`scripts/install.sh:360-388`): a destination whose immediate parent
    is a scoped namespace is copied to a sibling ``<namespace>-backup/``
    directory; any other destination gets an in-place
    ``<name>.backup-<ts>`` sibling. Either way the original bytes are
    written before the caller overwrites ``dest``.
    """
    parent = dest.parent
    if parent.name in _SCOPED_NAMESPACES:
        backup_dir = parent.parent / f"{parent.name}-backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{dest.name}.backup-{timestamp}"
    else:
        backup_path = dest.with_name(f"{dest.name}.backup-{timestamp}")
    shutil.copy2(dest, backup_path)


def _now_timestamp() -> str:
    # Local wall-clock time, matching bash ``date +%Y%m%d-%H%M%S`` (local TZ).
    return datetime.now().astimezone().strftime(_TIMESTAMP_FORMAT)


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()
