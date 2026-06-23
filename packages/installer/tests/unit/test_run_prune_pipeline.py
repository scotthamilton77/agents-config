"""Unit tests for installer.core.run.prune_pipeline (G.5 — scan + flow composition).

``prune_pipeline`` is the install-side composition that G.5 wires behind the
``--prune`` / ``--prune-only`` flags: scan the active tools' dest trees against
their in-memory plans for orphans, then drive the interactive prune flow. These
tests pin the composition's end-state, driving it through ``ScriptedIO`` and the
real filesystem — not the call sequence.

Covered decisions:
- an unstaged, glob-matched dest entry is scanned AND pruned (scan -> flow),
- an empty staging plan with an excluded-plugin file flags + prunes that file
  (strict mode: nothing staged it),
- a no-orphan tree is a clean no-op.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.installer_toml import InstallerToml
from installer.core.io_port import ScriptedIO
from installer.core.model import StagingPlan, Tool
from installer.core.run import prune_pipeline
from installer.plugins.beads import BeadsPlugin
from installer.tools.registry import get_adapter

_TS = "20250101-120000"


def _claude_home_with_settings(tmp_path: Path) -> Path:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    return tmp_path


def test_unstaged_matched_entry_is_scanned_and_pruned(tmp_path: Path) -> None:
    """
    Given a claude skills/ entry absent from the plan and matching a glob
    When prune_pipeline runs under auto_yes
    Then it is deleted (the scan feeds the flow) and pruned == 1.
    """
    home = _claude_home_with_settings(tmp_path)
    retired = home / ".claude" / "skills" / "retired-skill"
    retired.mkdir(parents=True)
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}
    config = InstallerToml(prune_globs=["*/skills/retired-skill"])

    per_tool = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        home=home,
        config=config,
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert not retired.exists()
    assert per_tool["claude"].pruned == 1


def test_prune_pipeline_groups_counters_by_orphan_tool(tmp_path: Path) -> None:
    """
    Given a claude skills/ orphan AND a ~/.beads/formulas orphan, both matching
    the prune globs
    When prune_pipeline runs under auto_yes
    Then the returned mapping buckets each pruned orphan under its OWN
    Orphan.tool — claude.pruned==1 and beads.pruned==1 — rather than summing both
    into one tool's tally.

    Pins the 8.18 prune plumbing change: the beads bucket carries a plugin
    namespace (not a Tool) and must surface separately so the summary can report
    a plugin pruned outside the active tool set (bash AC#19). Fails while
    run_prune returns a single aggregate Counters.
    """
    home = _claude_home_with_settings(tmp_path)
    claude_orphan = home / ".claude" / "skills" / "retired-skill"
    claude_orphan.mkdir(parents=True)
    beads_orphan = home / ".beads" / "formulas" / "stale.toml"
    beads_orphan.parent.mkdir(parents=True)
    beads_orphan.write_text("x")
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}
    config = InstallerToml(prune_globs=["*/skills/retired-skill", "beads/formulas/*"])

    per_tool = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        home=home,
        config=config,
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert not claude_orphan.exists()
    assert not beads_orphan.exists()
    assert per_tool["claude"].pruned == 1
    assert per_tool["beads"].pruned == 1


def test_empty_plan_with_excluded_plugin_file_flags_it(tmp_path: Path) -> None:
    """
    Given a ~/.beads/formulas file and an empty plan set (plugin excluded)
    When prune_pipeline runs under auto_yes with a matching glob
    Then the formula is pruned (strict mode: excluded plugin -> all its files
    are orphans).
    """
    home = _claude_home_with_settings(tmp_path)
    formula = home / ".beads" / "formulas" / "stale.toml"
    formula.parent.mkdir(parents=True)
    formula.write_text("x")
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}
    config = InstallerToml(prune_globs=["beads/formulas/*"])

    per_tool = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        home=home,
        config=config,
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert not formula.exists()
    assert per_tool["beads"].pruned == 1


def test_active_plugin_formula_survives_prune(tmp_path: Path) -> None:
    """
    Given an active beads plugin still shipping current.toml, and a
    ~/.beads/formulas dir holding current.toml + retired.toml, both glob-matched
    When prune_pipeline runs with that plugin active under auto_yes
    Then retired.toml is pruned but current.toml survives — prune_pipeline
    forwards the active plugins so the scan protects a still-shipped formula.

    Pins the wiring: without the plugins forwarding, strict mode would delete
    current.toml alongside retired.toml.
    """
    home = _claude_home_with_settings(tmp_path)
    src = tmp_path / "src" / "plugins" / "beads"
    (src / ".beads" / "formulas").mkdir(parents=True)
    (src / ".beads" / "formulas" / "current.toml").write_text("shipped")
    formulas = home / ".beads" / "formulas"
    formulas.mkdir(parents=True)
    (formulas / "current.toml").write_text("shipped")
    (formulas / "retired.toml").write_text("stale")
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}
    config = InstallerToml(prune_globs=["beads/formulas/*"])
    beads = BeadsPlugin(name="beads", source_path=src, which=lambda _c: None)

    per_tool = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plugins=[beads],
        plans=plans,
        home=home,
        config=config,
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert (formulas / "current.toml").exists()
    assert not (formulas / "retired.toml").exists()
    assert per_tool["beads"].pruned == 1


def test_no_orphans_is_clean_noop(tmp_path: Path) -> None:
    """
    Given a dest tree with nothing matching the prune globs
    When prune_pipeline runs
    Then pruned == 0 (no scan hit, flow no-ops on empty list).
    """
    home = _claude_home_with_settings(tmp_path)
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}
    config = InstallerToml(prune_globs=["*/skills/never-matches"])

    per_tool = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        home=home,
        config=config,
        io=ScriptedIO(interactive=True),
        timestamp=_TS,
    )

    # No orphans -> a clean no-op -> no per-tool buckets at all.
    assert per_tool == {}
