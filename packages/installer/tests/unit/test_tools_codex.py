"""Behavioral tests for CodexAdapter.

Each test pins a coded decision. Tautology tests (attribute literals,
isinstance checks, @runtime_checkable machinery) are absent per the
writing-unit-tests tautology filter."""

from __future__ import annotations

from pathlib import Path

from installer.tools.codex import CodexAdapter


def test_codex_adapter_detected_when_dot_codex_dir_exists(tmp_path: Path) -> None:
    """
    Given ~/.codex/ exists as a directory
    When is_detected is called with that home
    Then it returns True.

    Pins: directory-presence detection (mirrors bash [[ -d "$HOME/.codex" ]]).
    """
    (tmp_path / ".codex").mkdir()
    assert CodexAdapter().is_detected(tmp_path) is True


def test_codex_adapter_not_detected_when_dot_codex_absent(tmp_path: Path) -> None:
    """
    Given ~/.codex/ does not exist
    When is_detected is called
    Then it returns False.

    Pins: fresh-home guard — installer skips Codex when not installed.
    """
    assert CodexAdapter().is_detected(tmp_path) is False


def test_codex_adapter_not_detected_when_dot_codex_is_a_file(tmp_path: Path) -> None:
    """
    Given ~/.codex exists but is a file (not a directory)
    When is_detected is called
    Then it returns False.

    Pins: probe is a directory check, not a mere existence check.
    """
    (tmp_path / ".codex").write_text("oops")
    assert CodexAdapter().is_detected(tmp_path) is False
