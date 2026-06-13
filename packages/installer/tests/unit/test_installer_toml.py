"""Unit tests for installer.core.installer_toml (G.2 — TOML config loader).

Each test pins a coded decision in ``load_installer_toml``:
- a present ``[prune] retired`` list is surfaced verbatim,
- a missing file is a no-op default (empty prune list), not an error,
- a present file with no ``[prune]`` section yields an empty prune list,
- optional ``[tools]`` dest overrides are surfaced when present, empty when not.

Tautology tests (asserting tomllib parses TOML, asserting a dataclass is frozen)
are deliberately absent — the loader's *defaulting* and *section-selection*
decisions are the behaviour under test, not stdlib TOML parsing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.installer_toml import load_installer_toml


def test_present_prune_section_surfaces_retired_globs_in_order(tmp_path: Path) -> None:
    """
    Given an installer.toml with a [prune] retired list of two globs
    When the loader reads it
    Then both globs are returned as strings in file order.
    """
    toml = tmp_path / "installer.toml"
    toml.write_text(
        '[prune]\nretired = [\n  "*/skills/foo",\n  "claude/rules/bar.md",\n]\n',
    )

    config = load_installer_toml(toml)

    assert config.prune_globs == ["*/skills/foo", "claude/rules/bar.md"]


def test_missing_file_yields_empty_prune_list_without_error(tmp_path: Path) -> None:
    """
    Given a path to an installer.toml that does not exist
    When the loader reads it
    Then it returns an empty prune list (absence is not an error).
    """
    config = load_installer_toml(tmp_path / "does-not-exist.toml")

    assert config.prune_globs == []


def test_present_file_without_prune_section_yields_empty_prune_list(tmp_path: Path) -> None:
    """
    Given an installer.toml present but carrying no [prune] section
    When the loader reads it
    Then the prune list is empty (section-optional, not section-required).
    """
    toml = tmp_path / "installer.toml"
    toml.write_text('[tools]\n# claude.dest = "~/.claude"\n')

    config = load_installer_toml(toml)

    assert config.prune_globs == []


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
    Given an installer.toml with only a [prune] section
    When the loader reads it
    Then tool dest overrides default to an empty mapping.
    """
    toml = tmp_path / "installer.toml"
    toml.write_text('[prune]\nretired = ["*/skills/foo"]\n')

    config = load_installer_toml(toml)

    assert config.tool_dest_overrides == {}


def test_prune_not_a_table_raises_value_error(tmp_path: Path) -> None:
    """
    Given a type-malformed [prune] (a scalar, not a table)
    When the loader reads it
    Then a ValueError is raised rather than an AttributeError on .get().
    """
    toml = tmp_path / "installer.toml"
    toml.write_text('prune = "x"\n')

    with pytest.raises(ValueError, match=r"\[prune\] must be a table"):
        load_installer_toml(toml)


def test_retired_as_string_raises_value_error(tmp_path: Path) -> None:
    """
    Given retired declared as a bare string instead of a list
    When the loader reads it
    Then a ValueError is raised — guarding the list("*/foo") single-char shred.
    """
    toml = tmp_path / "installer.toml"
    toml.write_text('[prune]\nretired = "*/skills/foo"\n')

    with pytest.raises(ValueError, match=r"retired must be a list of strings"):
        load_installer_toml(toml)


def test_retired_with_non_string_elements_raises_value_error(tmp_path: Path) -> None:
    """
    Given a retired list whose elements are not strings
    When the loader reads it
    Then a ValueError is raised rather than passing ints downstream to fnmatch.
    """
    toml = tmp_path / "installer.toml"
    toml.write_text("[prune]\nretired = [1, 2]\n")

    with pytest.raises(ValueError, match=r"retired must be a list of strings"):
        load_installer_toml(toml)


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
