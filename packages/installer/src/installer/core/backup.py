"""Path-aware timestamped backup placement (shared by sync and prune).

A target whose immediate parent is one of the prune-managed namespaces is
copied to a sibling ``<namespace>-backup/`` dir under the grandparent; any
other target gets an in-place ``<name>.backup-<ts>`` sibling. Handles both
files (``shutil.copy2``) and directories (``shutil.copytree``).

The ``timestamp`` is interpolated raw into the backup path, so callers MUST
pass a value matching the ``YYYYMMDD-HHMMSS`` contract; ``new_timestamp``
produces one and ``valid_timestamp`` validates a caller-supplied value before
it reaches the filesystem (a value carrying ``../`` would otherwise escape the
backup directory).

Retention: every call to ``back_up`` prunes that target's own older backups
down to the newest ``BACKUP_RETENTION_COUNT``, so repeated installs or prunes
of the same file do not accumulate dated siblings without bound. The prune is
per-target (keyed on the backup filename, which embeds the original name) and
never removes the newest surviving backup, so a target backed up only once is
never left without a recoverable copy.
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

from installer.core import namespaces

# Backup timestamp format: YYYYMMDD-HHMMSS.
_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"

# A caller-supplied timestamp is interpolated raw into the backup filename, so it
# must match the documented YYYYMMDD-HHMMSS contract exactly — otherwise a value
# carrying path separators (``../``) would split into Path components and write
# the backup outside the intended directory.
_TIMESTAMP_RE = re.compile(r"^\d{8}-\d{6}$")

# Newest backups kept per target; every older one is deleted the moment a new
# backup is written for that same target. Arbitrary but generous: enough
# history to recover from a bad install without unbounded per-file
# accumulation. Stated for operators in docs/guide/getting-started.md.
BACKUP_RETENTION_COUNT = 5


def new_timestamp() -> str:
    """Current local wall-clock time as ``YYYYMMDD-HHMMSS``."""
    return datetime.now().astimezone().strftime(_TIMESTAMP_FORMAT)


def valid_timestamp(timestamp: str) -> bool:
    """True when ``timestamp`` matches the ``YYYYMMDD-HHMMSS`` backup contract."""
    return _TIMESTAMP_RE.match(timestamp) is not None


def _backup_path_for(target: Path, timestamp: str) -> Path:
    """Resolve the backup destination for ``target`` (no I/O).

    A target whose parent is a backup-routed namespace (``namespaces.BACKUP``)
    routes to ``<grandparent>/<namespace>-backup/<name>.backup-<ts>``; any other
    target gets an in-place ``<name>.backup-<ts>`` sibling.
    """
    parent = target.parent
    if parent.name in namespaces.BACKUP:
        backup_dir = parent.parent / f"{parent.name}-backup"
        return backup_dir / f"{target.name}.backup-{timestamp}"
    return target.with_name(f"{target.name}.backup-{timestamp}")


def _existing_backups(target: Path, backup_dir: Path) -> list[Path]:
    """Every retention-eligible backup of ``target`` already sitting in
    ``backup_dir``, oldest first.

    A candidate must start with the literal prefix ``<name>.backup-`` *and*
    have everything after it satisfy ``valid_timestamp`` — the same contract
    ``back_up`` enforces on every timestamp it writes. Matching is plain
    string comparison, not a glob pattern, so a target name carrying a glob
    metacharacter (``*``, ``?``, ``[...]``) needs no escaping and cannot
    cross-match another target's backups. The timestamp check additionally
    rejects two things a looser ``<name>.backup-*`` match would wrongly
    accept: a hand-placed file that merely resembles a backup name (e.g.
    ``AGENTS.md.backup-notes``), and a nested-name collision where one
    target's own name is another target's name plus a backup suffix (target
    ``X``'s prefix would otherwise also match target ``X.backup-old``'s own
    backups, named ``X.backup-old.backup-<ts>``).

    Counts a target's backups regardless of whether they landed in-place or
    in a routed ``<namespace>-backup/`` dir — whichever ``backup_dir`` the
    caller resolved. The ``YYYYMMDD-HHMMSS`` suffix sorts lexicographically in
    chronological order, so a plain name sort is enough.
    """
    if not backup_dir.is_dir():
        return []
    prefix = f"{target.name}.backup-"
    return sorted(
        entry
        for entry in backup_dir.iterdir()
        if entry.name.startswith(prefix) and valid_timestamp(entry.name[len(prefix) :])
    )


def _prune_old_backups(target: Path, backup_dir: Path, *, keep: int) -> None:
    """Delete every backup of ``target`` in ``backup_dir`` beyond the newest ``keep``.

    ``keep`` is floored at 1 so a misconfigured non-positive value can never
    delete a target's last remaining backup. A no-op whenever there are ``keep``
    or fewer backups to begin with.
    """
    keep = max(keep, 1)
    existing = _existing_backups(target, backup_dir)
    if len(existing) <= keep:
        return
    for stale in existing[: len(existing) - keep]:
        if stale.is_dir():
            shutil.rmtree(stale)
        else:
            stale.unlink()


def back_up(target: Path, timestamp: str) -> Path:
    """Copy ``target`` (file or directory) to its timestamped backup; return the path.

    Validates ``timestamp`` against the ``YYYYMMDD-HHMMSS`` contract before any
    I/O (``ValueError`` otherwise): the value is interpolated raw into the backup
    path, so this guard is the path-traversal security boundary — safe by default
    rather than relying on every caller to pre-validate.

    Routes via ``_backup_path_for`` (backup-routed namespace -> sibling
    ``<namespace>-backup/``; else in-place), creating the backup dir as needed.
    Directories are copied recursively (``shutil.copytree``), files via
    ``shutil.copy2``.

    After the copy, prunes ``target``'s own older backups down to the newest
    ``BACKUP_RETENTION_COUNT`` (the retention policy — see module docstring).
    """
    if not valid_timestamp(timestamp):
        raise ValueError(f"timestamp must be YYYYMMDD-HHMMSS: {timestamp!r}")  # noqa: TRY003  # single call-site
    dest = _backup_path_for(target, timestamp)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        shutil.copytree(target, dest)
    else:
        shutil.copy2(target, dest)
    _prune_old_backups(target, dest.parent, keep=BACKUP_RETENTION_COUNT)
    return dest
