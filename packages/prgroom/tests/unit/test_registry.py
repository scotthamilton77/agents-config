"""Tests for the store-adapter selector (§2 "Selection at runtime").

Pins the coded decisions: name resolution and precedence (flag > env > default
file), the concrete adapter each name yields, and the terminal user-error for
the deferred `bd` adapter and any unknown name. Uses the real FileStore (a fake
would not prove the file branch returns the production adapter).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from prgroom.errors import ErrorCode, PreconditionError, Tier
from prgroom.prsession.file import FileStore
from prgroom.prsession.legacy_export import LegacyExportStore
from prgroom.prsession.registry import resolve_store


def test_explicit_file_name_yields_legacy_wrapped_filestore(tmp_path: Path) -> None:
    # The "file" store is wrapped so it also emits merge-guard's legacy
    # pr-inventory at persist time; the inner adapter is still the production
    # FileStore.
    store = resolve_store("file", env={}, state_dir=tmp_path)
    assert isinstance(store, LegacyExportStore)
    assert isinstance(store._inner, FileStore)


def test_injected_env_threads_into_legacy_export_dir(tmp_path: Path) -> None:
    # The injected env must drive the legacy-inventory dir, not the real
    # os.environ — otherwise a test selecting the file store would write into
    # the caller's real ~/.claude/state/pr-inventory (isolation seam leak).
    legacy_dir = tmp_path / "pr-inventory"
    store = resolve_store(
        "file",
        env={"PRGROOM_LEGACY_INVENTORY_DIR": str(legacy_dir)},
        state_dir=tmp_path,
    )
    assert isinstance(store, LegacyExportStore)
    assert store._export_dir == legacy_dir


def test_default_when_no_flag_no_env_is_file(tmp_path: Path) -> None:
    store = resolve_store(None, env={}, state_dir=tmp_path)
    assert isinstance(store, LegacyExportStore)
    assert isinstance(store._inner, FileStore)


def test_env_selects_when_no_flag(tmp_path: Path) -> None:
    store = resolve_store(None, env={"PRGROOM_STORE": "file"}, state_dir=tmp_path)
    assert isinstance(store, LegacyExportStore)
    assert isinstance(store._inner, FileStore)


def test_flag_beats_env(tmp_path: Path) -> None:
    # Flag says file, env says bd: flag wins, so we get a FileStore (no error).
    store = resolve_store("file", env={"PRGROOM_STORE": "bd"}, state_dir=tmp_path)
    assert isinstance(store, LegacyExportStore)
    assert isinstance(store._inner, FileStore)


def test_bd_is_a_terminal_user_error(tmp_path: Path) -> None:
    with pytest.raises(PreconditionError) as exc:
        resolve_store("bd", env={}, state_dir=tmp_path)
    assert exc.value.code == ErrorCode.PRECONDITION_STORE_UNAVAILABLE
    assert exc.value.tier == Tier.PRECONDITION_USER_ERROR
    assert "bd" in str(exc.value)


def test_unknown_name_is_a_terminal_user_error(tmp_path: Path) -> None:
    with pytest.raises(PreconditionError) as exc:
        resolve_store("frobnicate", env={}, state_dir=tmp_path)
    assert exc.value.code == ErrorCode.PRECONDITION_STORE_UNAVAILABLE
    assert "frobnicate" in str(exc.value)


def test_env_unknown_name_is_a_terminal_user_error(tmp_path: Path) -> None:
    with pytest.raises(PreconditionError):
        resolve_store(None, env={"PRGROOM_STORE": "nope"}, state_dir=tmp_path)


def test_blank_env_falls_back_to_default_file(tmp_path: Path) -> None:
    # A blank PRGROOM_STORE is treated as unset (POSIX env convention, mirroring
    # resolve_state_dir's blank-XDG_STATE_HOME handling), not as an explicit
    # invalid selection — a stray `export PRGROOM_STORE=` must not break every run.
    store = resolve_store(None, env={"PRGROOM_STORE": ""}, state_dir=tmp_path)
    assert isinstance(store, LegacyExportStore)
    assert isinstance(store._inner, FileStore)


def test_blank_flag_is_an_explicit_error_not_a_fallback(tmp_path: Path) -> None:
    # Deliberately distinct from a blank env: an explicit empty `--store ''` is a
    # user mistake (an explicit selection of nothing), so it surfaces the terminal
    # user-error rather than silently defaulting.
    with pytest.raises(PreconditionError) as exc:
        resolve_store("", env={}, state_dir=tmp_path)
    assert exc.value.code == ErrorCode.PRECONDITION_STORE_UNAVAILABLE
