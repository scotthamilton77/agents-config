"""Path-aware timestamped backup placement (shared by sync and prune).

Single home for the bash ``backup()`` routing decision
(``scripts/install.sh:352-388``): a target whose immediate parent is one of the
prune-managed namespaces is copied to a sibling ``<namespace>-backup/`` dir
under the grandparent; any other target gets an in-place ``<name>.backup-<ts>``
sibling. Handles both files (``shutil.copy2``) and directories
(``shutil.copytree``), mirroring the bash ``cp`` / ``cp -R`` split.

The ``timestamp`` is interpolated raw into the backup path, so callers MUST
pass a value matching the ``YYYYMMDD-HHMMSS`` contract; ``new_timestamp``
produces one and ``valid_timestamp`` validates a caller-supplied value before
it reaches the filesystem (a value carrying ``../`` would otherwise escape the
backup directory).
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

# Namespaces whose backups route to a sibling ``<namespace>-backup/`` dir rather
# than an in-place suffix (bash ``backup()`` case list, scripts/install.sh:369-379).
_SCOPED_NAMESPACES = frozenset({"commands", "skills", "agents", "rules", "formulas"})

# Backup timestamp format, matching ``date +%Y%m%d-%H%M%S`` (scripts/install.sh:365).
_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"

# A caller-supplied timestamp is interpolated raw into the backup filename, so it
# must match the documented YYYYMMDD-HHMMSS contract exactly — otherwise a value
# carrying path separators (``../``) would split into Path components and write
# the backup outside the intended directory.
_TIMESTAMP_RE = re.compile(r"^\d{8}-\d{6}$")


def new_timestamp() -> str:
    """Current local wall-clock time as ``YYYYMMDD-HHMMSS`` (bash local-TZ ``date``)."""
    return datetime.now().astimezone().strftime(_TIMESTAMP_FORMAT)


def valid_timestamp(timestamp: str) -> bool:
    """True when ``timestamp`` matches the ``YYYYMMDD-HHMMSS`` backup contract."""
    return _TIMESTAMP_RE.match(timestamp) is not None


def backup_path_for(target: Path, timestamp: str) -> Path:
    """Resolve the backup destination for ``target`` (no I/O).

    A target whose parent is a scoped namespace routes to
    ``<grandparent>/<namespace>-backup/<name>.backup-<ts>``; any other target
    gets an in-place ``<name>.backup-<ts>`` sibling.
    """
    parent = target.parent
    if parent.name in _SCOPED_NAMESPACES:
        backup_dir = parent.parent / f"{parent.name}-backup"
        return backup_dir / f"{target.name}.backup-{timestamp}"
    return target.with_name(f"{target.name}.backup-{timestamp}")


def back_up(target: Path, timestamp: str) -> Path:
    """Copy ``target`` (file or directory) to its timestamped backup; return the path.

    Creates the sibling ``<namespace>-backup/`` directory when routing there.
    Directories are copied recursively (``shutil.copytree``), files via
    ``shutil.copy2`` — mirroring the bash ``cp -R`` / ``cp`` split.
    """
    dest = backup_path_for(target, timestamp)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        shutil.copytree(target, dest)
    else:
        shutil.copy2(target, dest)
    return dest
