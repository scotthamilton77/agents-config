"""Unit tests for installer.core.backup.

Each test pins a coded decision in ``back_up`` / ``valid_timestamp``, the shared
path-aware backup placement used by both sync and prune. The focus here is the
safe-by-default validation boundary: ``back_up`` rejects a malformed timestamp
itself, so a caller cannot interpolate a path-traversing value into the backup
path by forgetting to pre-validate. The retention tests below pin retention
itself: repeated backups of the same target do not accumulate without bound,
and the newest backup of a target is never the one deleted.
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
    Given a target whose backups land in-place (parent not a BACKUP namespace),
    created in REVERSE timestamp order (newest first, oldest last)
    When back_up is called more times than BACKUP_RETENTION_COUNT
    Then only the backups with the newest BACKUP_RETENTION_COUNT timestamp
    VALUES survive — regardless of the order they were created in.

    Pins the retention policy on the in-place branch — a flat instruction file
    like AGENTS.md must not accumulate one dated sibling per install forever.
    Creating in reverse order is deliberate: it distinguishes sorting by the
    filename-embedded timestamp value (correct) from sorting by directory
    iteration or creation order (wrong) — under creation-order sorting, this
    exact input would keep the OLDEST timestamps and discard the newest,
    the opposite of what's asserted below.
    """
    target = tmp_path / "AGENTS.md"
    target.write_text("v0")

    for ts in reversed(_TIMESTAMPS):
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
    <namespace>-backup/ directory — quiet's lone backup (at the globally
    OLDEST timestamp used anywhere in this test) already exists before busy
    accumulates its own backups in REVERSE timestamp order (newest first,
    oldest last)
    When busy is pruned repeatedly as it accumulates more backups than the
    retention count
    Then only busy's own excess backups are pruned, by timestamp VALUE
    rather than creation order — quiet's backup, present throughout every
    one of busy's prune cycles and old enough to be an easy target, is
    never touched.

    Pins that pruning is keyed on the backed-up file's own name, not on
    everything sharing its backup directory (a routed backup dir like
    skills-backup/ holds many unrelated skills' backups side by side).
    Quiet's backup is created FIRST specifically so it is exposed to every
    one of busy's prune cycles, not created only after busy has finished
    pruning — an implementation that scoped pruning to the shared directory
    as a whole, rather than to the target's own name, would otherwise have
    nothing else in the directory to wrongly sweep up when it ran. Giving
    quiet the globally oldest timestamp makes it the first casualty such an
    unscoped implementation would take. Reverse-order creation of busy's own
    backups is separately deliberate: it distinguishes sorting by the
    filename-embedded timestamp value (correct) from sorting by creation
    order (wrong).
    """
    busy = tmp_path / ".claude" / "skills" / "busy"
    quiet = tmp_path / ".claude" / "skills" / "quiet"
    busy.parent.mkdir(parents=True)
    quiet.write_text("quiet-v0")
    back_up(quiet, _TIMESTAMPS[0])

    for ts in reversed(_TIMESTAMPS):
        busy.write_text(f"busy-{ts}")
        back_up(busy, ts)

    backup_dir = tmp_path / ".claude" / "skills-backup"
    busy_survivors = sorted(p.name for p in backup_dir.glob("busy.backup-*"))
    expected = [f"busy.backup-{ts}" for ts in _TIMESTAMPS[-BACKUP_RETENTION_COUNT:]]
    assert busy_survivors == expected
    assert (backup_dir / f"quiet.backup-{_TIMESTAMPS[0]}").exists()


def test_back_up_treats_glob_metacharacters_in_a_target_name_literally(
    tmp_path: Path,
) -> None:
    """
    Given a target whose own name contains a glob metacharacter (``*``),
    sharing a backup directory with an unrelated target whose name that
    wildcard would incorrectly also match
    When the metacharacter-bearing target's backups are pruned
    Then only its own literal name is matched — the unrelated target's
    backup, which an unescaped ``*`` wildcard would sweep in as a false
    match, survives untouched.

    Not a hypothetical input: this repo ships a real file named
    ``*.instructions.md`` (`.github/instructions/`). ``_existing_backups``
    must treat ``target.name`` as a literal string, not a pattern.
    """
    weird = tmp_path / ".claude" / "skills" / "note*"
    decoy = tmp_path / ".claude" / "skills" / "noteX"
    weird.parent.mkdir(parents=True)
    # An unescaped "note*.backup-*" pattern also matches "noteX.backup-<ts>",
    # so the decoy must exist *before* weird's retention-triggering loop runs
    # for the false match to have anything to sweep up.
    decoy.write_text("decoy-v0")
    back_up(decoy, _TIMESTAMPS[0])

    for ts in _TIMESTAMPS[1:]:
        weird.write_text(f"weird-{ts}")
        back_up(weird, ts)

    backup_dir = tmp_path / ".claude" / "skills-backup"
    all_names = sorted(p.name for p in backup_dir.iterdir())
    weird_survivors = [n for n in all_names if n.startswith("note*.backup-")]
    expected = [f"note*.backup-{ts}" for ts in _TIMESTAMPS[1:][-BACKUP_RETENTION_COUNT:]]
    assert weird_survivors == expected
    assert f"noteX.backup-{_TIMESTAMPS[0]}" in all_names


def test_back_up_ignores_a_backup_shaped_file_with_a_non_timestamp_suffix(
    tmp_path: Path,
) -> None:
    """
    Given a hand-placed file that merely resembles a backup name — the text
    after ``.backup-`` is not a well-formed timestamp
    When the real target accumulates enough real backups to trigger pruning
    Then the hand-placed file is never counted toward retention and is never
    pruned — it survives untouched.

    Pins the timestamp-suffix check: a looser ``<name>.backup-*`` match would
    treat a file like ``AGENTS.md.backup-notes`` as one of AGENTS.md's own
    dated backups.
    """
    target = tmp_path / "AGENTS.md"
    target.write_text("v0")
    decoy = tmp_path / "AGENTS.md.backup-notes"
    decoy.write_text("hand-written notes, not a backup")

    for ts in _TIMESTAMPS:
        target.write_text(f"content-{ts}")
        back_up(target, ts)

    assert decoy.read_text() == "hand-written notes, not a backup"
    all_backup_like = sorted(p.name for p in tmp_path.glob("AGENTS.md.backup-*"))
    real_survivors = [n for n in all_backup_like if n != decoy.name]
    expected = [f"AGENTS.md.backup-{ts}" for ts in _TIMESTAMPS[-BACKUP_RETENTION_COUNT:]]
    assert real_survivors == expected
    assert decoy.name in all_backup_like


def test_back_up_does_not_cross_match_a_nested_name_collision(tmp_path: Path) -> None:
    """
    Given two distinct targets sharing a backup directory, where one target's
    own name equals another target's name plus a backup suffix (targets
    "note" and "note.backup-old")
    When the shorter-named target accumulates enough backups to trigger
    pruning
    Then the longer-named target's own backups (named
    "note.backup-old.backup-<ts>") are never counted toward "note"'s
    retention and are never pruned by it.

    Without the timestamp-suffix check, "note.backup-old.backup-<ts>" starts
    with "note"'s own prefix ("note.backup-"), so an unconstrained prefix (or
    escaped-glob) match would sweep it into "note"'s retention set.
    """
    note = tmp_path / ".claude" / "skills" / "note"
    collider = tmp_path / ".claude" / "skills" / "note.backup-old"
    note.parent.mkdir(parents=True)
    collider.write_text("collider-v0")
    back_up(collider, _TIMESTAMPS[0])

    for ts in _TIMESTAMPS[1:]:
        note.write_text(f"note-{ts}")
        back_up(note, ts)

    backup_dir = tmp_path / ".claude" / "skills-backup"
    all_names = sorted(p.name for p in backup_dir.iterdir())
    collider_backup = f"note.backup-old.backup-{_TIMESTAMPS[0]}"
    expected_note_backups = [
        f"note.backup-{ts}" for ts in _TIMESTAMPS[1:][-BACKUP_RETENTION_COUNT:]
    ]
    assert all_names == sorted([collider_backup, *expected_note_backups])


@pytest.mark.parametrize("retention_count", [0, -1])
def test_back_up_never_deletes_the_only_backup_even_with_non_positive_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retention_count: int
) -> None:
    """
    Given a target with exactly one backup and a misconfigured non-positive
    retention count (zero, or negative)
    When back_up is called again for that same target
    Then the newest backup still survives — the floor of 1 holds regardless of
    the configured count.

    Pins the safety floor (``max(keep, 1)`` in ``_prune_old_backups``): a
    target must never be left with zero recoverable backups, whether
    ``BACKUP_RETENTION_COUNT`` were misconfigured to exactly 0 or to something
    negative. Without the floor either value would prune every existing
    backup (``len(existing) <= keep`` is false for both, so the loop would
    run and take everything), so both are covered here rather than only 0.
    """
    monkeypatch.setattr(backup_module, "BACKUP_RETENTION_COUNT", retention_count)
    target = tmp_path / "AGENTS.md"
    target.write_text("v0")

    back_up(target, _TIMESTAMPS[0])

    # The lone-backup case, pinned on its own before a second backup exists:
    # a single backup must never be pruned away, regardless of what a
    # misconfigured retention count says.
    first_backup = tmp_path / f"AGENTS.md.backup-{_TIMESTAMPS[0]}"
    assert list(tmp_path.glob("AGENTS.md.backup-*")) == [first_backup]

    target.write_text("v1")
    back_up(target, _TIMESTAMPS[1])

    survivors = list(tmp_path.glob("AGENTS.md.backup-*"))
    assert survivors == [tmp_path / f"AGENTS.md.backup-{_TIMESTAMPS[1]}"]
    assert survivors[0].read_text() == "v1"


def test_existing_backups_returns_empty_for_a_backup_dir_that_does_not_exist_yet(
    tmp_path: Path,
) -> None:
    """
    Given a backup_dir that has never been created
    When _existing_backups is asked for a target's backups in it
    Then it returns an empty list rather than raising.
    """
    target = tmp_path / "AGENTS.md"
    missing_backup_dir = tmp_path / "does-not-exist"

    assert backup_module._existing_backups(target, missing_backup_dir) == []


def test_backup_retention_count_is_5() -> None:
    """
    Pins the retention policy's actual number. The other retention tests
    derive their expected survivor counts from ``BACKUP_RETENTION_COUNT``
    itself, so a change to that constant would pass them silently; this test
    is the one place a change to the number is itself a visible pin.
    """
    assert BACKUP_RETENTION_COUNT == 5


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
