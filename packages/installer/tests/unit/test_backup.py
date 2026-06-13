"""Unit tests for installer.core.backup.

Each test pins a coded decision in ``back_up`` / ``valid_timestamp``, the shared
path-aware backup placement used by both sync and prune. The focus here is the
safe-by-default validation boundary: ``back_up`` rejects a malformed timestamp
itself, so a caller cannot interpolate a path-traversing value into the backup
path by forgetting to pre-validate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.backup import back_up

_TS = "20250101-120000"


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
