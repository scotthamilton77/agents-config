"""Unit tests for installer.core.installer_toml (G.2 — TOML config loader).

Each test pins a coded decision in ``load_installer_toml``:
- a missing file is a no-op default (no overrides), not an error,
- a present file with no ``[tools]`` section yields no overrides,
- optional ``[tools]`` dest overrides are surfaced when present, empty when not,
- a type-malformed ``[tools]`` table or non-string ``dest`` raises ValueError.

Tautology tests (asserting tomllib parses TOML, asserting a dataclass is frozen)
are deliberately absent — the loader's *defaulting* and *section-selection*
decisions are the behaviour under test, not stdlib TOML parsing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.installer_toml import load_installer_toml


def test_missing_file_yields_empty_overrides_without_error(tmp_path: Path) -> None:
    """
    Given a path to an installer.toml that does not exist
    When the loader reads it
    Then it returns empty tool dest overrides (absence is not an error).
    """
    config = load_installer_toml(tmp_path / "does-not-exist.toml")

    assert config.tool_dest_overrides == {}


def test_present_file_without_tools_section_yields_empty_overrides(tmp_path: Path) -> None:
    """
    Given an installer.toml present but carrying no [tools] section
    When the loader reads it
    Then the overrides are empty (section-optional, not section-required).
    """
    toml = tmp_path / "installer.toml"
    toml.write_text("# installer.toml — no [tools] table\n")

    config = load_installer_toml(toml)

    assert config.tool_dest_overrides == {}


def test_tool_dest_override_surfaced_when_present(tmp_path: Path) -> None:
    """
    Given a [tools] section declaring a per-tool dest override
    When the loader reads it
    Then the override is surfaced keyed by tool name.
    """
    toml = tmp_path / "installer.toml"
    toml.write_text('[tools]\nclaude.dest = "~/somewhere/.claude"\n')

    config = load_installer_toml(toml)

    assert config.tool_dest_overrides == {"claude": "~/somewhere/.claude"}


def test_tool_dest_overrides_empty_when_tools_section_absent(tmp_path: Path) -> None:
    """
    Given an installer.toml carrying an unrelated table but no [tools] section
    When the loader reads it
    Then tool dest overrides default to an empty mapping.
    """
    toml = tmp_path / "installer.toml"
    toml.write_text('[other]\nkey = "value"\n')

    config = load_installer_toml(toml)

    assert config.tool_dest_overrides == {}


def test_tools_not_a_table_raises_value_error(tmp_path: Path) -> None:
    """
    Given a type-malformed [tools] (a scalar, not a table)
    When the loader reads it
    Then a ValueError is raised rather than silently iterating a non-dict.
    """
    toml = tmp_path / "installer.toml"
    toml.write_text('tools = "x"\n')

    with pytest.raises(ValueError, match=r"\[tools\] must be a table"):
        load_installer_toml(toml)


def test_tool_dest_non_string_raises_value_error(tmp_path: Path) -> None:
    """
    Given a [tools] entry whose dest leaf is a non-string (an int)
    When the loader reads it
    Then a ValueError is raised — the dest leaf is validated, not just the
    container shape, so a non-string never reaches a later string consumer.
    """
    toml = tmp_path / "installer.toml"
    toml.write_text("[tools]\nclaude.dest = 123\n")

    with pytest.raises(ValueError, match=r"claude\.dest must be a string"):
        load_installer_toml(toml)


def test_tool_entry_without_dest_key_is_skipped_not_an_error(tmp_path: Path) -> None:
    """
    Given a [tools] entry that declares no dest key (only some other field)
    When the loader reads it
    Then the entry is silently skipped (no override surfaced, no error) —
    only <tool>.dest entries contribute to the override mapping.
    """
    toml = tmp_path / "installer.toml"
    toml.write_text('[tools]\nclaude.other = "x"\n')

    config = load_installer_toml(toml)

    assert config.tool_dest_overrides == {}
