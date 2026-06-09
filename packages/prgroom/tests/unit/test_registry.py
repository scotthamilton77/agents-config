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
from prgroom.prsession.registry import StoreName, resolve_store


def test_explicit_file_name_yields_filestore(tmp_path: Path) -> None:
    store = resolve_store("file", env={}, state_dir=tmp_path)
    assert isinstance(store, FileStore)


def test_default_when_no_flag_no_env_is_file(tmp_path: Path) -> None:
    store = resolve_store(None, env={}, state_dir=tmp_path)
    assert isinstance(store, FileStore)


def test_env_selects_when_no_flag(tmp_path: Path) -> None:
    store = resolve_store(None, env={"PRGROOM_STORE": "file"}, state_dir=tmp_path)
    assert isinstance(store, FileStore)


def test_flag_beats_env(tmp_path: Path) -> None:
    # Flag says file, env says bd: flag wins, so we get a FileStore (no error).
    store = resolve_store("file", env={"PRGROOM_STORE": "bd"}, state_dir=tmp_path)
    assert isinstance(store, FileStore)


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


def test_store_name_enum_values() -> None:
    # Consumer-boundary pin: these strings are the user-facing --store / env
    # vocabulary, so they are pinned where a drift would break the CLI surface.
    assert StoreName.FILE.value == "file"
    assert StoreName.BD.value == "bd"
