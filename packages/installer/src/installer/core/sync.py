"""Minimal single-file sync engine (B.2 + G.1 backup).

Copies one source file to one destination, resolving both ends through a
`ToolAdapter`. The smallest slice of the eventual Phase-7 sync described in
`docs/architecture/installer/installer-design.md`: later stories grow it
to walk a `StagingPlan` and route conflicts through the merge registry.

Path-aware backup (G.1) ports the bash installer's ``backup()``
(`scripts/install.sh:352-388`): before overwriting an existing
destination, the original is copied to a timestamped backup so a failed
write leaves it recoverable. The routing decision and timestamp contract
live in `core/backup.py`, shared with the prune flow (G.4).
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from installer.core.backup import back_up, new_timestamp, valid_timestamp
from installer.core.model import Counters
from installer.core.paths import is_safe_relpath

if TYPE_CHECKING:
    from pathlib import Path

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
    boundary. A caller-supplied ``timestamp`` that does not match that
    format is rejected with `ValueError` before any backup is written —
    it is interpolated raw into the backup path, so an unvalidated value
    carrying ``..``/path separators would escape the backup directory.

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
            ts = timestamp if timestamp is not None else new_timestamp()
            if not valid_timestamp(ts):
                raise ValueError(f"timestamp must be YYYYMMDD-HHMMSS: {ts!r}")  # noqa: TRY003  # single call-site; subclass not justified
            back_up(dest, ts)
            counters.backed_up += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    if dest_exists:
        counters.updated += 1
    else:
        counters.created += 1
    return counters


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()
