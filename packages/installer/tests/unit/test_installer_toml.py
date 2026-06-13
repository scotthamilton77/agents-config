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
