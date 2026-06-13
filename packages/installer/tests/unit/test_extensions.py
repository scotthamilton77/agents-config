"""Phase 6.5 plugin extensions (plugins/extensions.py).

Behavioural tests for YAML schema validation, scope discovery + R6 ordering,
StagingPlan target resolution/writeback, and the apply_extensions composition
loop. Fixture style mirrors test_overlay.py: tmp_path plugin trees and a
minimal frozen _Plugin standing in for PluginAdapter; assertions are on
returned plan state and structured ExtensionError attrs — never call counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
from installer.plugins.extensions import ExtensionError, apply_extensions


@dataclass(frozen=True, slots=True)
class _Plugin:
    name: str
    source_path: Path

    def is_detected(self, home: Path) -> bool:  # noqa: ARG002  # inert  # pragma: no cover
        return True


def _plugin(tmp_path: Path, name: str) -> _Plugin:
    root = tmp_path / "plugins" / name
    root.mkdir(parents=True, exist_ok=True)
    return _Plugin(name=name, source_path=root)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _ext_yaml(
    target_file: str = "agents/reviewer.md",
    target_section: str = "Boundaries",
    precision: str = "append",
    content: str = "patched",
) -> str:
    block = "".join(f"  {line}\n" for line in content.split("\n"))
    return (
        f"target-file: {target_file}\n"
        f"target-section: {target_section}\n"
        f"precision: {precision}\n"
        f"content: |\n{block}"
    )


def _plan_with_agent_md(text: str = "# Reviewer\n\n## Boundaries\nbase\n") -> StagingPlan:
    item = StagedItem(
        source_path=Path("/base/agents/reviewer.md"),
        dest_relpath=Path("agents/reviewer.md"),
        kind=FileKind.NAMESPACED_MD,
        namespace="agents",
        provenance=Provenance(kind="tool", name="claude"),
        content=text.encode(),
    )
    return StagingPlan(items={item.dest_relpath: item}, tool=Tool.CLAUDE)


@pytest.mark.parametrize(
    ("yaml_text", "reason_match"),
    [
        ("target-file: [unclosed", "malformed YAML"),
        ("- a\n- b\n", "top-level YAML is a list; mapping required"),
        ("just a string\n", "top-level YAML is a scalar; mapping required"),
        (
            "target-section: S\nprecision: append\ncontent: c\n",
            "missing required field: target-file",
        ),
        (
            "target-file: f.md\nprecision: append\ncontent: c\n",
            "missing required field: target-section",
        ),
        (
            "target-file: f.md\ntarget-section: S\ncontent: c\n",
            "missing required field: precision",
        ),
        (
            "target-file: f.md\ntarget-section: S\nprecision: append\n",
            "missing required field: content",
        ),
        (_ext_yaml(precision="upsert"), "unknown precision: upsert"),
        (_ext_yaml(target_file="/etc/passwd"), "must be a relative path"),
        (_ext_yaml(target_file="../escape.md"), "must be a relative path"),
        (
            "target-file: f.md\ntarget-section: 7\nprecision: append\ncontent: c\n",
            "field target-section must be a string",
        ),
    ],
)
def test_schema_validation_is_terminal_with_cited_reason(
    tmp_path: Path, yaml_text: str, reason_match: str
) -> None:
    plugin = _plugin(tmp_path, "p")
    yaml_path = plugin.source_path / ".agents" / "extensions" / "00-bad.yaml"
    _write(yaml_path, yaml_text)

    with pytest.raises(ExtensionError, match=reason_match) as exc_info:
        apply_extensions(_plan_with_agent_md(), [plugin])
    assert exc_info.value.yaml_path == yaml_path


def test_unknown_precision_error_lists_the_valid_verbs(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path, "p")
    _write(plugin.source_path / ".agents" / "extensions" / "00.yaml", _ext_yaml(precision="bogus"))
    with pytest.raises(
        ExtensionError,
        match="expected one of: replace, insert_before, insert_after, prepend, append",
    ):
        apply_extensions(_plan_with_agent_md(), [plugin])


def _skill_dir_item(tmp_path: Path, name: str, skill_md: str) -> StagedItem:
    """A base shared-carrier skill DIR item with a real on-disk SKILL.md,
    mirroring Phase 2 staging."""
    src = tmp_path / "base" / "skills" / name
    _write(src / "SKILL.md", skill_md)
    return StagedItem(
        source_path=src,
        dest_relpath=Path("skills") / name,
        kind=FileKind.DIR,
        namespace="skills",
        provenance=Provenance(kind="tool", name="claude"),
        content=None,
        shared_carrier=True,
    )


def test_direct_file_item_is_patched_in_place(tmp_path: Path) -> None:
    """An agents/*.md NAMESPACED_MD item (non-SKILL.md base, AC #10) gets its
    content bytes replaced; provenance and kind are untouched."""
    plugin = _plugin(tmp_path, "p")
    _write(plugin.source_path / ".agents" / "extensions" / "00.yaml", _ext_yaml())

    plan = apply_extensions(_plan_with_agent_md(), [plugin])

    item = plan.items[Path("agents/reviewer.md")]
    assert item.content == b"# Reviewer\n\n## Boundaries\nbase\npatched\n"
    assert item.provenance == Provenance(kind="tool", name="claude")
    assert plan.dir_overrides == {}


def test_file_inside_dir_item_patches_into_dir_overrides(tmp_path: Path) -> None:
    """SKILL.md inside an opaque DIR item: patched bytes land in
    dir_overrides keyed by (dir dest, inner relpath); the DIR item itself
    stays content=None."""
    plugin = _plugin(tmp_path, "p")
    _write(
        plugin.source_path / ".agents" / "extensions" / "00.yaml",
        _ext_yaml(target_file="skills/demo/SKILL.md", target_section="Usage"),
    )
    item = _skill_dir_item(tmp_path, "demo", "# Demo\n\n## Usage\nbase\n")
    plan = StagingPlan(items={item.dest_relpath: item}, tool=Tool.CLAUDE)

    plan = apply_extensions(plan, [plugin])

    patched = plan.dir_overrides[Path("skills/demo")][Path("SKILL.md")]
    assert patched == b"# Demo\n\n## Usage\nbase\npatched\n"
    assert plan.items[Path("skills/demo")].content is None


def test_second_patch_sees_first_patch_result_in_dir_overrides(tmp_path: Path) -> None:
    """R6: later patches apply to the already-mutated bytes, not the source."""
    plugin = _plugin(tmp_path, "p")
    ext_dir = plugin.source_path / ".agents" / "extensions"
    _write(
        ext_dir / "00.yaml",
        _ext_yaml(target_file="skills/demo/SKILL.md", target_section="Usage", content="first"),
    )
    _write(
        ext_dir / "01.yaml",
        _ext_yaml(target_file="skills/demo/SKILL.md", target_section="Usage", content="second"),
    )
    item = _skill_dir_item(tmp_path, "demo", "# Demo\n\n## Usage\nbase\n")
    plan = StagingPlan(items={item.dest_relpath: item}, tool=Tool.CLAUDE)

    plan = apply_extensions(plan, [plugin])

    patched = plan.dir_overrides[Path("skills/demo")][Path("SKILL.md")]
    assert patched == b"# Demo\n\n## Usage\nbase\nfirst\nsecond\n"


def test_carrier_merge_contribution_for_other_inner_file_survives(tmp_path: Path) -> None:
    """dir_overrides is shared with the F.3 carrier-merge: a patch to
    SKILL.md must not clobber a carrier-carried sibling file's entry."""
    plugin = _plugin(tmp_path, "p")
    _write(
        plugin.source_path / ".agents" / "extensions" / "00.yaml",
        _ext_yaml(target_file="skills/demo/SKILL.md", target_section="Usage"),
    )
    item = _skill_dir_item(tmp_path, "demo", "# Demo\n\n## Usage\nbase\n")
    plan = StagingPlan(items={item.dest_relpath: item}, tool=Tool.CLAUDE)
    plan.dir_overrides[Path("skills/demo")] = {Path("cheats.md"): b"carried"}

    plan = apply_extensions(plan, [plugin])

    overrides = plan.dir_overrides[Path("skills/demo")]
    assert overrides[Path("cheats.md")] == b"carried"
    assert overrides[Path("SKILL.md")].endswith(b"patched\n")


@pytest.mark.parametrize(
    "target",
    [
        "agents/missing.md",  # no plan item at all
        "skills/demo/ABSENT.md",  # DIR item exists, inner file does not
        "skills/demo",  # names the DIR itself, not a file
    ],
)
def test_unresolvable_target_file_is_terminal(tmp_path: Path, target: str) -> None:
    plugin = _plugin(tmp_path, "p")
    _write(
        plugin.source_path / ".agents" / "extensions" / "00.yaml",
        _ext_yaml(target_file=target),
    )
    item = _skill_dir_item(tmp_path, "demo", "# Demo\n\n## Usage\nbase\n")
    plan = StagingPlan(items={item.dest_relpath: item}, tool=Tool.CLAUDE)

    with pytest.raises(ExtensionError, match="target-file not found in staging tree") as ei:
        apply_extensions(plan, [plugin])
    assert ei.value.target_file == Path(target)


def test_frontmatter_precision_through_extension_on_agent_md(tmp_path: Path) -> None:
    """AC #10: a frontmatter precision exercised through the full extension
    path against a non-SKILL.md base asset."""
    plugin = _plugin(tmp_path, "p")
    _write(
        plugin.source_path / ".agents" / "extensions" / "00.yaml",
        _ext_yaml(target_section="frontmatter", content="model: haiku"),
    )

    plan = apply_extensions(_plan_with_agent_md("---\nname: reviewer\n---\n# Reviewer\n"), [plugin])

    assert plan.items[Path("agents/reviewer.md")].content == (
        b"---\nname: reviewer\nmodel: haiku\n---\n# Reviewer\n"
    )


def test_section_errors_carry_yaml_and_target_citation(tmp_path: Path) -> None:
    """PatchError reasons surface as ExtensionError with both citation
    fields (R7 target-resolution rows)."""
    plugin = _plugin(tmp_path, "p")
    yaml_path = plugin.source_path / ".agents" / "extensions" / "00.yaml"
    _write(yaml_path, _ext_yaml(target_section="No Such Header"))

    with pytest.raises(ExtensionError, match='"No Such Header" not found') as ei:
        apply_extensions(_plan_with_agent_md(), [plugin])
    assert ei.value.yaml_path == yaml_path
    assert ei.value.target_file == Path("agents/reviewer.md")


def test_r6_ordering_plugin_alpha_then_shared_before_tool_then_filename(
    tmp_path: Path,
) -> None:
    """Four appends to one section across (plugin alpha x scope x filename)
    land in R6 order. Ordering is observable: appends compose positionally."""
    alpha = _plugin(tmp_path, "alpha")
    zeta = _plugin(tmp_path, "zeta")
    _write(
        alpha.source_path / ".agents" / "extensions" / "10.yaml",
        _ext_yaml(content="alpha-shared-10"),
    )
    _write(
        alpha.source_path / ".agents" / "extensions" / "20.yaml",
        _ext_yaml(content="alpha-shared-20"),
    )
    _write(
        alpha.source_path / ".claude" / "extensions" / "00.yaml",
        _ext_yaml(content="alpha-tool-00"),
    )  # filename sorts first; scope still loses
    _write(
        zeta.source_path / ".agents" / "extensions" / "00.yaml",
        _ext_yaml(content="zeta-shared-00"),
    )

    # Pass plugins deliberately unsorted: ordering is the module's decision.
    plan = apply_extensions(_plan_with_agent_md("## Boundaries\nbase\n"), [zeta, alpha])

    assert plan.items[Path("agents/reviewer.md")].content == (
        b"## Boundaries\nbase\nalpha-shared-10\nalpha-shared-20\nalpha-tool-00\nzeta-shared-00\n"
    )


def test_ordering_changes_the_result_for_replace(tmp_path: Path) -> None:
    """AC #5: with two replaces on one section, the R6-last patch wins —
    a different order would leave different bytes."""
    alpha = _plugin(tmp_path, "alpha")
    zeta = _plugin(tmp_path, "zeta")
    _write(
        alpha.source_path / ".agents" / "extensions" / "00.yaml",
        _ext_yaml(precision="replace", content="from-alpha"),
    )
    _write(
        zeta.source_path / ".agents" / "extensions" / "00.yaml",
        _ext_yaml(precision="replace", content="from-zeta"),
    )

    plan = apply_extensions(_plan_with_agent_md("## Boundaries\nbase\n"), [alpha, zeta])

    assert plan.items[Path("agents/reviewer.md")].content == b"## Boundaries\nfrom-zeta\n"


def test_patch_introduced_header_is_targetable_by_a_later_patch(tmp_path: Path) -> None:
    """AC #6 now-resolvable: 0 matches without the earlier patch, 1 with it."""
    plugin = _plugin(tmp_path, "p")
    ext_dir = plugin.source_path / ".agents" / "extensions"
    _write(ext_dir / "00.yaml", _ext_yaml(content="## Brand New\nseed"))
    _write(ext_dir / "01.yaml", _ext_yaml(target_section="Brand New", content="landed"))

    plan = apply_extensions(_plan_with_agent_md("## Boundaries\nbase\n"), [plugin])

    assert plan.items[Path("agents/reviewer.md")].content == (
        b"## Boundaries\nbase\n## Brand New\nseed\nlanded\n"
    )


def test_patch_introduced_duplicate_header_makes_later_patch_ambiguous(
    tmp_path: Path,
) -> None:
    """AC #6 now-ambiguous: 1 match without the earlier patch, 2 with it."""
    plugin = _plugin(tmp_path, "p")
    ext_dir = plugin.source_path / ".agents" / "extensions"
    _write(ext_dir / "00.yaml", _ext_yaml(content="## Boundaries\nshadow"))
    _write(ext_dir / "01.yaml", _ext_yaml(content="never-applied"))

    with pytest.raises(ExtensionError, match="appears 2 times; ambiguous"):
        apply_extensions(_plan_with_agent_md("## Boundaries\nbase\n"), [plugin])


def test_tool_scope_applies_only_to_its_own_tool(tmp_path: Path) -> None:
    """AC #7: a .claude/extensions patch lands in the Claude plan only; a
    .agents/extensions patch lands in both Claude and Codex plans."""
    plugin = _plugin(tmp_path, "p")
    _write(
        plugin.source_path / ".agents" / "extensions" / "00.yaml",
        _ext_yaml(content="shared"),
    )
    _write(
        plugin.source_path / ".claude" / "extensions" / "00.yaml",
        _ext_yaml(content="claude-only"),
    )

    claude_plan = apply_extensions(_plan_with_agent_md("## Boundaries\nbase\n"), [plugin])
    codex_plan = apply_extensions(
        StagingPlan(
            items=dict(_plan_with_agent_md("## Boundaries\nbase\n").items), tool=Tool.CODEX
        ),
        [plugin],
    )

    assert claude_plan.items[Path("agents/reviewer.md")].content == (
        b"## Boundaries\nbase\nshared\nclaude-only\n"
    )
    assert codex_plan.items[Path("agents/reviewer.md")].content == (
        b"## Boundaries\nbase\nshared\n"
    )


def test_plugin_without_extension_dirs_is_a_noop(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path, "p")
    base = _plan_with_agent_md()
    original = base.items[Path("agents/reviewer.md")].content

    plan = apply_extensions(base, [plugin])

    assert plan.items[Path("agents/reviewer.md")].content == original
