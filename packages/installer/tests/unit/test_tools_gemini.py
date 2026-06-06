"""Behavioral tests for GeminiAdapter.

Each test pins a coded decision. Tautology tests (attribute literals,
isinstance checks, @runtime_checkable machinery) are absent per the
writing-unit-tests tautology filter."""

from __future__ import annotations

from pathlib import Path

from installer.tools.gemini import GeminiAdapter


def test_gemini_adapter_detected_when_dot_gemini_dir_exists(tmp_path: Path) -> None:
    """
    Given ~/.gemini/ exists as a directory
    When is_detected is called with that home
    Then it returns True.

    Pins: directory-presence detection (mirrors bash [[ -d "$HOME/.gemini" ]]).
    """
    (tmp_path / ".gemini").mkdir()
    assert GeminiAdapter().is_detected(tmp_path) is True


def test_gemini_adapter_not_detected_when_dot_gemini_absent(tmp_path: Path) -> None:
    """
    Given ~/.gemini/ does not exist
    When is_detected is called
    Then it returns False.

    Pins: fresh-home guard — installer skips Gemini when not installed.
    """
    assert GeminiAdapter().is_detected(tmp_path) is False


def test_gemini_adapter_not_detected_when_dot_gemini_is_a_file(tmp_path: Path) -> None:
    """
    Given ~/.gemini exists but is a file (not a directory)
    When is_detected is called
    Then it returns False.

    Pins: probe is a directory check, not a mere existence check.
    """
    (tmp_path / ".gemini").write_text("oops")
    assert GeminiAdapter().is_detected(tmp_path) is False
