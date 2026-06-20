"""build_plan Phase 2 marks shared skills/agents DIR items as carrier dirs.

The ``shared_carrier`` flag is the in-memory replacement for the bash
``.carrier-from-user-shared`` sentinel file (scripts/install.sh:517-529): it
records that a skills/agents directory was first staged from the shared carrier
tree, so the Phase 6 plugin overlay can distinguish an allowed carrier-merge
from a forbidden plugin-plugin directory collision. These tests pin *where*
Phase 2 sets the flag — only skills/ and agents/ DIR items — not the field's
default literal (that is the type system's job).
"""

from __future__ import annotations

from pathlib import Path

from installer.core.installignore import InstallIgnore
from installer.core.model import FileKind
from installer.core.staging import build_plan
from installer.tools.claude import ClaudeAdapter


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shared = repo / "src" / "user" / ".agents"
    (shared / "skills" / "shared-skill").mkdir(parents=True)
    (shared / "agents").mkdir(parents=True)
    (shared / "agents" / "shared-agent-dir").mkdir()
    (shared / "agents" / "shared-agent.md").write_bytes(b"agent file")
    (shared / "rules").mkdir(parents=True)
    (shared / "rules" / "delegation.md").write_bytes(b"shared rule")
    (shared / "INSTRUCTIONS.md.template").write_bytes(b"# tmpl")
    (repo / "src" / "user" / ".claude").mkdir(parents=True)
    return repo


def test_shared_skill_dir_is_marked_carrier(tmp_path: Path, ignore: InstallIgnore) -> None:
    """A shared skills/ DIR item carries shared_carrier=True so the overlay
    can carrier-merge a plugin's disjoint additions into it."""
    plan = build_plan(ClaudeAdapter(), repo_root=_make_repo(tmp_path), ignore=ignore)
    item = plan.items[Path("skills/shared-skill")]
    assert item.kind is FileKind.DIR
    assert item.shared_carrier is True


def test_shared_agent_dir_is_marked_carrier(tmp_path: Path, ignore: InstallIgnore) -> None:
    """The carrier mark covers agents/ DIR items too, not just skills/."""
    plan = build_plan(ClaudeAdapter(), repo_root=_make_repo(tmp_path), ignore=ignore)
    assert plan.items[Path("agents/shared-agent-dir")].shared_carrier is True


def test_shared_non_dir_namespace_item_is_not_carrier(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    """A shared rules/*.md file is not a DIR, so it must NOT be marked —
    carrier-merge applies only to skill/agent directory units."""
    plan = build_plan(ClaudeAdapter(), repo_root=_make_repo(tmp_path), ignore=ignore)
    assert plan.items[Path("rules/delegation.md")].shared_carrier is False


def test_shared_agent_md_file_is_not_carrier(tmp_path: Path, ignore: InstallIgnore) -> None:
    """An agents/*.md file (kind OTHER-of-namespace, not DIR) is not a carrier
    even though it lives under agents/ — the mark keys on kind==DIR."""
    plan = build_plan(ClaudeAdapter(), repo_root=_make_repo(tmp_path), ignore=ignore)
    assert plan.items[Path("agents/shared-agent.md")].shared_carrier is False


def test_shared_template_is_not_carrier(tmp_path: Path, ignore: InstallIgnore) -> None:
    """A Phase 1 root template is neither skills/ nor agents/, so unmarked."""
    plan = build_plan(ClaudeAdapter(), repo_root=_make_repo(tmp_path), ignore=ignore)
    assert plan.items[Path("INSTRUCTIONS.md")].shared_carrier is False
