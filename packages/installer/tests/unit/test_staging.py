"""Unit tests for installer.core.staging — B.3 (.template suffix strip).

Each test pins a behaviour the B.3 story contract requires
(docs/specs/2026-05-31-w1qls.2.3-template-suffix-strip.md).
"""

from __future__ import annotations

from pathlib import Path

from installer.core.model import FileKind, Provenance
from installer.core.staging import stage_namespace, strip_template_suffix


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


def _prov() -> Provenance:
    return Provenance(kind="tool", name="claude")


def test_stage_namespace_md_files_are_namespaced(tmp_path: Path) -> None:
    """A .md file in a namespace dir becomes a NAMESPACED_MD item whose
    dest_relpath is <namespace>/<name> and whose bytes are read eagerly."""
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "style.md").write_bytes(b"# style\n")

    items = stage_namespace(tmp_path, "rules", provenance=_prov())

    assert len(items) == 1
    item = items[0]
    assert item.kind == FileKind.NAMESPACED_MD
    assert item.namespace == "rules"
    assert item.dest_relpath == Path("rules/style.md")
    assert item.content == b"# style\n"
    assert item.provenance == _prov()


def test_stage_namespace_directory_is_dir_with_no_content(tmp_path: Path) -> None:
    """A skill directory is staged as a single DIR unit; content is None
    (bytes derived from source_path at sync time)."""
    skills = tmp_path / "skills"
    (skills / "my-skill").mkdir(parents=True)
    (skills / "my-skill" / "SKILL.md").write_bytes(b"x")

    items = stage_namespace(tmp_path, "skills", provenance=_prov())

    assert len(items) == 1
    assert items[0].kind == FileKind.DIR
    assert items[0].content is None
    assert items[0].dest_relpath == Path("skills/my-skill")


def test_stage_namespace_filters_top_level_marker_files(tmp_path: Path) -> None:
    """In-repo AGENTS.md/CLAUDE.md/GEMINI.md at the top of a namespace dir
    are dead files with no host-runtime meaning and are dropped."""
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "AGENTS.md").write_bytes(b"dev doc")
    (skills / "real-skill").mkdir()

    items = stage_namespace(tmp_path, "skills", provenance=_prov())

    names = {i.dest_relpath.name for i in items}
    assert names == {"real-skill"}


def test_stage_namespace_strips_template_suffix(tmp_path: Path) -> None:
    """A namespace .md.template entry lands with the suffix stripped."""
    cmds = tmp_path / "commands"
    cmds.mkdir()
    (cmds / "go.md.template").write_bytes(b"go")

    items = stage_namespace(tmp_path, "commands", provenance=_prov())

    assert items[0].dest_relpath == Path("commands/go.md")


def test_stage_namespace_missing_dir_returns_empty(tmp_path: Path) -> None:
    """A namespace dir that does not exist yields no items (bash `return 0`)."""
    assert stage_namespace(tmp_path, "agents", provenance=_prov()) == []


def test_stage_namespace_is_deterministically_ordered(tmp_path: Path) -> None:
    """Entries are returned sorted by name for reproducible plans."""
    rules = tmp_path / "rules"
    rules.mkdir()
    for n in ("c.md", "a.md", "b.md"):
        (rules / n).write_bytes(b"x")

    items = stage_namespace(tmp_path, "rules", provenance=_prov())

    assert [i.dest_relpath.name for i in items] == ["a.md", "b.md", "c.md"]
