"""Unit tests for installer.config.

Each test pins a design decision from the B.1 spec
(docs/specs/2026-05-23-w1qls.2.1-config-claude-adapter-design.md).
Tests for `@dataclass(frozen=True)` machinery, `slots=True` behaviour,
and pathlib semantics are deliberately absent — they test stdlib, not
coded decisions. See the writing-unit-tests skill's Tautology Filter."""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.config import resolve_tools
from installer.core.model import Tool
from installer.tools.registry import UnknownToolError


def _home_with_claude_settings(tmp_path: Path) -> Path:
    """Build a hermetic home directory with a Claude Code marker file."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    return tmp_path


def test_autodetect_includes_claude_when_settings_json_exists(
    tmp_path: Path,
) -> None:
    """
    Given a home directory with a file at .claude/settings.json
    When resolve_tools(home=that_home, override_csv=None) is called
    Then the result is (Tool.CLAUDE,).
    """
    home = _home_with_claude_settings(tmp_path)
    assert resolve_tools(home=home, override_csv=None) == (Tool.CLAUDE,)


def test_autodetect_excludes_claude_when_settings_json_absent(
    tmp_path: Path,
) -> None:
    """
    Given an empty home directory
    When resolve_tools(home=that_home, override_csv=None) is called
    Then the result is ().

    Pins: the deliberate divergence from install.sh's unconditional
    claude inclusion.
    """
    assert resolve_tools(home=tmp_path, override_csv=None) == ()


def test_explicit_tools_claude_is_accepted(tmp_path: Path) -> None:
    """
    When resolve_tools(home=any, override_csv="claude") is called
    Then the result is (Tool.CLAUDE,).
    """
    assert resolve_tools(home=tmp_path, override_csv="claude") == (Tool.CLAUDE,)


def test_explicit_tools_claude_overrides_empty_autodetect(
    tmp_path: Path,
) -> None:
    """
    Given an empty home directory
    When resolve_tools(home=that_home, override_csv="claude") is called
    Then the result is (Tool.CLAUDE,).

    Pins: override is "I know what I'm doing" — no settings.json gate.
    """
    assert resolve_tools(home=tmp_path, override_csv="claude") == (Tool.CLAUDE,)


def test_empty_tools_value_is_rejected(tmp_path: Path) -> None:
    """
    When resolve_tools(home=any, override_csv="") is called
    Then ValueError is raised.

    Pins: explicit-empty signals broken intent — Python improvement
    over bash's silent no-op.
    """
    with pytest.raises(ValueError, match="--tools="):
        resolve_tools(home=tmp_path, override_csv="")


def test_trailing_comma_in_tools_value_is_rejected(tmp_path: Path) -> None:
    """
    When resolve_tools(home=any, override_csv="claude,") is called
    Then ValueError is raised
    And the message names the CSV-format problem (not 'Unknown tool: '').

    Pins: empty CSV elements get a clear UX error rather than the
    misleading 'Unknown tool: ''' message from parse_tool_name("").
    """
    with pytest.raises(ValueError, match="empty tool name"):
        resolve_tools(home=tmp_path, override_csv="claude,")


def test_consecutive_commas_in_tools_value_is_rejected(tmp_path: Path) -> None:
    """
    When resolve_tools(home=any, override_csv="claude,,claude") is called
    Then ValueError is raised
    And the message names the CSV-format problem.
    """
    with pytest.raises(ValueError, match="empty tool name"):
        resolve_tools(home=tmp_path, override_csv="claude,,claude")


def test_whitespace_around_csv_tokens_is_stripped(tmp_path: Path) -> None:
    """
    When resolve_tools(home=any, override_csv=" claude ") is called
    Then the result is (Tool.CLAUDE,).
    """
    assert resolve_tools(home=tmp_path, override_csv=" claude ") == (Tool.CLAUDE,)


def test_duplicate_csv_tokens_are_deduped_first_occurrence_wins(
    tmp_path: Path,
) -> None:
    """
    When resolve_tools(home=any, override_csv="claude,claude") is called
    Then the result is (Tool.CLAUDE,).
    """
    assert resolve_tools(home=tmp_path, override_csv="claude,claude") == (Tool.CLAUDE,)


def test_unregistered_enum_value_in_csv_is_rejected(tmp_path: Path) -> None:
    """
    When resolve_tools(home=any, override_csv="gemini") is called
    Then UnknownToolError is raised.

    Pins: Tool.GEMINI exists in the enum but has no registered adapter, so
    the registry — not the enum — gates CSV validation.
    """
    with pytest.raises(UnknownToolError):
        resolve_tools(home=tmp_path, override_csv="gemini")


def test_garbage_csv_token_is_rejected(tmp_path: Path) -> None:
    """
    When resolve_tools(home=any, override_csv="foo") is called
    Then UnknownToolError is raised.
    """
    with pytest.raises(UnknownToolError):
        resolve_tools(home=tmp_path, override_csv="foo")
