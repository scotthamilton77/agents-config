"""Phase 6 plugin overlay (core/overlay.py).

Behavioural tests for ``overlay_plugins``: it overlays each active plugin's
``.agents/`` and ``.<tool>/`` content onto a base ``StagingPlan`` in alphabetical
plugin order, routing every ``dest_relpath`` collision through the Epic-E merge
registry, and reusing the tool adapter's namespace rules. Carrier-merge of the
shared skills/agents DIR-collision path lives here too (Decision B of the epic's
Plugin Seam Integration Brief).

Each test pins a coded routing/ordering/merge decision, observed on the returned
plan — never a mock call-count. The merge *strategies* themselves are unit-
tested in tests/unit/test_{append_rules,json_union,fatal,last_wins}.py; here we
pin only that the overlay dispatches to them on the right keys.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from installer.core.merge.base import CollisionError
from installer.core.merge.registry import default_registry
from installer.core.model import (
    FileKind,
    Provenance,
    StagedItem,
    StagingPlan,
    Tool,
)
from installer.core.overlay import overlay_plugins
from installer.plugins.generic import GenericPluginAdapter
from installer.tools.claude import ClaudeAdapter
from installer.tools.opencode import OpenCodeAdapter


@dataclass(frozen=True, slots=True)
class _Plugin:
    """Minimal PluginAdapter: a name and an on-disk source tree. Mirrors
    GenericPluginAdapter's shape without its is_detected probe (the overlay
    never re-checks detection — the active set is already resolved)."""

    name: str
    source_path: Path

    def is_detected(self, home: Path) -> bool:  # noqa: ARG002  # inert  # pragma: no cover
        return True


def _empty_plan() -> StagingPlan:
    return StagingPlan(items={}, tool=Tool.CLAUDE)


def _plugin(tmp_path: Path, name: str) -> _Plugin:
    root = tmp_path / "plugins" / name
    root.mkdir(parents=True)
    return _Plugin(name=name, source_path=root)


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_disjoint_plugin_content_is_added_to_the_plan(tmp_path: Path) -> None:
    """A plugin rule with no base-side collision simply lands in the plan."""
    plugin = _plugin(tmp_path, "test-plugin")
    _write(plugin.source_path / ".claude" / "rules" / "extra.md", b"plugin rule")

    plan = overlay_plugins(
        _empty_plan(),
        [plugin],
        adapter=ClaudeAdapter(),
        registry=default_registry(),
    )

    item = plan.items[Path("rules/extra.md")]
    assert item.content == b"plugin rule"
    assert item.provenance == Provenance(kind="plugin", name="test-plugin")
    # No carrier-merge happened, so the side channel stays empty.
    assert plan.dir_overrides == {}


def test_skill_dir_overlay_without_collision_records_no_override(tmp_path: Path) -> None:
    """A plugin skill dir landing on an UNOCCUPIED destination is added as a
    plain DIR item (its bytes come from source_path at sync); it is not a
    carrier-merge, so nothing is written to dir_overrides. The channel is only
    for the second-source-tree case."""
    plugin = _plugin_skill_dir(tmp_path, "test-plugin", files=["SKILL.md"])

    plan = overlay_plugins(
        _empty_plan(), [plugin], adapter=ClaudeAdapter(), registry=default_registry()
    )

    assert plan.items[Path("skills/demo-skill")].kind is FileKind.DIR
    assert plan.dir_overrides == {}


def _base_item(
    dest: str,
    *,
    kind: FileKind,
    namespace: str | None,
    content: bytes | None,
    shared_carrier: bool = False,
) -> StagedItem:
    """A base-staged (tool-provenance) item to pre-seed a plan with, so an
    overlaid plugin item collides with it."""
    return StagedItem(
        source_path=Path("/base") / dest,
        dest_relpath=Path(dest),
        kind=kind,
        namespace=namespace,
        provenance=Provenance(kind="tool", name="claude"),
        content=content,
        shared_carrier=shared_carrier,
    )


def _seeded_plan(item: StagedItem) -> StagingPlan:
    return StagingPlan(items={item.dest_relpath: item}, tool=Tool.CLAUDE)


def test_plugin_rule_appends_to_base_rule(tmp_path: Path) -> None:
    """A plugin rules/foo.md colliding with a base rules/foo.md append-merges:
    the two bodies are joined with the canonical b'\\n---\\n' separator
    (bead AC #1)."""
    plan = _seeded_plan(
        _base_item(
            "rules/shared.md",
            kind=FileKind.NAMESPACED_MD,
            namespace="rules",
            content=b"base",
        )
    )
    plugin = _plugin(tmp_path, "test-plugin")
    _write(plugin.source_path / ".claude" / "rules" / "shared.md", b"plugin")

    overlay_plugins(plan, [plugin], adapter=ClaudeAdapter(), registry=default_registry())

    assert plan.items[Path("rules/shared.md")].content == b"base\n---\nplugin"


def test_plugin_command_same_name_as_base_command_is_fatal(tmp_path: Path) -> None:
    """A plugin commands/foo.md colliding with a base commands/foo.md is an
    irreconcilable collision — the registry routes (NAMESPACED_MD, "commands")
    to the fatal strategy (bead AC #2)."""
    plan = _seeded_plan(
        _base_item(
            "commands/go.md", kind=FileKind.NAMESPACED_MD, namespace="commands", content=b"base"
        )
    )
    plugin = _plugin(tmp_path, "test-plugin")
    _write(plugin.source_path / ".claude" / "commands" / "go.md", b"plugin")

    with pytest.raises(CollisionError):
        overlay_plugins(plan, [plugin], adapter=ClaudeAdapter(), registry=default_registry())


def test_plugin_settings_deep_union_merges_into_base(tmp_path: Path) -> None:
    """A plugin settings.json fragment deep-union-merges into the base settings:
    a base-only key and a plugin-only key both survive (bead AC #3)."""
    plan = _seeded_plan(
        _base_item(
            "settings.json",
            kind=FileKind.SETTINGS_JSON,
            namespace=None,
            content=b'{"base": 1}',
        )
    )
    plugin = _plugin(tmp_path, "test-plugin")
    _write(plugin.source_path / ".claude" / "settings.json.template", b'{"plugin": 2}')

    overlay_plugins(plan, [plugin], adapter=ClaudeAdapter(), registry=default_registry())

    merged = json.loads(plan.items[Path("settings.json")].content or b"{}")
    assert merged == {"base": 1, "plugin": 2}


def test_plugin_toml_collision_is_last_wins_with_warning(tmp_path: Path) -> None:
    """A plugin *.toml colliding with a base *.toml resolves last-wins and warns
    (the registry routes (TOML, None) to LastWinsWarnStrategy)."""
    plan = _seeded_plan(
        _base_item("config.toml", kind=FileKind.TOML, namespace=None, content=b"base=1")
    )
    plugin = _plugin(tmp_path, "test-plugin")
    _write(plugin.source_path / ".claude" / "config.toml.template", b"plugin=2")

    with pytest.warns(UserWarning):
        overlay_plugins(plan, [plugin], adapter=ClaudeAdapter(), registry=default_registry())

    assert plan.items[Path("config.toml")].content == b"plugin=2"


def test_plugins_apply_in_alphabetical_order(tmp_path: Path) -> None:
    """Two plugins both contribute config.toml; the later (alphabetical) plugin
    wins the last-wins collision. Passing them in REVERSE order proves the
    overlay sorts internally rather than honouring caller order (bead AC #4)."""
    a_plugin = _plugin(tmp_path, "a-plugin")
    z_plugin = _plugin(tmp_path, "z-plugin")
    _write(a_plugin.source_path / ".claude" / "config.toml.template", b"who='a'")
    _write(z_plugin.source_path / ".claude" / "config.toml.template", b"who='z'")

    # Deliberately reversed input order: z first, a second.
    with pytest.warns(UserWarning):
        plan = overlay_plugins(
            _empty_plan(),
            [z_plugin, a_plugin],
            adapter=ClaudeAdapter(),
            registry=default_registry(),
        )

    # z applied last (alphabetical), so z wins regardless of input order.
    assert plan.items[Path("config.toml")].content == b"who='z'"


def test_overlay_reuses_tool_adapter_namespace_skip(tmp_path: Path) -> None:
    """The overlay has no namespace routing of its own — it consults the tool
    adapter's should_install_namespace. OpenCode skips the shared agents/
    namespace, so a plugin's .agents/agents/ content is dropped while its
    .agents/skills/ content is kept."""
    plugin = _plugin(tmp_path, "test-plugin")
    _write(plugin.source_path / ".agents" / "agents" / "skipme.md", b"agent")
    (plugin.source_path / ".agents" / "skills" / "keepme").mkdir(parents=True)

    plan = overlay_plugins(
        StagingPlan(items={}, tool=Tool.OPENCODE),
        [plugin],
        adapter=OpenCodeAdapter(),
        registry=default_registry(),
    )

    assert Path("agents/skipme.md") not in plan.items
    assert Path("skills/keepme") in plan.items


@dataclass(frozen=True, slots=True)
class _CommandsOptOutAdapter:
    """A tool adapter that opts a TOOL-scope namespace (commands) out. Pins that
    the overlay gates tool-scope namespaces through should_install_namespace too,
    not just shared-scope ones — a plugin's .<tool>/commands/ content is dropped
    when the adapter declines that namespace."""

    name: str = "claude"

    def should_install_namespace(self, namespace: str, source: str) -> bool:
        return not (namespace == "commands" and source == "tool")


def test_overlay_gates_tool_scope_namespaces_via_adapter(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path, "test-plugin")
    _write(plugin.source_path / ".claude" / "commands" / "skipme.md", b"cmd")
    _write(plugin.source_path / ".claude" / "rules" / "keepme.md", b"rule")

    plan = overlay_plugins(
        _empty_plan(),
        [plugin],
        adapter=_CommandsOptOutAdapter(),  # type: ignore[arg-type]  # structural ToolAdapter subset
        registry=default_registry(),
    )

    assert Path("commands/skipme.md") not in plan.items
    assert Path("rules/keepme.md") in plan.items


def _carrier_dir_plan(tmp_path: Path, *, files: list[str]) -> StagingPlan:
    """A plan pre-seeded with a shared_carrier skills/ DIR item whose on-disk
    source_path holds ``files`` (the carrier-side file set)."""
    carrier_src = tmp_path / "shared" / "skills" / "demo-skill"
    carrier_src.mkdir(parents=True)
    for name in files:
        (carrier_src / name).write_bytes(b"carrier")
    item = StagedItem(
        source_path=carrier_src,
        dest_relpath=Path("skills/demo-skill"),
        kind=FileKind.DIR,
        namespace="skills",
        provenance=Provenance(kind="tool", name="claude"),
        content=None,
        shared_carrier=True,
    )
    return _seeded_plan(item)


def _plugin_skill_dir(tmp_path: Path, name: str, *, files: list[str]) -> _Plugin:
    """A plugin whose .agents/skills/demo-skill/ dir holds ``files``."""
    plugin = _plugin(tmp_path, name)
    skill_dir = plugin.source_path / ".agents" / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    for fname in files:
        (skill_dir / fname).write_bytes(b"plugin")
    return plugin


def test_carrier_merge_disjoint_files_succeeds_and_clears_flag(tmp_path: Path) -> None:
    """A plugin skill dir overlaying a shared_carrier dir with a DISJOINT file
    set carrier-merges: no fatal error, the carrier item stays, and its
    shared_carrier flag is cleared (mirrors bash `rm -f sentinel`)."""
    plan = _carrier_dir_plan(tmp_path, files=["_test.sh"])
    plugin = _plugin_skill_dir(tmp_path, "test-plugin", files=["SKILL.md"])

    overlay_plugins(plan, [plugin], adapter=ClaudeAdapter(), registry=default_registry())

    merged = plan.items[Path("skills/demo-skill")]
    assert merged.kind is FileKind.DIR
    assert merged.shared_carrier is False


def test_carrier_merge_records_plugin_file_bytes_in_dir_overrides(tmp_path: Path) -> None:
    """The carrier-merge does not silently drop the plugin's added file: its
    bytes are recorded in plan.dir_overrides, keyed by the carrier DIR's
    dest_relpath then the inner file relpath. This is the F.3 file-carry channel
    that the later plan-walking DIR-sync emits alongside the carrier's own
    files."""
    plan = _carrier_dir_plan(tmp_path, files=["_test.sh"])
    plugin = _plugin_skill_dir(tmp_path, "test-plugin", files=["SKILL.md"])

    overlay_plugins(plan, [plugin], adapter=ClaudeAdapter(), registry=default_registry())

    dest = Path("skills/demo-skill")
    assert plan.dir_overrides[dest] == {Path("SKILL.md"): b"plugin"}


def test_carrier_merge_carries_every_plugin_file(tmp_path: Path) -> None:
    """A plugin contributing several disjoint files has ALL of them represented
    in dir_overrides, not just the first — the carry iterates the whole added
    file set."""
    plan = _carrier_dir_plan(tmp_path, files=["_test.sh"])
    plugin = _plugin_skill_dir(tmp_path, "test-plugin", files=["SKILL.md", "ref.md", "helper.py"])

    overlay_plugins(plan, [plugin], adapter=ClaudeAdapter(), registry=default_registry())

    assert plan.dir_overrides[Path("skills/demo-skill")] == {
        Path("SKILL.md"): b"plugin",
        Path("ref.md"): b"plugin",
        Path("helper.py"): b"plugin",
    }


def test_carrier_merge_override_holds_only_plugin_files_not_carrier_own(tmp_path: Path) -> None:
    """The override map holds the PLUGIN's added files only. The carrier's own
    files (read from its source_path at sync) are not duplicated into the
    channel — dir_overrides is the second source tree, not the merged whole."""
    plan = _carrier_dir_plan(tmp_path, files=["_test.sh", "README.md"])
    plugin = _plugin_skill_dir(tmp_path, "test-plugin", files=["SKILL.md"])

    overlay_plugins(plan, [plugin], adapter=ClaudeAdapter(), registry=default_registry())

    overrides = plan.dir_overrides[Path("skills/demo-skill")]
    assert overrides == {Path("SKILL.md"): b"plugin"}
    assert Path("_test.sh") not in overrides
    assert Path("README.md") not in overrides


def test_carrier_merge_does_not_carry_top_level_dotfiles(tmp_path: Path) -> None:
    """A top-level dotfile in the plugin dir is NOT carried: bash's
    `for sfile in "$src"/*` skips dot-prefixed entries, so they never reach the
    copy. This matches the dotfile exclusion the disjoint check already
    applies — a shared `.gitkeep` does not block the merge AND is not copied."""
    plan = _carrier_dir_plan(tmp_path, files=["_test.sh", ".gitkeep"])
    plugin = _plugin_skill_dir(tmp_path, "test-plugin", files=["SKILL.md", ".gitkeep"])

    overlay_plugins(plan, [plugin], adapter=ClaudeAdapter(), registry=default_registry())

    assert plan.dir_overrides[Path("skills/demo-skill")] == {Path("SKILL.md"): b"plugin"}


def test_carrier_merge_carries_nested_subdirectory_files(tmp_path: Path) -> None:
    """A subdirectory in the plugin dir is carried wholesale (bash `cp -R`):
    each nested file is represented under its relpath (e.g. `lib/util.py`), and
    a dotfile NESTED under a carried subdir is kept (cp -R copies it) — unlike a
    top-level dotfile."""
    plan = _carrier_dir_plan(tmp_path, files=["_test.sh"])
    plugin = _plugin(tmp_path, "test-plugin")
    skill_dir = plugin.source_path / ".agents" / "skills" / "demo-skill"
    (skill_dir / "lib").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_bytes(b"top")
    (skill_dir / "lib" / "util.py").write_bytes(b"nested")
    (skill_dir / "lib" / ".keep").write_bytes(b"dot-nested")

    overlay_plugins(plan, [plugin], adapter=ClaudeAdapter(), registry=default_registry())

    assert plan.dir_overrides[Path("skills/demo-skill")] == {
        Path("SKILL.md"): b"top",
        Path("lib/util.py"): b"nested",
        Path("lib/.keep"): b"dot-nested",
    }


def test_carrier_merge_overlapping_files_is_fatal(tmp_path: Path) -> None:
    """A plugin skill dir overlaying a shared_carrier dir with an OVERLAPPING
    file name cannot carrier-merge — it is a real conflict and falls through to
    the registry's fatal DIR strategy."""
    plan = _carrier_dir_plan(tmp_path, files=["SKILL.md"])
    plugin = _plugin_skill_dir(tmp_path, "test-plugin", files=["SKILL.md"])

    with pytest.raises(CollisionError):
        overlay_plugins(plan, [plugin], adapter=ClaudeAdapter(), registry=default_registry())


def test_non_carrier_dir_collision_is_fatal_even_when_disjoint(tmp_path: Path) -> None:
    """A DIR collision on a NON-carrier item is fatal regardless of file-set
    disjointness — the shared_carrier flag, not the file sets, is what unlocks
    carrier-merge."""
    plan = _carrier_dir_plan(tmp_path, files=["_test.sh"])
    # Strip the carrier flag: now it is an ordinary DIR item.
    seeded = plan.items[Path("skills/demo-skill")]
    plan.items[Path("skills/demo-skill")] = replace(seeded, shared_carrier=False)
    plugin = _plugin_skill_dir(tmp_path, "test-plugin", files=["SKILL.md"])  # disjoint

    with pytest.raises(CollisionError):
        overlay_plugins(plan, [plugin], adapter=ClaudeAdapter(), registry=default_registry())


def test_tool_scope_plugin_dir_cannot_carrier_merge(tmp_path: Path) -> None:
    """Carrier-merge is eligible ONLY for content from the plugin's .agents/
    (shared) tree. A tool-scope plugin DIR (.<tool>/skills/...) colliding with a
    shared_carrier dir is fatal even with a disjoint file set — mirrors the bash
    guard requiring the incoming src under /src/plugins/<p>/.agents/."""
    plan = _carrier_dir_plan(tmp_path, files=["_test.sh"])
    plugin = _plugin(tmp_path, "test-plugin")
    # Tool-scope (.claude/), NOT .agents/ — disjoint file set, but ineligible.
    tool_skill = plugin.source_path / ".claude" / "skills" / "demo-skill"
    tool_skill.mkdir(parents=True)
    (tool_skill / "SKILL.md").write_bytes(b"plugin")

    with pytest.raises(CollisionError):
        overlay_plugins(plan, [plugin], adapter=ClaudeAdapter(), registry=default_registry())


def test_carrier_merge_ignores_dotfiles_in_disjoint_check(tmp_path: Path) -> None:
    """Dotfiles are excluded from the disjointness comparison (bash `"$dir"/*`
    skips them): a shared carrier and an incoming plugin dir that share only a
    dot-prefixed entry still carrier-merge."""
    plan = _carrier_dir_plan(tmp_path, files=["_test.sh", ".gitkeep"])
    plugin = _plugin_skill_dir(tmp_path, "test-plugin", files=["SKILL.md", ".gitkeep"])

    overlay_plugins(plan, [plugin], adapter=ClaudeAdapter(), registry=default_registry())

    assert plan.items[Path("skills/demo-skill")].shared_carrier is False


def test_second_plugin_on_merged_carrier_is_fatal(tmp_path: Path) -> None:
    """After one plugin carrier-merges (clearing the flag), a SECOND plugin
    colliding on the same dir is a true plugin-plugin collision and fatal —
    even with a disjoint file set (mirrors bash `rm -f sentinel`)."""
    plan = _carrier_dir_plan(tmp_path, files=["_test.sh"])
    first = _plugin_skill_dir(tmp_path, "a-plugin", files=["SKILL.md"])
    second = _plugin_skill_dir(tmp_path, "z-plugin", files=["OTHER.md"])  # disjoint from carrier

    with pytest.raises(CollisionError):
        overlay_plugins(plan, [first, second], adapter=ClaudeAdapter(), registry=default_registry())


# ── Against the canonical committed test-plugin fixture ──────────────────────

_SOURCES = Path(__file__).parents[1] / "fixtures" / "sources"


def _test_plugin_adapter() -> GenericPluginAdapter:
    return GenericPluginAdapter(name="test-plugin", source_path=_SOURCES / "test-plugin")


def test_fixture_plugin_rule_appends_to_a_colliding_base_rule() -> None:
    """End-to-end against the committed fixture: its .claude/rules/test-plugin-
    rule.md append-merges onto a colliding base rule of the same name."""
    plan = _seeded_plan(
        _base_item(
            "rules/test-plugin-rule.md",
            kind=FileKind.NAMESPACED_MD,
            namespace="rules",
            content=b"base body",
        )
    )

    overlay_plugins(
        plan, [_test_plugin_adapter()], adapter=ClaudeAdapter(), registry=default_registry()
    )

    merged = plan.items[Path("rules/test-plugin-rule.md")].content
    assert merged is not None
    assert merged.startswith(b"base body\n---\n")
    assert b"test-plugin-rule" in merged


def test_fixture_plugin_command_collision_is_fatal() -> None:
    """The fixture's .claude/commands/test-plugin-command.md is fatal when it
    collides with a base command of the same name."""
    plan = _seeded_plan(
        _base_item(
            "commands/test-plugin-command.md",
            kind=FileKind.NAMESPACED_MD,
            namespace="commands",
            content=b"base command",
        )
    )

    with pytest.raises(CollisionError):
        overlay_plugins(
            plan, [_test_plugin_adapter()], adapter=ClaudeAdapter(), registry=default_registry()
        )


def test_fixture_plugin_settings_union_merges_with_base() -> None:
    """The fixture's .claude/settings.json.template deep-union-merges with a base
    settings.json: the base permission survives alongside the plugin's."""
    plan = _seeded_plan(
        _base_item(
            "settings.json",
            kind=FileKind.SETTINGS_JSON,
            namespace=None,
            content=b'{"permissions": {"allow": ["Bash(base:*)"]}}',
        )
    )

    overlay_plugins(
        plan, [_test_plugin_adapter()], adapter=ClaudeAdapter(), registry=default_registry()
    )

    merged = json.loads(plan.items[Path("settings.json")].content or b"{}")
    allow = merged["permissions"]["allow"]
    assert "Bash(base:*)" in allow
    assert "Bash(test-plugin:*)" in allow


def test_fixture_plugin_skill_overlays_without_collision() -> None:
    """The fixture's shared-scope .agents/skills/test-plugin-skill/ lands in the
    plan as a DIR when no base item occupies that destination."""
    plan = overlay_plugins(
        _empty_plan(),
        [_test_plugin_adapter()],
        adapter=ClaudeAdapter(),
        registry=default_registry(),
    )

    assert plan.items[Path("skills/test-plugin-skill")].kind is FileKind.DIR
