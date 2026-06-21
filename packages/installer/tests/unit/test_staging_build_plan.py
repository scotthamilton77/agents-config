"""End-to-end staging plan build over a fixture repo, driving the real
ClaudeAdapter — this is where ClaudeAdapter.scoped_namespaces and
should_install_namespace earn behavioural coverage (pragmas removed).

Fixtures are no-collision by construction (distinct names across shared and
tool roots), per the C.1 contract; collision/merge dispatch is Epic E.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.installignore import InstallIgnore
from installer.core.merge.base import CollisionError
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
    # hooks namespace — scripts staged like other tool namespaces, +x preserved
    (claude / "hooks").mkdir(parents=True)
    hook = claude / "hooks" / "ruff-postedit.py"
    hook.write_bytes(b"#!/usr/bin/env python3\n")
    hook.chmod(0o755)
    return repo


def test_build_plan_includes_shared_and_tool_phases(tmp_path: Path, ignore: InstallIgnore) -> None:
    repo = _make_repo(tmp_path)

    plan = build_plan(ClaudeAdapter(), repo_root=repo, ignore=ignore)

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


def test_build_plan_filters_namespace_marker_file(tmp_path: Path, ignore: InstallIgnore) -> None:
    repo = _make_repo(tmp_path)
    plan = build_plan(ClaudeAdapter(), repo_root=repo, ignore=ignore)
    assert Path("skills/AGENTS.md") not in plan.items


def test_build_plan_stages_hooks_namespace_with_exec_bit(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    """The Claude installer stages src/user/.claude/hooks/ -> hooks/ and preserves
    the +x bit on hook scripts (8.7 parity with install.sh's hooks/ support)."""
    repo = _make_repo(tmp_path)
    plan = build_plan(ClaudeAdapter(), repo_root=repo, ignore=ignore)
    assert Path("hooks/ruff-postedit.py") in plan.items
    assert plan.items[Path("hooks/ruff-postedit.py")].executable is True


def test_build_plan_assigns_namespaces_and_kinds(tmp_path: Path, ignore: InstallIgnore) -> None:
    repo = _make_repo(tmp_path)
    plan = build_plan(ClaudeAdapter(), repo_root=repo, ignore=ignore)

    assert plan.items[Path("rules/delegation.md")].kind == FileKind.NAMESPACED_MD
    assert plan.items[Path("rules/delegation.md")].namespace == "rules"
    assert plan.items[Path("skills/shared-skill")].kind == FileKind.DIR
    assert plan.items[Path("settings.json")].kind == FileKind.SETTINGS_JSON


def test_build_plan_appends_colliding_rules(tmp_path: Path, ignore: InstallIgnore) -> None:
    """A shared rules/ file (Phase 2) and a tool rules/ file (Phase 4) at the
    same dest_relpath append-merge through the registry: (NAMESPACED_MD, "rules")
    -> AppendRulesStrategy joins existing (shared) THEN incoming (tool) with the
    canonical b"\\n---\\n" separator."""
    repo = _make_repo(tmp_path)
    # rules is in both _SHARED_NAMESPACES (Phase 2) and scoped_namespaces (Phase 4),
    # so both stage to rules/delegation.md -> identical dest_relpath.
    (repo / "src" / "user" / ".claude" / "rules").mkdir(parents=True)
    (repo / "src" / "user" / ".claude" / "rules" / "delegation.md").write_bytes(b"tool extension")

    plan = build_plan(ClaudeAdapter(), repo_root=repo, ignore=ignore)

    assert plan.items[Path("rules/delegation.md")].content == b"shared rule\n---\ntool extension"


def test_build_plan_dir_collision_is_fatal(tmp_path: Path, ignore: InstallIgnore) -> None:
    """A same-named skill DIR in shared (Phase 2) and tool (Phase 4) is an
    irreconcilable collision: the registry routes (FileKind.DIR) to
    FatalStrategy, which raises CollisionError. Proves the guard was relocated to
    the registry, not dissolved."""
    repo = _make_repo(tmp_path)
    # shared has skills/shared-skill/ (a DIR); stage the same DIR name tool-side.
    (repo / "src" / "user" / ".claude" / "skills" / "shared-skill").mkdir(parents=True)
    (repo / "src" / "user" / ".claude" / "skills" / "shared-skill" / "SKILL.md").write_bytes(b"x")

    with pytest.raises(CollisionError):
        build_plan(ClaudeAdapter(), repo_root=repo, ignore=ignore)


def test_build_plan_other_collision_last_wins(tmp_path: Path, ignore: InstallIgnore) -> None:
    """Two root templates mapping to the same dest (FileKind.OTHER) resolve via
    LastWinsSilentStrategy: the incoming tool template (Phase 3) silently wins
    over the shared one (Phase 1)."""
    repo = _make_repo(tmp_path)
    # shared INSTRUCTIONS.md.template (Phase 1) -> INSTRUCTIONS.md; add a tool-root
    # template at the same dest (Phase 3).
    tool_tmpl = repo / "src" / "user" / ".claude" / "INSTRUCTIONS.md.template"
    tool_tmpl.write_bytes(b"# tool root tmpl")

    plan = build_plan(ClaudeAdapter(), repo_root=repo, ignore=ignore)

    assert plan.items[Path("INSTRUCTIONS.md")].content == b"# tool root tmpl"
