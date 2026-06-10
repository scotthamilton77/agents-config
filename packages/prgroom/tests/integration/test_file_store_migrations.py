"""Integration tests for FileStore's schema-migration read branch (§2, §3.7).

Real filesystem, real atomic rewrite, a synthetic migrator injected via the
constructor seam (no global monkeypatching). Pins three coded decisions: a
registered migrator upgrades + rewrites the file in place and the read proceeds;
no migrator trips STATE_SCHEMA_UNKNOWN; a raising migrator surfaces STATE_CORRUPT
and leaves the on-disk file byte-identical (write_atomic runs only on success).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prgroom.prsession.enums import PRPhase
from prgroom.prsession.file import FileStore
from prgroom.prsession.migrations import Migrator
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import SCHEMA_VERSION, PRGroomingState, QuiescenceState
from prgroom.prsession.store import SchemaUnknownError, StateCorruptError

_T = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_OLD = SCHEMA_VERSION - 1


def _current_state(ref: PRRef) -> PRGroomingState:
    return PRGroomingState(
        pr=ref,
        phase=PRPhase.IDLE,
        round=1,
        last_polled_at=_T,
        last_activity_at=_T,
        quiescence=QuiescenceState(),
    )


def _write_old_schema_file(path: Path, ref: PRRef) -> bytes:
    payload = _current_state(ref).to_dict()
    payload["schema_version"] = _OLD
    raw = json.dumps(payload).encode("utf-8")
    path.write_bytes(raw)
    return raw


def _bump_to_current() -> Migrator:
    def migrate(raw: bytes) -> bytes:
        obj = json.loads(raw)
        obj["schema_version"] = SCHEMA_VERSION
        return json.dumps(obj).encode("utf-8")

    return migrate


def test_registered_migrator_upgrades_and_rewrites_in_place(tmp_path: Path) -> None:
    ref = PRRef("octo", "demo", 7)
    state_path = tmp_path / f"{ref.slug()}.json"
    _write_old_schema_file(state_path, ref)
    migrations: Mapping[int, Migrator] = {_OLD: _bump_to_current()}
    store = FileStore(state_dir=tmp_path, migrations=migrations)

    read_back = store.read(ref)

    assert read_back.phase == PRPhase.IDLE
    # File rewritten in place at the current version (write_atomic ran on success).
    on_disk = json.loads(state_path.read_bytes())
    assert on_disk["schema_version"] == SCHEMA_VERSION


def test_no_migrator_for_unknown_version_trips_schema_unknown(tmp_path: Path) -> None:
    ref = PRRef("octo", "demo", 7)
    _write_old_schema_file(tmp_path / f"{ref.slug()}.json", ref)
    store = FileStore(state_dir=tmp_path, migrations={})  # empty: no migrator
    with pytest.raises(SchemaUnknownError):
        store.read(ref)


def test_raising_migrator_surfaces_corrupt_and_leaves_file_byte_identical(
    tmp_path: Path,
) -> None:
    ref = PRRef("octo", "demo", 7)
    state_path = tmp_path / f"{ref.slug()}.json"
    original = _write_old_schema_file(state_path, ref)

    def _boom(_raw: bytes) -> bytes:
        raise ValueError("migrator cannot convert")  # noqa: TRY003

    store = FileStore(state_dir=tmp_path, migrations={_OLD: _boom})
    with pytest.raises(StateCorruptError):
        store.read(ref)

    # HARD requirement: a failed migration never rewrites the file.
    assert state_path.read_bytes() == original


def test_migrator_returning_invalid_json_does_not_corrupt_the_file(tmp_path: Path) -> None:
    # A migrator that returns unparseable bytes WITHOUT raising must not overwrite
    # the good file: validation happens before the atomic write.
    ref = PRRef("octo", "demo", 7)
    state_path = tmp_path / f"{ref.slug()}.json"
    original = _write_old_schema_file(state_path, ref)

    def _garbage(_raw: bytes) -> bytes:
        return b"not valid json{{{"

    store = FileStore(state_dir=tmp_path, migrations={_OLD: _garbage})
    with pytest.raises(StateCorruptError):
        store.read(ref)
    assert state_path.read_bytes() == original


def test_migrator_returning_non_object_json_does_not_corrupt_the_file(tmp_path: Path) -> None:
    # Parseable but non-object JSON (e.g. a bare number) is not valid state; it
    # must be rejected before the write, leaving the good file byte-identical.
    ref = PRRef("octo", "demo", 7)
    state_path = tmp_path / f"{ref.slug()}.json"
    original = _write_old_schema_file(state_path, ref)

    def _scalar(_raw: bytes) -> bytes:
        return b"5"

    store = FileStore(state_dir=tmp_path, migrations={_OLD: _scalar})
    with pytest.raises(StateCorruptError):
        store.read(ref)
    assert state_path.read_bytes() == original


@pytest.mark.parametrize("bogus_version", [True, 1.0, "1"])
def test_non_int_schema_version_is_rejected_not_loaded_as_current(
    tmp_path: Path, bogus_version: object
) -> None:
    # bool subclasses int (True == 1) and 1.0 == 1, so a naive `!= SCHEMA_VERSION`
    # gate would silently accept these as a healthy v1 state. A schema_version that
    # is not a genuine int must route to the migrate-or-reject path (here: no
    # migrator -> STATE_SCHEMA_UNKNOWN), never load as current.
    ref = PRRef("octo", "demo", 7)
    state_path = tmp_path / f"{ref.slug()}.json"
    payload = _current_state(ref).to_dict()
    payload["schema_version"] = bogus_version
    state_path.write_bytes(json.dumps(payload).encode("utf-8"))
    store = FileStore(state_dir=tmp_path, migrations={})
    with pytest.raises(SchemaUnknownError):
        store.read(ref)
