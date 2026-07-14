"""Unit tests for installer.config.

Each test pins a design decision from the B.1 spec
(docs/specs/2026-05-23-w1qls.2.1-config-claude-adapter-design.md).
Tests for `@dataclass(frozen=True)` machinery, `slots=True` behaviour,
and pathlib semantics are deliberately absent — they test stdlib, not
coded decisions. See the writing-unit-tests skill's Tautology Filter."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from installer.config import read_project_profiles, resolve_tools, write_project_profiles
from installer.core.model import Tool
from installer.tools import registry
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


def test_autodetect_includes_claude_when_settings_json_absent(
    tmp_path: Path,
) -> None:
    """
    Given an empty home directory
    When resolve_tools(home=that_home, override_csv=None) is called
    Then the result is (Tool.CLAUDE,).

    Pins: claude is unconditionally selected under auto-detect, matching
    install.sh's `TOOLS=(claude)` ("claude always; others if ~/.<tool>/").
    A fresh machine with no ~/.claude/settings.json still installs claude.
    """
    assert resolve_tools(home=tmp_path, override_csv=None) == (Tool.CLAUDE,)


def test_autodetect_claude_always_plus_detected_other(tmp_path: Path) -> None:
    """
    Given a home with ~/.codex/ (a codex marker) but no ~/.claude/settings.json
    When resolve_tools(home=that_home, override_csv=None) is called
    Then the result is (Tool.CLAUDE, Tool.CODEX).

    Pins: the always-on claude rule composes with — does not suppress —
    detection of other tools, and claude leads (known_tools() sorts it first,
    matching bash's claude-first auto-detect order).
    """
    (tmp_path / ".codex").mkdir()
    assert resolve_tools(home=tmp_path, override_csv=None) == (Tool.CLAUDE, Tool.CODEX)


def test_explicit_tools_claude_is_accepted(tmp_path: Path) -> None:
    """
    When resolve_tools(home=any, override_csv="claude") is called
    Then the result is (Tool.CLAUDE,).
    """
    assert resolve_tools(home=tmp_path, override_csv="claude") == (Tool.CLAUDE,)


def test_explicit_tools_suppresses_autodetected_others(
    tmp_path: Path,
) -> None:
    """
    Given a home with ~/.codex/ (a codex marker)
    When resolve_tools(home=that_home, override_csv="claude") is called
    Then the result is (Tool.CLAUDE,) — codex is NOT auto-added.

    Pins: an explicit --tools list is authoritative; it bypasses auto-detect
    entirely (including the always-on claude rule's sibling detection), so the
    user gets exactly what they asked for.
    """
    (tmp_path / ".codex").mkdir()
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


def test_unregistered_enum_value_in_csv_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a Tool enum value whose adapter is absent from the registry
    When resolve_tools is called with that value in --tools=
    Then UnknownToolError is raised.

    Pins: the registry — not the enum — gates CSV validation. Every Tool now
    has a registered adapter, so the unregistered case is simulated by removing
    one entry.
    """
    reduced = {t: a for t, a in registry._REGISTRY.items() if t is not Tool.OPENCODE}
    monkeypatch.setattr(registry, "_REGISTRY", reduced)
    with pytest.raises(UnknownToolError):
        resolve_tools(home=tmp_path, override_csv="opencode")


def test_garbage_csv_token_is_rejected(tmp_path: Path) -> None:
    """
    When resolve_tools(home=any, override_csv="foo") is called
    Then UnknownToolError is raised.
    """
    with pytest.raises(UnknownToolError):
        resolve_tools(home=tmp_path, override_csv="foo")


def test_read_project_profiles_returns_tuple_when_install_profiles_present(
    tmp_path: Path,
) -> None:
    """
    Given <project>/project-config.toml with [install] profiles = ["beads-kit"]
    When read_project_profiles(project_root) is called
    Then the result is ("beads-kit",).
    """
    (tmp_path / "project-config.toml").write_text(
        '[install]\nprofiles = ["beads-kit"]\n', encoding="utf-8"
    )
    assert read_project_profiles(tmp_path) == ("beads-kit",)


def test_read_project_profiles_returns_none_when_file_absent(tmp_path: Path) -> None:
    """
    Given a project root with no project-config.toml
    When read_project_profiles(project_root) is called
    Then the result is None (absence is a valid state, not an error).
    """
    assert read_project_profiles(tmp_path) is None


def test_read_project_profiles_returns_none_when_install_table_absent(tmp_path: Path) -> None:
    """
    Given project-config.toml present but with no [install] table
    When read_project_profiles(project_root) is called
    Then the result is None.
    """
    (tmp_path / "project-config.toml").write_text('[other]\nfoo = "bar"\n', encoding="utf-8")
    assert read_project_profiles(tmp_path) is None


def test_write_project_profiles_round_trips_through_read(tmp_path: Path) -> None:
    """
    Given a project root with no project-config.toml
    When write_project_profiles(project_root, ("beads-kit",)) is called
    Then read_project_profiles(project_root) returns ("beads-kit",).
    """
    write_project_profiles(tmp_path, ("beads-kit",))
    assert read_project_profiles(tmp_path) == ("beads-kit",)


def test_write_project_profiles_preserves_other_tables(tmp_path: Path) -> None:
    """
    Given project-config.toml with an unrelated [merge-policy] table
    When write_project_profiles(project_root, ("beads-kit",)) is called
    Then [merge-policy] survives and [install].profiles is set.
    """
    path = tmp_path / "project-config.toml"
    path.write_text('[merge-policy]\nmerge-authorization = "explicit"\n', encoding="utf-8")

    write_project_profiles(tmp_path, ("beads-kit",))

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["merge-policy"] == {"merge-authorization": "explicit"}
    assert data["install"]["profiles"] == ["beads-kit"]
