"""Unit tests for installer.core.templates.flatten_plan_templates — the plan-level
Phase 6.5/6.75 port: flatten the instruction templates in a StagingPlan, then drop
the include-only templates they inline (bash install.sh:849-890).
"""

from __future__ import annotations

from pathlib import Path

from installer.core.io_port import ScriptedIO
from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
from installer.core.templates import flatten_plan_templates


def _item(relpath: Path, content: bytes, *, namespace: str | None = None) -> StagedItem:
    return StagedItem(
        source_path=Path("/unused") / relpath,
        dest_relpath=relpath,
        kind=FileKind.NAMESPACED_MD if namespace else FileKind.OTHER,
        namespace=namespace,
        provenance=Provenance(kind="tool", name="claude"),
        content=content,
    )


def _plan(*items: StagedItem) -> StagingPlan:
    return StagingPlan(items={i.dest_relpath: i for i in items}, tool=Tool.CLAUDE)


def test_flatten_inlines_file_includes_and_drops_include_only(tmp_path: Path) -> None:
    """A file-include marker is replaced by the referenced file's text (resolved
    from repo_root), and the inlined template is removed from the plan so it is
    not also deployed standalone (Phase 6.75)."""
    (tmp_path / "src/user/.agents").mkdir(parents=True)
    (tmp_path / "src/user/.agents/AGENT-PERSONA.md.template").write_bytes(b"PERSONA\n")
    agents_md = _item(
        Path("AGENTS.md"),
        b"# top\n<!-- DYNAMIC-INCLUDE: src/user/.agents/AGENT-PERSONA.md.template -->\n",
    )
    persona = _item(Path("AGENT-PERSONA.md"), b"PERSONA\n")
    plan = _plan(agents_md, persona)

    flatten_plan_templates(plan, repo_root=tmp_path, io=ScriptedIO())

    assert plan.items[Path("AGENTS.md")].content == b"# top\nPERSONA\n"
    assert Path("AGENT-PERSONA.md") not in plan.items


def test_flatten_inlines_all_rules_from_staged_plan_rules(tmp_path: Path) -> None:
    """An ALL-RULES marker is replaced by the plan's staged rules, sorted by
    filename and joined with the bash separator."""
    gemini_md = _item(Path("GEMINI.md"), b"top\n<!-- DYNAMIC-INCLUDE-ALL-RULES -->\n")
    r1 = _item(Path("rules/a-first.md"), b"FIRST", namespace="rules")
    r2 = _item(Path("rules/b-second.md"), b"SECOND", namespace="rules")
    plan = _plan(gemini_md, r1, r2)

    flatten_plan_templates(plan, repo_root=tmp_path, io=ScriptedIO())

    assert plan.items[Path("GEMINI.md")].content == b"top\nFIRST\n---\nSECOND"


def test_flatten_leaves_other_items_and_markerless_templates_untouched(tmp_path: Path) -> None:
    """Non-flattenable items and a marker-free instruction file are unchanged, and
    nothing is dropped when there are no includes."""
    agents_md = _item(Path("AGENTS.md"), b"# no markers here\n")
    cmd = _item(Path("commands/go.md"), b"go", namespace="commands")
    plan = _plan(agents_md, cmd)

    flatten_plan_templates(plan, repo_root=tmp_path, io=ScriptedIO())

    assert plan.items[Path("AGENTS.md")].content == b"# no markers here\n"
    assert plan.items[Path("commands/go.md")].content == b"go"
