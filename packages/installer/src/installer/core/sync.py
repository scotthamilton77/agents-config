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
import shutil
from typing import TYPE_CHECKING

from installer.core.backup import back_up, new_timestamp, valid_timestamp
from installer.core.model import Counters
from installer.core.paths import is_safe_relpath

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan
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


def sync_plan(
    adapter: ToolAdapter,
    plan: StagingPlan,
    *,
    home: Path,
    io: IOPort,
    dry_run: bool = False,
    timestamp: str | None = None,
) -> Counters:
    """Walk a ``StagingPlan`` and install every item under the adapter's dest root.

    The plan-walking install sync (W1): the in-memory replacement for the bash
    installer's temp-dir-to-home copy. For each item:

    - a FILE item (eager ``content``) is hash-compared against the dest; an
      unchanged dest is skipped, a differing dest is backed up *before* the
      overwrite, and the bytes are written with a deterministic mode bit
      (``0o755`` when ``executable`` else ``0o644``);
    - a DIR item materialises its ``source_path`` tree — backing up then cleanly
      replacing an existing dest — and overlays its ``dir_overrides`` (override
      wins on a name collision).

    ``dry_run`` previews would-be writes through ``io`` and touches nothing.
    ``timestamp`` is the backup suffix (defaults to current local time); a
    caller-supplied value is validated against ``YYYYMMDD-HHMMSS`` before any
    backup is written, since it is interpolated raw into the backup path. A
    ``dest_relpath`` that is absolute or carries a ``..`` component is rejected
    with `ValueError` before any write. Path containment is **lexical** — like
    ``sync``/``dump``, symlinked dest *parents* are not resolved, so the guard
    is not resolved-path safety. The walk is **non-transactional**: a failure on
    item N leaves items 1..N-1 installed (matching the bash streaming installer;
    no rollback). Returns aggregate `Counters`.
    """
    counters = Counters()
    dest_dir = adapter.dest_dir(home)
    for item in plan.items.values():
        if not is_safe_relpath(item.dest_relpath):
            raise ValueError(f"dest_relpath escapes the dest tree: {item.dest_relpath}")  # noqa: TRY003  # single call-site; subclass not justified
        dest = dest_dir / item.dest_relpath
        content = item.content
        if content is None:
            _install_dir(
                dest,
                item.source_path,
                plan.dir_overrides.get(item.dest_relpath, {}),
                io=io,
                dry_run=dry_run,
                timestamp=timestamp,
                counters=counters,
            )
        else:
            _install_file(
                dest,
                content,
                executable=item.executable,
                io=io,
                dry_run=dry_run,
                timestamp=timestamp,
                counters=counters,
            )
    return counters


def _install_file(
    dest: Path,
    content: bytes,
    *,
    executable: bool,
    io: IOPort,
    dry_run: bool,
    timestamp: str | None,
    counters: Counters,
) -> None:
    """Install one FILE item: hash-skip an unchanged dest, back up a differing
    dest before the overwrite, and write the bytes with a deterministic mode
    bit (``0o755`` when ``executable`` else ``0o644``). Mutates ``counters``.

    A dest already occupied by a non-file (a directory) is rejected with
    `ValueError` rather than crashing the walk with a raw ``IsADirectoryError`` —
    matching ``dump``'s type-guard so the CLI surfaces a clean error."""
    if dest.exists() and not dest.is_file():
        raise ValueError(f"dest exists but is not a file: {dest}")  # noqa: TRY003  # single call-site; subclass not justified
    dest_exists = dest.is_file()
    if dest_exists and _sha256(dest.read_bytes()) == _sha256(content):
        counters.skipped += 1
        return
    if not dry_run:
        if dest_exists:
            _back_up(dest, timestamp, counters)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        dest.chmod(0o755 if executable else 0o644)
    _record_write(dest, dest_exists=dest_exists, io=io, dry_run=dry_run, counters=counters)


def _install_dir(
    dest: Path,
    source_path: Path,
    overrides: Mapping[Path, bytes],
    *,
    io: IOPort,
    dry_run: bool,
    timestamp: str | None,
    counters: Counters,
) -> None:
    """Materialise one DIR item: back up then cleanly replace an existing dest,
    copy the ``source_path`` tree, then overlay ``overrides`` (override wins on
    a name collision, matching dump-time semantics). Mutates ``counters``.

    A missing or non-directory ``source_path``, or a dest already occupied by a
    non-directory (a file), is rejected with `ValueError` rather than crashing
    the walk with a raw ``FileNotFoundError`` / ``NotADirectoryError``. Symlinks
    in the source tree are dereferenced by ``copytree`` (its default) — a
    behavioural choice flagged for the golden-master parity pass."""
    if not source_path.is_dir():
        raise ValueError(f"DIR item source is not a directory: {source_path}")  # noqa: TRY003  # single call-site; subclass not justified
    if dest.exists() and not dest.is_dir():
        raise ValueError(f"dest exists but is not a directory: {dest}")  # noqa: TRY003  # single call-site; subclass not justified
    dest_exists = dest.exists()
    if not dry_run:
        if dest_exists:
            _back_up(dest, timestamp, counters)
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_path, dest)
        for inner, inner_content in overrides.items():
            if not is_safe_relpath(inner):
                raise ValueError(f"dir override relpath escapes the dir: {inner}")  # noqa: TRY003  # single call-site; subclass not justified
            inner_dest = dest / inner
            inner_dest.parent.mkdir(parents=True, exist_ok=True)
            inner_dest.write_bytes(inner_content)
    _record_write(dest, dest_exists=dest_exists, io=io, dry_run=dry_run, counters=counters)


def _record_write(
    dest: Path, *, dest_exists: bool, io: IOPort, dry_run: bool, counters: Counters
) -> None:
    """Preview the would-be write under ``dry_run`` and tally it as a create or
    update. Shared by the file and dir installers; mutates ``counters``."""
    if dry_run:
        verb = "update" if dest_exists else "create"
        io.info(f"would {verb} {dest}")
    if dest_exists:
        counters.updated += 1
    else:
        counters.created += 1


def _back_up(target: Path, timestamp: str | None, counters: Counters) -> None:
    """Back up ``target`` (file or dir) before an overwrite, resolving and
    validating the timestamp at the boundary (raw-interpolated into the backup
    path, so the validation is the path-traversal guard). Mutates ``counters``."""
    ts = timestamp if timestamp is not None else new_timestamp()
    if not valid_timestamp(ts):
        raise ValueError(f"timestamp must be YYYYMMDD-HHMMSS: {ts!r}")  # noqa: TRY003  # single call-site; subclass not justified
    back_up(target, ts)
    counters.backed_up += 1


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()
