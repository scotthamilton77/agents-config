"""Unit tests for installer.core.staging — B.3 (.template suffix strip).

Each test pins a behaviour the B.3 story contract requires
(docs/specs/2026-05-31-w1qls.2.3-template-suffix-strip.md).
"""

from __future__ import annotations

from pathlib import Path

from installer.core.installignore import InstallIgnore
from installer.core.model import FileKind, Provenance
from installer.core.staging import (
    stage_namespace,
    stage_settings,
    stage_templates,
    strip_template_suffix,
)


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


def test_strip_template_suffix_against_embedded_match_is_unchanged() -> None:
    """
    Given a path where .template appears as a non-final suffix (e.g. .template.bak)
    When strip_template_suffix is called
    Then the path is returned unchanged — only the final suffix is tested.
    """
    assert strip_template_suffix(Path("AGENTS.md.template.bak")) == Path("AGENTS.md.template.bak")


def test_strip_template_suffix_double_suffix_strips_outermost_only() -> None:
    """
    Given a path with two consecutive .template suffixes
    When strip_template_suffix is called
    Then only the outermost (final) suffix is stripped, leaving one .template.
    """
    assert strip_template_suffix(Path("file.template.template")) == Path("file.template")


def test_strip_template_suffix_no_suffix_path_is_unchanged() -> None:
    """
    Given a path with no suffix at all (e.g. Makefile)
    When strip_template_suffix is called
    Then the path is returned unchanged.
    """
    assert strip_template_suffix(Path("Makefile")) == Path("Makefile")


def _prov() -> Provenance:
    return Provenance(kind="tool", name="claude")


def test_stage_namespace_md_files_are_namespaced(tmp_path: Path, ignore: InstallIgnore) -> None:
    """A .md file in a namespace dir becomes a NAMESPACED_MD item whose
    dest_relpath is <namespace>/<name> and whose bytes are read eagerly."""
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "style.md").write_bytes(b"# style\n")

    items = stage_namespace(tmp_path, "rules", provenance=_prov(), ignore=ignore)

    assert len(items) == 1
    item = items[0]
    assert item.kind == FileKind.NAMESPACED_MD
    assert item.namespace == "rules"
    assert item.dest_relpath == Path("rules/style.md")
    assert item.content == b"# style\n"
    assert item.provenance == _prov()


def test_stage_namespace_directory_is_dir_with_no_content(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    """A skill directory is staged as a single DIR unit; content is None
    (bytes derived from source_path at sync time)."""
    skills = tmp_path / "skills"
    (skills / "my-skill").mkdir(parents=True)
    (skills / "my-skill" / "SKILL.md").write_bytes(b"x")

    items = stage_namespace(tmp_path, "skills", provenance=_prov(), ignore=ignore)

    assert len(items) == 1
    assert items[0].kind == FileKind.DIR
    assert items[0].content is None
    assert items[0].dest_relpath == Path("skills/my-skill")


def test_stage_namespace_filters_top_level_marker_files(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    """In-repo AGENTS.md/CLAUDE.md/GEMINI.md at the top of a namespace dir are
    dead files; the .installignore matcher drops them while keeping real content."""
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "AGENTS.md").write_bytes(b"dev doc")
    (skills / "real-skill").mkdir()

    items = stage_namespace(tmp_path, "skills", provenance=_prov(), ignore=ignore)

    names = {i.dest_relpath.name for i in items}
    assert names == {"real-skill"}


def test_stage_namespace_filters_excluded_directory(tmp_path: Path, ignore: InstallIgnore) -> None:
    """A directory whose name is a .installignore directory entry (rules-readmes)
    is dropped whole, not partially staged."""
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "rules-readmes").mkdir()
    (rules / "rules-readmes" / "foo-readme.md").write_bytes(b"rationale")
    (rules / "real-rule.md").write_bytes(b"rule")

    items = stage_namespace(tmp_path, "rules", provenance=_prov(), ignore=ignore)

    names = {i.dest_relpath.name for i in items}
    assert names == {"real-rule.md"}


def test_stage_namespace_strips_template_suffix(tmp_path: Path, ignore: InstallIgnore) -> None:
    """A namespace .md.template entry lands with the suffix stripped."""
    cmds = tmp_path / "commands"
    cmds.mkdir()
    (cmds / "go.md.template").write_bytes(b"go")

    items = stage_namespace(tmp_path, "commands", provenance=_prov(), ignore=ignore)

    assert items[0].dest_relpath == Path("commands/go.md")


