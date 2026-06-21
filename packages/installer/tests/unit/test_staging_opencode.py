"""End-to-end staging plan build over a fixture repo, driving the real
OpenCodeAdapter — this is where OpenCodeAdapter.should_install_namespace
earns behavioural coverage.

Pins the key OpenCode divergence from Claude/Codex: the shared agents/
namespace is NOT staged (frontmatter format differs; see
OPENCODE-EXTENSIONS.md), while shared skills/ and rules/ ARE staged
(rules remain available for DYNAMIC-INCLUDE-ALL-RULES inlining).
"""

from __future__ import annotations

from pathlib import Path

from installer.core.installignore import InstallIgnore
from installer.core.io_port import ScriptedIO
from installer.core.model import StagingPlan, Tool
from installer.core.staging import build_plan
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
    (opencode / "AGENTS.md.template").write_bytes(b"# opencode root tmpl")
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


def test_opencode_post_staging_transforms_drops_rules(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    """
    Given an OpenCode plan that still carries shared rules/ items (build_plan keeps
    them so the DYNAMIC-INCLUDE-ALL-RULES flatten can inline them)
    When OpenCodeAdapter.post_staging_transforms runs
    Then every rules/ item is dropped, while non-rules items (skills/, templates)
    survive.

    Pins: OpenCode writes no standalone rules/ namespace — rules live only inline in
    AGENTS.md. The drop runs post-flatten (mirrors install.sh Phase 7, which stages
    rules then skips writing the rules/ subdir for opencode), so the inliner still
    sees the rules but sync does not.
    """
    repo = _make_opencode_repo(tmp_path)
    plan = build_plan(OpenCodeAdapter(), repo_root=repo, ignore=ignore)
    assert Path("rules/delegation.md") in plan.items  # precondition: staged for inlining

    result = OpenCodeAdapter().post_staging_transforms(plan, ScriptedIO())

    assert not any(item.namespace == "rules" for item in result.items.values())
    assert Path("rules/delegation.md") not in result.items
    assert Path("skills/shared-skill") in result.items
