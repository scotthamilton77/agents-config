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

    counters = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        home=home,
        config=config,
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert not retired.exists()
    assert counters.pruned == 1


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

    counters = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        home=home,
        config=config,
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert not formula.exists()
    assert counters.pruned == 1


def test_no_orphans_is_clean_noop(tmp_path: Path) -> None:
    """
    Given a dest tree with nothing matching the prune globs
    When prune_pipeline runs
    Then pruned == 0 (no scan hit, flow no-ops on empty list).
    """
    home = _claude_home_with_settings(tmp_path)
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}
    config = InstallerToml(prune_globs=["*/skills/never-matches"])

    counters = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        home=home,
        config=config,
        io=ScriptedIO(interactive=True),
        timestamp=_TS,
    )

    assert counters.pruned == 0