def test_stage_namespace_missing_dir_returns_empty(tmp_path: Path, ignore: InstallIgnore) -> None:
    """A namespace dir that does not exist yields no items (bash `return 0`)."""
    assert stage_namespace(tmp_path, "agents", provenance=_prov(), ignore=ignore) == []


def test_stage_namespace_is_deterministically_ordered(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    """Entries are returned sorted by name for reproducible plans."""
    rules = tmp_path / "rules"
    rules.mkdir()
    for n in ("c.md", "a.md", "b.md"):
        (rules / n).write_bytes(b"x")

    items = stage_namespace(tmp_path, "rules", provenance=_prov(), ignore=ignore)

    assert [i.dest_relpath.name for i in items] == ["a.md", "b.md", "c.md"]


def test_stage_namespace_preserves_executable_bit(tmp_path: Path, ignore: InstallIgnore) -> None:
    """An executable source file (a hook script) stages with executable=True; a
    non-executable sibling stages with executable=False. The sync engine writes
    0o755 vs 0o644 from this bit, so hook scripts must land +x (8.7 parity)."""
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    script = hooks / "ruff-postedit.py"
    script.write_bytes(b"#!/usr/bin/env python3\n")
    script.chmod(0o755)
    plain = hooks / "notes.md"
    plain.write_bytes(b"x")
    plain.chmod(0o644)

    items = {
        i.dest_relpath.name: i
        for i in stage_namespace(tmp_path, "hooks", provenance=_prov(), ignore=ignore)
    }

    assert items["ruff-postedit.py"].executable is True
    assert items["notes.md"].executable is False


def test_stage_templates_strips_suffix_and_is_other(tmp_path: Path) -> None:
    """A tool-root AGENTS.md.template stages to AGENTS.md as FileKind.OTHER
    at the plan root (no namespace), with eager bytes."""
    (tmp_path / "AGENTS.md.template").write_bytes(b"# agents\n")

    items = stage_templates(tmp_path, provenance=_prov())

    assert len(items) == 1
    assert items[0].kind == FileKind.OTHER
    assert items[0].namespace is None
    assert items[0].dest_relpath == Path("AGENTS.md")
    assert items[0].content == b"# agents\n"


def test_stage_templates_ignores_raw_markdown(tmp_path: Path) -> None:
    """Raw AGENTS.md / CLAUDE.md at the tool root (in-repo dev docs) are not
    *.md.template and are never staged — only the template glob matches."""
    (tmp_path / "AGENTS.md").write_bytes(b"dev doc")
    (tmp_path / "CLAUDE.md").write_bytes(b"dev doc")
    (tmp_path / "AGENTS.md.template").write_bytes(b"real")

    items = stage_templates(tmp_path, provenance=_prov())

    assert [i.dest_relpath for i in items] == [Path("AGENTS.md")]


def test_stage_templates_missing_root_returns_empty(tmp_path: Path) -> None:
    assert stage_templates(tmp_path / "nope", provenance=_prov()) == []


def test_stage_settings_classifies_each_form(tmp_path: Path) -> None:
    """settings.json.template, *.jsonc.template, *.toml.template each stage
    to the plan root with the right FileKind and the .template suffix gone."""
    (tmp_path / "settings.json.template").write_bytes(b"{}")
    (tmp_path / "opencode.jsonc.template").write_bytes(b"{}")
    (tmp_path / "config.toml.template").write_bytes(b"x=1")

    items = stage_settings(tmp_path, provenance=_prov())
    by_dest = {i.dest_relpath: i for i in items}

    assert by_dest[Path("settings.json")].kind == FileKind.SETTINGS_JSON
    assert by_dest[Path("opencode.jsonc")].kind == FileKind.JSONC
    assert by_dest[Path("config.toml")].kind == FileKind.TOML
    assert all(i.namespace is None for i in items)


def test_stage_settings_ignores_md_and_dirs(tmp_path: Path) -> None:
    """Only settings templates are staged here; .md and subdirs are not."""
    (tmp_path / "AGENTS.md.template").write_bytes(b"x")
    (tmp_path / "skills").mkdir()
    (tmp_path / "settings.json.template").write_bytes(b"{}")

    items = stage_settings(tmp_path, provenance=_prov())

    assert [i.dest_relpath for i in items] == [Path("settings.json")]


def test_stage_settings_missing_root_returns_empty(tmp_path: Path) -> None:
    assert stage_settings(tmp_path / "nope", provenance=_prov()) == []
