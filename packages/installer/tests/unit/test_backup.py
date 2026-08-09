"""Unit tests for installer.core.backup.

Each test pins a coded decision in ``back_up`` / ``valid_timestamp``, the shared
path-aware backup placement used by both sync and prune. The focus here is the
safe-by-default validation boundary: ``back_up`` rejects a malformed timestamp
itself, so a caller cannot interpolate a path-traversing value into the backup
path by forgetting to pre-validate. The retention tests below pin the second
coded decision: repeated backups of the same target do not accumulate without
bound, and the newest backup of a target is never the one deleted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core import backup as backup_module
from installer.core.backup import BACKUP_RETENTION_COUNT, back_up

_TS = "20250101-120000"

# Ascending timestamps, one per second, well-formed against the
# YYYYMMDD-HHMMSS contract so `back_up` accepts every one of them.
_TIMESTAMPS = [f"20250101-1200{i:02d}" for i in range(BACKUP_RETENTION_COUNT + 3)]


def test_back_up_rejects_malformed_timestamp_before_any_io(tmp_path: Path) -> None:
    """
    Given a target file and a timestamp that escapes the YYYYMMDD-HHMMSS format
    When back_up is called directly
    Then it raises ValueError and writes no backup (safe-by-default boundary).

    Pins the security guard at the API boundary: the timestamp is interpolated
    raw into the backup path, so a path-separator-bearing value (``../``) must be
    rejected by back_up itself, not left to caller-side validation.
    """
    target = tmp_path / ".claude" / "skills" / "a"
    target.parent.mkdir(parents=True)
    target.write_text("precious")

    with pytest.raises(ValueError, match="YYYYMMDD-HHMMSS"):
        back_up(target, "../evil")

    # No backup escaped into the parent tree.
    assert list(tmp_path.glob("**/*.backup-*")) == []
    assert not (tmp_path / "evil").exists()


def test_back_up_with_valid_timestamp_writes_recoverable_copy(tmp_path: Path) -> None:
    """
    Given a scoped-namespace target file and a well-formed timestamp
    When back_up is called directly
    Then a recoverable copy lands in the sibling <namespace>-backup/ directory.

    Anchors the happy path so the rejection test above is not vacuously green
    (a back_up that raised on every input would also pass the guard test).
    """
    target = tmp_path / ".claude" / "skills" / "retired"
    target.parent.mkdir(parents=True)
    target.write_text("precious")

    dest = back_up(target, _TS)

    assert dest == tmp_path / ".claude" / "skills-backup" / f"retired.backup-{_TS}"
    assert dest.read_text() == "precious"


def test_back_up_prunes_in_place_backups_beyond_retention_count(tmp_path: Path) -> None:
    """
    Given a target whose backups land in-place (parent not a BACKUP namespace)
    When back_up is called more times than BACKUP_RETENTION_COUNT
    Then only the newest BACKUP_RETENTION_COUNT backups survive.

    Pins the retention policy on the in-place branch — an instruction file like
    a flat AGENTS.md, the exact shape the deployed-surface finding named, must
    not accumulate one dated sibling per install forever.
    """
    target = tmp_path / "AGENTS.md"
    target.write_text("v0")

    for ts in _TIMESTAMPS:
        target.write_text(f"content-{ts}")
        back_up(target, ts)

    survivors = sorted(p.name for p in tmp_path.glob("AGENTS.md.backup-*"))
    expected = [f"AGENTS.md.backup-{ts}" for ts in _TIMESTAMPS[-BACKUP_RETENTION_COUNT:]]
    assert survivors == expected


def test_back_up_retention_is_scoped_per_target_within_a_shared_backup_dir(
    tmp_path: Path,
) -> None:
    """
    Given two different targets whose backups route to the same sibling
    <namespace>-backup/ directory
    When one target accumulates more backups than the retention count
    Then only that target's own excess backups are pruned — the other
    target's lone backup is untouched.

    Pins that pruning is keyed on the backed-up file's own name, not on
    everything sharing its backup directory (a routed backup dir like
    skills-backup/ holds many unrelated skills' backups side by side).
    """
    busy = tmp_path / ".claude" / "skills" / "busy"
    quiet = tmp_path / ".claude" / "skills" / "quiet"
    busy.parent.mkdir(parents=True)
    quiet.write_text("quiet-v0")

    for ts in _TIMESTAMPS:
        busy.write_text(f"busy-{ts}")
        back_up(busy, ts)
    back_up(quiet, _TIMESTAMPS[0])

    backup_dir = tmp_path / ".claude" / "skills-backup"
    busy_survivors = sorted(p.name for p in backup_dir.glob("busy.backup-*"))
    expected = [f"busy.backup-{ts}" for ts in _TIMESTAMPS[-BACKUP_RETENTION_COUNT:]]
    assert busy_survivors == expected
    assert (backup_dir / f"quiet.backup-{_TIMESTAMPS[0]}").exists()


def test_back_up_never_deletes_the_only_backup_even_with_non_positive_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a target with exactly one backup and a misconfigured non-positive
    retention count
    When back_up is called again for that same target
    Then the newest backup still survives — the floor of 1 holds regardless of
    the configured count.

    Pins the safety floor: a target must never be left with zero recoverable
    backups, even if BACKUP_RETENTION_COUNT were set to 0 or negative.
    """
    monkeypatch.setattr(backup_module, "BACKUP_RETENTION_COUNT", 0)
    target = tmp_path / "AGENTS.md"
    target.write_text("v0")

    back_up(target, _TIMESTAMPS[0])
    target.write_text("v1")
    back_up(target, _TIMESTAMPS[1])

    survivors = list(tmp_path.glob("AGENTS.md.backup-*"))
    assert survivors == [tmp_path / f"AGENTS.md.backup-{_TIMESTAMPS[1]}"]
    assert survivors[0].read_text() == "v1"


def test_back_up_prunes_stale_directory_backups_recursively(tmp_path: Path) -> None:
    """
    Given a directory target backed up more times than BACKUP_RETENTION_COUNT
    When back_up is called each time
    Then a pruned directory backup is removed recursively (rmtree), not left
    behind as an unremovable non-empty directory.

    A directory backup (``shutil.copytree``) is a tree, not a file — pruning it
    needs ``shutil.rmtree`` rather than ``Path.unlink``, which raises on a
    directory. This pins that branch specifically, distinct from the file-target
    retention tests above.
    """
    target = tmp_path / ".claude" / "skills" / "retired"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("v0")

    for ts in _TIMESTAMPS:
        (target / "SKILL.md").write_text(f"content-{ts}")
        back_up(target, ts)

    backup_dir = tmp_path / ".claude" / "skills-backup"
    survivors = sorted(p.name for p in backup_dir.glob("retired.backup-*"))
    expected = [f"retired.backup-{ts}" for ts in _TIMESTAMPS[-BACKUP_RETENTION_COUNT:]]
    assert survivors == expected
    # The pruned (oldest) backup is gone entirely, not left as an empty dir.
    assert not (backup_dir / f"retired.backup-{_TIMESTAMPS[0]}").exists()
