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


def _dir_item(relpath: Path, *, namespace: str) -> StagedItem:
    """A directory StagedItem (``content is None``) — materialised from its source
    tree at sync, never inlined."""
    return StagedItem(
        source_path=Path("/unused") / relpath,
        dest_relpath=relpath,
        kind=FileKind.DIR,
        namespace=namespace,
        provenance=Provenance(kind="tool", name="claude"),
        content=None,
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


def test_flatten_inlines_named_rules_subset_from_source_dir(tmp_path: Path) -> None:
    """A named-RULES subset marker is replaced by the listed rules in order,
    resolved from the fixed ``src/user/.claude/rules/`` source dir under
    repo_root — NOT from the plan's staged rules tree (that is the ALL-RULES
    source). The subset can name rules the staged tree does not even carry."""
    rules_src = tmp_path / "src/user/.claude/rules"
    rules_src.mkdir(parents=True)
    (rules_src / "second.md").write_bytes(b"SECOND\n")
    (rules_src / "first.md").write_bytes(b"FIRST\n")
    agents_md = _item(
        Path("AGENTS.md"),
        b"top\n<!-- DYNAMIC-INCLUDE-RULES: second,first -->\n",
    )
    plan = _plan(agents_md)

    flatten_plan_templates(plan, repo_root=tmp_path, io=ScriptedIO())

    assert plan.items[Path("AGENTS.md")].content == b"top\nSECOND\n\n---\nFIRST\n"


def test_flatten_leaves_other_items_and_markerless_templates_untouched(tmp_path: Path) -> None:
    """Non-flattenable items and a marker-free instruction file are unchanged, and
    nothing is dropped when there are no includes."""
    agents_md = _item(Path("AGENTS.md"), b"# no markers here\n")
    cmd = _item(Path("commands/go.md"), b"go", namespace="commands")
    plan = _plan(agents_md, cmd)

    flatten_plan_templates(plan, repo_root=tmp_path, io=ScriptedIO())

    assert plan.items[Path("AGENTS.md")].content == b"# no markers here\n"
    assert plan.items[Path("commands/go.md")].content == b"go"


def test_all_rules_inline_drops_loose_rules_from_plan(tmp_path: Path) -> None:
    """When the instruction file inlines every rule via ALL-RULES, the loose
    rules/ items are dropped from the plan.

    A tool whose instruction file carries the ALL-RULES marker
    (codex/gemini/opencode) gets every rule inlined into AGENTS.md/GEMINI.md, so
    deploying the rules/ files standalone would write redundant copies the tool
    does not read. They are removed exactly like include-only file templates."""
    gemini_md = _item(Path("GEMINI.md"), b"top\n<!-- DYNAMIC-INCLUDE-ALL-RULES -->\n")
    r1 = _item(Path("rules/a-first.md"), b"FIRST", namespace="rules")
    r2 = _item(Path("rules/b-second.md"), b"SECOND", namespace="rules")
    plan = _plan(gemini_md, r1, r2)

    flatten_plan_templates(plan, repo_root=tmp_path, io=ScriptedIO())

    assert plan.items[Path("GEMINI.md")].content == b"top\nFIRST\n---\nSECOND"
    assert Path("rules/a-first.md") not in plan.items
    assert Path("rules/b-second.md") not in plan.items


def test_markerless_instruction_file_keeps_loose_rules(tmp_path: Path) -> None:
    """When the instruction file does NOT inline ALL-RULES, the rules/ items stay
    in the plan for standalone deploy.

    Claude reads a loose ~/.claude/rules/ tree natively and its AGENTS.md carries
    no ALL-RULES marker, so its rules must survive flattening as standalone files —
    only the inlining tools drop them."""
    agents_md = _item(Path("AGENTS.md"), b"# claude - no all-rules marker\n")
    r1 = _item(Path("rules/a-first.md"), b"FIRST", namespace="rules")
    plan = _plan(agents_md, r1)

    flatten_plan_templates(plan, repo_root=tmp_path, io=ScriptedIO())

    assert plan.items[Path("rules/a-first.md")].content == b"FIRST"


def test_all_rules_inline_keeps_a_non_inlined_rules_dir_item(tmp_path: Path) -> None:
    """The drop mirrors the inliner: only rule FILE items (content is not None) are
    inlined, so only those are dropped. A rules/ directory item (content None) was
    never inlined, so dropping it would lose content silently — it must survive."""
    gemini_md = _item(Path("GEMINI.md"), b"top\n<!-- DYNAMIC-INCLUDE-ALL-RULES -->\n")
    rule_file = _item(Path("rules/a-first.md"), b"FIRST", namespace="rules")
    rule_dir = _dir_item(Path("rules/subpack"), namespace="rules")
    plan = _plan(gemini_md, rule_file, rule_dir)

    flatten_plan_templates(plan, repo_root=tmp_path, io=ScriptedIO())

    assert Path("rules/a-first.md") not in plan.items  # inlined file dropped
    assert Path("rules/subpack") in plan.items  # non-inlined dir survives
