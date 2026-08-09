"""Tests for the CLI `--store` root-callback wiring (§1, §2).

The store is resolved eagerly in the root callback so an invalid adapter fails
terminally — rendered 4-line block, exit 2, no traceback — BEFORE any verb body
runs. A valid `--store file` (or the default) falls through to the verb, which
then actually reads through the resolved store. The probe is `status` against
a well-formed PR ref that has never been polled: `status`'s lock-free `_read()`
calls `store.read(ref)` for real (`file.py::FileStore.read`), which raises
`StateNotFoundError` for a ref with no state file, converted to
`PRECONDITION_NO_STATE`. This exercises `ctx.obj` as a genuine, working Store —
not just "the verb body was reached" — so a broken store resolution (e.g. a
non-functional object landing on `ctx.obj`) would surface here as an
uncaught exception rather than a false pass.

Every test isolates `XDG_STATE_HOME` to `tmp_path`: the real `file` adapter
reads `$XDG_STATE_HOME/prgroom/...` (`file.py::resolve_state_dir`), so without
isolation a pre-existing state file for the probe's PR ref on the runner's
machine would flip `PRECONDITION_NO_STATE` into a real `gh` invocation.

Proves `--store` beats `PRGROOM_STORE` via a set env var.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from prgroom.cli import app

runner = CliRunner()

# A well-formed PR ref that (by construction) has no state file on disk, so a
# working store's `read()` deterministically raises PRECONDITION_NO_STATE —
# never PRECONDITION_BAD_PR_REF, which would mask a broken store behind a
# parse failure that never reaches `store.read()`.
_PROBE = "status"
_PROBE_ARG = "prgroom-test-fixture/store-probe#999999"


def test_invalid_store_bd_exits_two_with_block_before_verb(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    result = runner.invoke(app, ["--store", "bd", _PROBE, _PROBE_ARG])
    assert result.exit_code == 2
    assert "error: PRECONDITION_STORE_UNAVAILABLE" in result.output
    assert "how:" in result.output
    # Terminal store error pre-empts the verb's own precondition check.
    assert "PRECONDITION_NO_STATE" not in result.output
    # A clean typer.Exit (SystemExit), not an uncaught PrgroomError traceback: the
    # error was caught and rendered, not propagated raw. CliRunner records the
    # raw exception when a command raises something other than SystemExit, so a
    # PrgroomError leaking here would NOT be a SystemExit.
    assert isinstance(result.exception, SystemExit)


def test_unknown_store_name_exits_two(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    result = runner.invoke(app, ["--store", "frobnicate", _PROBE, _PROBE_ARG])
    assert result.exit_code == 2
    assert "PRECONDITION_STORE_UNAVAILABLE" in result.output


def test_valid_store_file_falls_through_to_verb(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    result = runner.invoke(app, ["--store", "file", _PROBE, _PROBE_ARG])
    assert result.exit_code == 2
    assert "PRECONDITION_NO_STATE" in result.output


def test_default_store_falls_through_to_verb(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    # An ambient PRGROOM_STORE (e.g. left set in the runner's shell) would
    # otherwise silently take precedence over the default this test asserts.
    monkeypatch.delenv("PRGROOM_STORE", raising=False)
    result = runner.invoke(app, [_PROBE, _PROBE_ARG])
    assert result.exit_code == 2
    assert "PRECONDITION_NO_STATE" in result.output


def test_flag_beats_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    # env says bd (would error); flag says file (valid) -> flag wins -> verb runs.
    monkeypatch.setenv("PRGROOM_STORE", "bd")
    result = runner.invoke(app, ["--store", "file", _PROBE, _PROBE_ARG])
    assert result.exit_code == 2
    assert "PRECONDITION_NO_STATE" in result.output


def test_env_bd_with_no_flag_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("PRGROOM_STORE", "bd")
    result = runner.invoke(app, [_PROBE, _PROBE_ARG])
    assert result.exit_code == 2
    assert "PRECONDITION_STORE_UNAVAILABLE" in result.output
