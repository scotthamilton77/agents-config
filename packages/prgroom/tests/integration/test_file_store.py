"""Integration tests for FileStore — the production Store adapter (§2).

Real filesystem, real ``flock``, real atomic rename. These verify the on-disk
contract: round-trip through JSON, the XDG path resolver, atomic replacement,
the corrupt-/unknown-schema error mapping, ref enumeration from state bodies, and
delete-as-file-removal.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prgroom.errors import ErrorCode, PreconditionError, exit_code_for_tier
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


def test_second_invocation_exits_75_naming_pid(tmp_path: Path) -> None:
    # §2 concurrency posture: a second invocation while one holds the lock must
    # exit IMMEDIATELY (non-blocking) with PRECONDITION_LOCK_HELD (exit 75), naming
    # the holder pid. Two FileStore instances on the same dir use separate open()
    # fds → separate flock file descriptions → they genuinely contend, in-process,
    # no subprocess/fork needed.
    store_a = FileStore(state_dir=tmp_path)
    store_b = FileStore(state_dir=tmp_path)
    ref = PRRef("octo", "demo", 7)
    with store_a.lock(ref), pytest.raises(PreconditionError) as exc_info, store_b.lock(ref):
        pass  # pragma: no cover - acquire raises before the body runs
    err = exc_info.value
    assert err.code == ErrorCode.PRECONDITION_LOCK_HELD
    assert exit_code_for_tier(err) == 75
    assert ref.display() in err.detail
    # The holder wrote its pid into the lock file, so the contender names it.
    assert f"pid {os.getpid()}" in err.detail


def test_lock_reacquirable_after_contention_resolves(tmp_path: Path) -> None:
    # The contender's failed non-blocking acquire must not corrupt the lock: once
    # the holder releases, a later acquire succeeds normally.
    store_a = FileStore(state_dir=tmp_path)
    store_b = FileStore(state_dir=tmp_path)
    ref = PRRef("octo", "demo", 7)
    with store_a.lock(ref), pytest.raises(PreconditionError), store_b.lock(ref):
        pass  # pragma: no cover
    with store_b.lock(ref):
        pass  # the holder released; the contender can now acquire


def test_read_lock_pid_returns_none_when_path_is_unreadable(tmp_path: Path) -> None:
    # The pid read is best-effort: an OSError on read (here, a directory standing in
    # for the lock path → IsADirectoryError, an OSError subclass) yields None, which
    # the contention error renders as `(pid unknown)` rather than crashing.
    from prgroom.prsession.file import _read_lock_pid

    a_directory = tmp_path / "not-a-lock-file"
    a_directory.mkdir()
    assert _read_lock_pid(a_directory) is None


def test_contention_pid_unknown_when_lock_file_empty(tmp_path: Path) -> None:
    # Defensive: if the lock file exists but carries no readable pid (crash between
    # create and write, or a pre-existing empty file), the contender reports
    # `(pid unknown)` rather than guessing — and never defaults to its OWN pid.
    store_a = FileStore(state_dir=tmp_path)
    store_b = FileStore(state_dir=tmp_path)
    ref = PRRef("octo", "demo", 7)
    lock_path = tmp_path / f"{ref.slug()}.lock"

    with store_a.lock(ref):
        # Blank the holder-written pid out from under the live holder to model the
        # empty/unparseable case the contender must tolerate.
        lock_path.write_text("")
        with pytest.raises(PreconditionError) as exc_info, store_b.lock(ref):
            pass  # pragma: no cover
    assert "pid unknown" in exc_info.value.detail
    assert str(os.getpid()) not in exc_info.value.detail


def test_list_refs_enumerates_written_prs(tmp_path: Path) -> None:
    store = FileStore(state_dir=tmp_path)
    refs = [PRRef("octo", "demo", n) for n in (1, 2)]
    for ref in refs:
        store.write(ref, _state(ref))
    assert sorted(store.list_refs(), key=lambda r: r.number) == refs


def test_list_refs_round_trips_hyphenated_owner_and_repo(tmp_path: Path) -> None:
    # Regression: the slug <owner>-<repo>-<n> is a *lossy* filename encoding when
    # owner or repo contains the '-' delimiter. Enumeration must recover the exact
    # ref from the authoritative `pr` object in the file body, never by reverse-
    # parsing the filename.
    store = FileStore(state_dir=tmp_path)
    ref = PRRef("scott-hamilton", "agents-config", 8)
    store.write(ref, _state(ref))
    assert store.list_refs() == [ref]


def test_list_refs_empty_when_dir_absent(tmp_path: Path) -> None:
    store = FileStore(state_dir=tmp_path / "does-not-exist-yet")
    assert store.list_refs() == []


def test_list_refs_skips_files_that_are_not_current_prgroom_state(tmp_path: Path) -> None:
    # The state dir may hold unrelated JSON. Enumeration mirrors read()'s gate —
    # the payload must be an object at the current schema_version with a dict `pr`
    # — and skips anything else, never crashing `sweep` or returning a spurious PR.
    store = FileStore(state_dir=tmp_path)
    ref = PRRef("octo", "demo", 1)
    store.write(ref, _state(ref))
    valid_pr = {"owner": "x", "repo": "y", "number": 3}
    (tmp_path / "unparseable.json").write_text("{ this is not json")  # bad JSON
    (tmp_path / "array.json").write_text("[1, 2, 3]")  # JSON, but not an object
    (tmp_path / "no-schema.json").write_text(json.dumps({"pr": valid_pr}))  # no schema_version
    (tmp_path / "future-schema.json").write_text(
        json.dumps({"schema_version": SCHEMA_VERSION + 1, "pr": valid_pr})
    )  # foreign / future schema
    # bool/float schema_version (True==1, 1.0==1) must NOT enumerate as current —
    # enumeration stays consistent with read()'s type-strict gate.
    (tmp_path / "bool-schema.json").write_text(json.dumps({"schema_version": True, "pr": valid_pr}))
    (tmp_path / "float-schema.json").write_text(json.dumps({"schema_version": 1.0, "pr": valid_pr}))
    (tmp_path / "pr-not-object.json").write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "pr": "nope"})
    )  # `pr` is not a dict
    (tmp_path / "partial-pr.json").write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "pr": {"owner": "x"}})
    )  # incomplete `pr`
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
