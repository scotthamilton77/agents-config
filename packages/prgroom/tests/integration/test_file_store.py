"""Integration tests for FileStore — the production Store adapter (§2).

Real filesystem, real ``flock``, real atomic rename. These verify the on-disk
contract: round-trip through JSON, the XDG path resolver, atomic replacement,
the corrupt-/unknown-schema error mapping, ref enumeration from filenames, and
delete-as-file-removal.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prgroom.prsession.enums import PRPhase
from prgroom.prsession.file import FileStore, resolve_state_dir, write_atomic
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import SCHEMA_VERSION, PRGroomingState, QuiescenceState
from prgroom.prsession.store import (
    SchemaUnknownError,
    StateCorruptError,
    StateNotFoundError,
)

_T = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _state(ref: PRRef, phase: PRPhase = PRPhase.IDLE) -> PRGroomingState:
    return PRGroomingState(
        pr=ref,
        phase=phase,
        round=1,
        last_polled_at=_T,
        last_activity_at=_T,
        quiescence=QuiescenceState(ci_state="success"),
        last_poll_sha="deadbeef",
    )


def test_write_then_read_round_trips_through_disk(tmp_path: Path) -> None:
    store = FileStore(state_dir=tmp_path)
    ref = PRRef("octo", "demo", 7)
    store.write(ref, _state(ref, PRPhase.FIXES_PENDING))
    read_back = store.read(ref)
    assert read_back.phase == PRPhase.FIXES_PENDING
    assert read_back.last_poll_sha == "deadbeef"


def test_state_file_lands_at_slug_named_path(tmp_path: Path) -> None:
    store = FileStore(state_dir=tmp_path)
    ref = PRRef("octo", "demo", 7)
    store.write(ref, _state(ref))
    assert (tmp_path / "octo-demo-7.json").is_file()


def test_read_missing_raises_state_not_found(tmp_path: Path) -> None:
    store = FileStore(state_dir=tmp_path)
    with pytest.raises(StateNotFoundError):
        store.read(PRRef("octo", "demo", 1))


def test_write_atomic_leaves_no_partial_file_and_no_tempfiles(tmp_path: Path) -> None:
    target = tmp_path / "octo-demo-7.json"
    write_atomic(target, b'{"ok": true}')
    assert json.loads(target.read_text()) == {"ok": True}
    # No leftover NamedTemporaryFile siblings.
    siblings = [p.name for p in tmp_path.iterdir() if p != target]
    assert siblings == []


def test_write_atomic_overwrites_existing_target(tmp_path: Path) -> None:
    target = tmp_path / "f.json"
    write_atomic(target, b"old")
    write_atomic(target, b"new")
    assert target.read_bytes() == b"new"


def test_write_atomic_cleans_up_tempfile_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the final rename fails, no partial tempfile may be left behind and the
    # target must be untouched (the prior content, if any, survives).
    import prgroom.prsession.file as file_mod

    def _boom(_src: object, _dst: object) -> None:
        raise OSError("rename failed")  # noqa: TRY003  # test stub simulating a rename failure

    monkeypatch.setattr(file_mod.os, "replace", _boom)
    target = tmp_path / "f.json"
    with pytest.raises(OSError, match="rename failed"):
        write_atomic(target, b"data")
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_corrupt_json_raises_state_corrupt(tmp_path: Path) -> None:
    ref = PRRef("octo", "demo", 7)
    (tmp_path / "octo-demo-7.json").write_text("{ this is not json")
    with pytest.raises(StateCorruptError):
        FileStore(state_dir=tmp_path).read(ref)


def test_unknown_schema_version_raises_schema_unknown(tmp_path: Path) -> None:
    ref = PRRef("octo", "demo", 7)
    payload = _state(ref).to_dict()
    payload["schema_version"] = SCHEMA_VERSION + 1
    (tmp_path / "octo-demo-7.json").write_text(json.dumps(payload))
    with pytest.raises(SchemaUnknownError):
        FileStore(state_dir=tmp_path).read(ref)


def test_lock_releases_on_context_exit(tmp_path: Path) -> None:
    store = FileStore(state_dir=tmp_path)
    ref = PRRef("octo", "demo", 7)
    with store.lock(ref):
        pass
    with store.lock(ref):
        pass  # re-acquire proves release


def test_lock_releases_even_when_body_raises(tmp_path: Path) -> None:
    store = FileStore(state_dir=tmp_path)
    ref = PRRef("octo", "demo", 7)
    with pytest.raises(RuntimeError), store.lock(ref):
        raise RuntimeError("boom")
    with store.lock(ref):
        pass


def test_list_refs_parses_slug_filenames(tmp_path: Path) -> None:
    store = FileStore(state_dir=tmp_path)
    refs = [PRRef("octo", "demo", n) for n in (1, 2)]
    for ref in refs:
        store.write(ref, _state(ref))
    assert sorted(store.list_refs(), key=lambda r: r.number) == refs


def test_list_refs_empty_when_dir_absent(tmp_path: Path) -> None:
    store = FileStore(state_dir=tmp_path / "does-not-exist-yet")
    assert store.list_refs() == []


def test_list_refs_skips_filenames_that_are_not_valid_slugs(tmp_path: Path) -> None:
    # A *.json file that does not match <owner>-<repo>-<n> is ignored, not crashed
    # on — the dir may hold unrelated JSON.
    store = FileStore(state_dir=tmp_path)
    ref = PRRef("octo", "demo", 1)
    store.write(ref, _state(ref))
    (tmp_path / "nonumbertail.json").write_text("{}")  # no hyphen, no numeric tail
    (tmp_path / "12345.json").write_text("{}")  # number only, empty owner-repo head
    (tmp_path / "solo-5.json").write_text("{}")  # numeric tail but head lacks owner/repo split
    assert store.list_refs() == [ref]


def test_delete_removes_the_state_file(tmp_path: Path) -> None:
    store = FileStore(state_dir=tmp_path)
    ref = PRRef("octo", "demo", 7)
    store.write(ref, _state(ref))
    store.delete(ref)
    assert not (tmp_path / "octo-demo-7.json").exists()


def test_delete_is_idempotent_on_unknown_ref(tmp_path: Path) -> None:
    FileStore(state_dir=tmp_path).delete(PRRef("octo", "demo", 404))


def test_resolve_state_dir_honors_xdg_state_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", "/tmp/xdg-state")  # noqa: S108  # test env, no write
    assert resolve_state_dir() == Path("/tmp/xdg-state/prgroom")  # noqa: S108


def test_resolve_state_dir_falls_back_to_local_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", "/home/tester")
    assert resolve_state_dir() == Path("/home/tester/.local/state/prgroom")


def test_resolve_state_dir_ignores_blank_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    # An empty XDG_STATE_HOME must be treated as unset (POSIX env convention),
    # not as the relative path "prgroom".
    monkeypatch.setenv("XDG_STATE_HOME", "")
    monkeypatch.setenv("HOME", "/home/tester")
    assert resolve_state_dir() == Path("/home/tester/.local/state/prgroom")
