"""End-to-end staging plan build over a fixture repo, driving the real
CodexAdapter — this is where CodexAdapter.scoped_namespaces and
should_install_namespace earn behavioural coverage.

Pins the key Codex divergence from ClaudeAdapter: Codex contributes zero
tool-scoped namespace items (scoped_namespaces() == ()) while still accepting
all shared namespaces (should_install_namespace → True for "shared").
"""

from __future__ import annotations

from pathlib import Path

from installer.core.installignore import InstallIgnore
from installer.core.model import StagingPlan, Tool
from installer.core.staging import build_plan
from installer.tools.codex import CodexAdapter


def _make_codex_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shared = repo / "src" / "user" / ".agents"
    codex = repo / "src" / "user" / ".codex"
    # shared namespaces
    (shared / "rules").mkdir(parents=True)
    (shared / "rules" / "delegation.md").write_bytes(b"shared rule")
    (shared / "skills").mkdir(parents=True)
    (shared / "skills" / "shared-skill").mkdir()
    (shared / "agents").mkdir(parents=True)
    (shared / "agents" / "shared-agent.md").write_bytes(b"agent")
    (shared / "INSTRUCTIONS.md.template").write_bytes(b"# shared root tmpl")
    # codex tool root — templates only, no namespace subdirs
    codex.mkdir(parents=True)
    (codex / "AGENTS.md.template").write_bytes(b"# codex root tmpl")
    return repo


def test_codex_build_plan_stages_shared_namespaces(tmp_path: Path, ignore: InstallIgnore) -> None:
    """
    Given a repo with shared rules/skills/agents content
    When build_plan runs with CodexAdapter
    Then shared namespace items appear in the plan.

    Pins: should_install_namespace returns True for shared source, so
    Phase 2 includes rules, skills, and agents.
    """
    repo = _make_codex_repo(tmp_path)

    plan = build_plan(CodexAdapter(), repo_root=repo, ignore=ignore)

    assert isinstance(plan, StagingPlan)
    assert plan.tool == Tool.CODEX
    dests = set(plan.items)
    assert Path("rules/delegation.md") in dests
    assert Path("skills/shared-skill") in dests
    assert Path("agents/shared-agent.md") in dests
    assert Path("AGENTS.md") in dests  # tool template (Phase 3), suffix stripped


def test_codex_build_plan_stages_no_tool_namespaces(tmp_path: Path, ignore: InstallIgnore) -> None:
    """
    Given CodexAdapter.scoped_namespaces() returns ()
    When build_plan runs
    Then no Phase-4 tool-namespace items appear in the plan.

    Pins: empty scoped_namespaces means Codex adds no tool-scoped namespace
    directories — the correct divergence from ClaudeAdapter (which adds commands/).
    """
    repo = _make_codex_repo(tmp_path)

    plan = build_plan(CodexAdapter(), repo_root=repo, ignore=ignore)

    assert not any(i.namespace == "commands" for i in plan.items.values())
