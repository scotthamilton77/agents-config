"""Unit tests for installer.core.staging — B.3 (.template suffix strip).

Each test pins a behaviour the B.3 story contract requires
(docs/specs/2026-05-31-w1qls.2.3-template-suffix-strip.md).
"""

from __future__ import annotations

from pathlib import Path

from installer.core.staging import strip_template_suffix


def test_template_suffix_is_stripped() -> None:
    """
    Given a path whose final suffix is .template
    When strip_template_suffix is called
    Then the .template suffix is removed and the remaining name is unchanged.
    """
    assert strip_template_suffix(Path("AGENTS.md.template")) == Path("AGENTS.md")


def test_non_template_path_is_unchanged() -> None:
    """
    Given a path with no .template suffix
    When strip_template_suffix is called
    Then the path is returned unchanged.
    """
    assert strip_template_suffix(Path("AGENTS.md")) == Path("AGENTS.md")


def test_directory_components_are_preserved() -> None:
    """
    Given a nested path whose filename ends in .template
    When strip_template_suffix is called
    Then directory components are untouched and only the filename suffix changes.
    """
    assert strip_template_suffix(Path("rules/AGENTS.md.template")) == Path("rules/AGENTS.md")


def test_bare_template_name_strips_to_stem() -> None:
    """
    Given a path whose entire name is <stem>.template (no prior extension)
    When strip_template_suffix is called
    Then the .template suffix is removed, leaving just the stem.
    """
    assert strip_template_suffix(Path("some.template")) == Path("some")
