"""End-to-end staging plan build over a fixture repo, driving the real
OpenCodeAdapter — this is where OpenCodeAdapter.should_install_namespace
earns behavioural coverage.

Pins the key OpenCode divergence from Claude/Codex: the shared agents/
namespace is NOT staged (OpenCode's agent frontmatter uses provider-prefixed
model IDs plus mode:/permission: keys, unlike the shared format), while shared
skills/ and rules/ ARE staged (rules remain available for
DYNAMIC-INCLUDE-ALL-RULES inlining).
"""

from __future__ import annotations

from pathlib import Path

from installer.core.installignore import InstallIgnore
from installer.core.io_port import ScriptedIO
from installer.core.model import StagingPlan, Tool
from installer.core.staging import build_plan
from installer.core.templates import flatten_plan_templates
from installer.tools.opencode import OpenCodeAdapter


def _make_opencode_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shared = repo / "src" / "user" / ".agents"
    opencode = repo / "src" / "user" / ".opencode"
    # shared namespaces
    (shared / "rules").mkdir(parents=True)
    (shared / "rules" / "delegation.md").write_bytes(b"shared rule")
    (shared / "skills").mkdir(parents=True)
    (shared / "skills" / "shared-skill").mkdir()
    (shared / "agents").mkdir(parents=True)
    (shared / "agents" / "shared-agent.md").write_bytes(b"agent")
    (shared / "INSTRUCTIONS.md.template").write_bytes(b"# shared root tmpl")
    # opencode tool root — templates + settings, no namespace subdirs
    opencode.mkdir(parents=True)
    # Synthetic template exercising the ALL-RULES marker grammar: no current
    # OpenCode template carries it (the real one is a single DYNAMIC-INCLUDE
    # of USER-CORE.md.template) — this fixture is what a template WOULD need
    # for flatten_plan_templates to inline the staged rules and drop the
    # loose copies.
    (opencode / "AGENTS.md.template").write_bytes(
        b"# opencode root tmpl\n<!-- DYNAMIC-INCLUDE-ALL-RULES -->\n"
    )
    (opencode / "opencode.jsonc.template").write_bytes(b"{}")
    return repo


def test_opencode_build_plan_skips_shared_agents(tmp_path: Path, ignore: InstallIgnore) -> None:
    """
    Given a repo with shared agents/ content
    When build_plan runs with OpenCodeAdapter
    Then no agents/ items appear in the plan.

    Pins: should_install_namespace returns False for ("agents", "shared"),
    so Phase 2 omits the shared agents namespace for OpenCode.
    """
    repo = _make_opencode_repo(tmp_path)

    plan = build_plan(OpenCodeAdapter(), repo_root=repo, ignore=ignore)

    assert not any(item.namespace == "agents" for item in plan.items.values())
    assert Path("agents/shared-agent.md") not in plan.items


def test_opencode_build_plan_keeps_shared_skills_and_rules(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    """
    Given a repo with shared skills/ and rules/ content
    When build_plan runs with OpenCodeAdapter
    Then skills/ and rules/ items appear in the plan.

    Pins: the agents skip is surgical — skills and rules are still staged
    (rules feed DYNAMIC-INCLUDE-ALL-RULES; only agents are dropped).
    """
    repo = _make_opencode_repo(tmp_path)

    plan = build_plan(OpenCodeAdapter(), repo_root=repo, ignore=ignore)

    assert isinstance(plan, StagingPlan)
    assert plan.tool == Tool.OPENCODE
    assert Path("skills/shared-skill") in plan.items
    assert Path("rules/delegation.md") in plan.items
    assert Path("AGENTS.md") in plan.items  # tool template (Phase 3), suffix stripped


def test_opencode_build_plan_stages_jsonc_settings(tmp_path: Path, ignore: InstallIgnore) -> None:
    """
    Given src/user/.opencode/opencode.jsonc.template
    When build_plan runs with OpenCodeAdapter
    Then opencode.jsonc appears in the plan (suffix stripped).

    Pins bead AC #3 end-to-end through the adapter: OpenCodeAdapter.source_dir
    points Phase 5 settings staging at .opencode, so the tool-specific jsonc
    lands at the OpenCode root rather than being dropped.
    """
    repo = _make_opencode_repo(tmp_path)

    plan = build_plan(OpenCodeAdapter(), repo_root=repo, ignore=ignore)

    assert Path("opencode.jsonc") in plan.items


def test_opencode_flatten_inlines_and_drops_rules(tmp_path: Path, ignore: InstallIgnore) -> None:
    """
    Given an OpenCode plan built from this fixture's synthetic template (which
    carries the ALL-RULES marker; no current real OpenCode template does) that
    still carries shared rules/ items (build_plan keeps them so the
    DYNAMIC-INCLUDE-ALL-RULES flatten can inline them)
    When flatten_plan_templates runs
    Then the rule is inlined into AGENTS.md and every rules/ item is dropped, while
    non-rules items (skills/, templates) survive.

    Pins: when a tool's instruction file carries the ALL-RULES marker, its
    rules live only inline in AGENTS.md instead of a standalone rules/
    namespace. The loose-rules drop is owned by flatten_plan_templates (keyed
    on the marker a template carries), NOT a per-adapter transform, so the
    inliner still sees the rules but sync does not. OpenCode's real rules/
    destination isn't special-cased away by this mechanism — it's simply
    unpopulated today because no current template carries the marker (see
    OpenCodeAdapter.post_staging_transforms).
    """
    repo = _make_opencode_repo(tmp_path)
    plan = build_plan(OpenCodeAdapter(), repo_root=repo, ignore=ignore)
    assert Path("rules/delegation.md") in plan.items  # precondition: staged for inlining

    flatten_plan_templates(plan, repo_root=repo, io=ScriptedIO())

    assert b"shared rule" in plan.items[Path("AGENTS.md")].content  # inlined
    assert not any(item.namespace == "rules" for item in plan.items.values())
    assert Path("rules/delegation.md") not in plan.items
    assert Path("skills/shared-skill") in plan.items
