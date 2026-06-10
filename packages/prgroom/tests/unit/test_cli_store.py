"""Tests for the CLI `--store` root-callback wiring (§1, §2).

The store is resolved eagerly in the root callback so an invalid adapter fails
terminally — rendered 4-line block, exit 2, no traceback — BEFORE any verb body
runs. A valid `--store file` (or the default) falls through to the verb skeleton.
Proves `--store` beats `PRGROOM_STORE` via a set env var.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from prgroom.cli import SKELETON_EXIT_CODE, app

runner = CliRunner()


def test_invalid_store_bd_exits_two_with_block_before_skeleton() -> None:
    result = runner.invoke(app, ["--store", "bd", "poll", "123"])
    assert result.exit_code == 2
    assert "error: PRECONDITION_STORE_UNAVAILABLE" in result.output
    assert "how:" in result.output
    # Terminal store error pre-empts the skeleton notice.
    assert "not yet implemented" not in result.output
    # A clean typer.Exit (SystemExit), not an uncaught PrgroomError traceback: the
    # error was caught and rendered, not propagated raw. CliRunner records the
    # raw exception when a command raises something other than SystemExit, so a
    # PrgroomError leaking here would NOT be a SystemExit.
    assert isinstance(result.exception, SystemExit)


def test_unknown_store_name_exits_two() -> None:
    result = runner.invoke(app, ["--store", "frobnicate", "poll", "123"])
    assert result.exit_code == 2
    assert "PRECONDITION_STORE_UNAVAILABLE" in result.output


def test_valid_store_file_falls_through_to_skeleton() -> None:
    result = runner.invoke(app, ["--store", "file", "poll", "123"])
    assert result.exit_code == SKELETON_EXIT_CODE
    assert "not yet implemented" in result.output


def test_default_store_falls_through_to_skeleton() -> None:
    result = runner.invoke(app, ["poll", "123"])
    assert result.exit_code == SKELETON_EXIT_CODE


def test_flag_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # env says bd (would error); flag says file (valid) -> flag wins -> skeleton.
    monkeypatch.setenv("PRGROOM_STORE", "bd")
    result = runner.invoke(app, ["--store", "file", "poll", "123"])
    assert result.exit_code == SKELETON_EXIT_CODE


def test_env_bd_with_no_flag_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRGROOM_STORE", "bd")
    result = runner.invoke(app, ["poll", "123"])
    assert result.exit_code == 2
    assert "PRECONDITION_STORE_UNAVAILABLE" in result.output
