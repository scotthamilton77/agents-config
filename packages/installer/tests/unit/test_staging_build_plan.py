"""End-to-end staging plan build over a fixture repo, driving the real
ClaudeAdapter — this is where ClaudeAdapter.scoped_namespaces and
should_install_namespace earn behavioural coverage (pragmas removed).

Fixtures are no-collision by construction (distinct names across shared and
tool roots), per the C.1 contract; collision/merge dispatch is Epic E.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.model import FileKind, StagingPlan, Tool
from installer.core.staging import build_plan
from installer.tools.claude import ClaudeAdapter


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shared = repo / "src" / "user" / ".agents"
    claude = repo / "src" / "user" / ".claude"
    # shared
    (shared / "rules").mkdir(parents=True)
    (shared / "rules" / "delegation.md").write_bytes(b"shared rule")
    (shared / "skills").mkdir(parents=True)
    (shared / "skills" / "shared-skill").mkdir()
    (shared / "skills" / "AGENTS.md").write_bytes(b"dead dev doc")  # must be filtered
    (shared / "agents").mkdir(parents=True)
    (shared / "agents" / "shared-agent.md").write_bytes(b"agent")
    # shared root template uses a DISTINCT name from the tool root so Phase 1
    # and Phase 3 do not collide on dest_relpath (mirrors the real repo).
    (shared / "INSTRUCTIONS.md.template").write_bytes(b"# shared root tmpl")
    # tool-specific
    (claude / "commands").mkdir(parents=True)
    (claude / "commands" / "go.md").write_bytes(b"go")
    (claude / "AGENTS.md.template").write_bytes(b"# claude root tmpl")
    (claude / "AGENTS.md").write_bytes(b"in-repo dev doc")  # must NOT stage
    (claude / "settings.json.template").write_bytes(b"{}")
    return repo


def test_build_plan_collects_all_phases(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    plan = build_plan(ClaudeAdapter(), repo_root=repo)

    assert isinstance(plan, StagingPlan)
    assert plan.tool == Tool.CLAUDE
    dests = set(plan.items)
    assert Path("rules/delegation.md") in dests  # shared namespace
    assert Path("skills/shared-skill") in dests  # shared dir
    assert Path("agents/shared-agent.md") in dests  # shared agents
    assert Path("commands/go.md") in dests  # tool namespace
    assert Path("INSTRUCTIONS.md") in dests  # shared template (Phase 1)
    assert Path("AGENTS.md") in dests  # tool template (Phase 3), stripped
    assert Path("settings.json") in dests  # tool settings


def test_build_plan_filters_namespace_marker_file(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    plan = build_plan(ClaudeAdapter(), repo_root=repo)
    assert Path("skills/AGENTS.md") not in plan.items


def test_build_plan_assigns_namespaces_and_kinds(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    plan = build_plan(ClaudeAdapter(), repo_root=repo)

    assert plan.items[Path("rules/delegation.md")].kind == FileKind.NAMESPACED_MD
    assert plan.items[Path("rules/delegation.md")].namespace == "rules"
    assert plan.items[Path("skills/shared-skill")].kind == FileKind.DIR
    assert plan.items[Path("settings.json")].kind == FileKind.SETTINGS_JSON


def test_build_plan_raises_on_collision(tmp_path: Path) -> None:
    """Two sources mapping to the same dest_relpath must raise — merge
    dispatch is deferred to Epic E, so a silent overwrite is unacceptable."""
    repo = _make_repo(tmp_path)
    # Force a collision: a tool-side rules/ file with the SAME name as the shared
    # rules/ file already in the fixture. rules is in both _SHARED_NAMESPACES
    # (Phase 2) and ClaudeAdapter.scoped_namespaces() (Phase 4), so both stage to
    # rules/delegation.md -> identical dest_relpath.
    (repo / "src" / "user" / ".claude" / "rules").mkdir(parents=True)
    (repo / "src" / "user" / ".claude" / "rules" / "delegation.md").write_bytes(b"dup")

    with pytest.raises(ValueError, match="collision"):
        build_plan(ClaudeAdapter(), repo_root=repo)
