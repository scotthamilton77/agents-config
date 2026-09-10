"""The user's own always-on file, ``AGENTS.local.md``, is reachable from every
tool's deployed instruction file and is never staged by the installer.

Each tool's top-level template refers to a sibling ``AGENTS.local.md`` in the
tool's config directory: Claude and Gemini through their native ``@`` import,
Codex and OpenCode through a prose instruction, since neither has an import
mechanism. The installer only ever writes what it stages, so the guarantee
that the user's file survives a deploy is exactly that no plan for any tool
contains an item by that name.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.installignore import InstallIgnore
from installer.core.io_port import ScriptedIO
from installer.core.staging import build_plan
from installer.core.templates import flatten_plan_templates
from installer.tools.base import ToolAdapter
from installer.tools.claude import ClaudeAdapter
from installer.tools.codex import CodexAdapter
from installer.tools.gemini import GeminiAdapter
from installer.tools.opencode import OpenCodeAdapter

_REPO_ROOT = Path(__file__).resolve().parents[4]

_LOCAL_NAME = "AGENTS.local.md"

# The deployed file that reaches the user's local file, per tool.
_REFERRER: dict[type[ToolAdapter], tuple[Path, str]] = {
    ClaudeAdapter: (Path("CLAUDE.md"), "@AGENTS.local.md"),
    GeminiAdapter: (Path("GEMINI.md"), "@./AGENTS.local.md"),
    CodexAdapter: (Path("AGENTS.md"), "~/.codex/AGENTS.local.md"),
    OpenCodeAdapter: (Path("AGENTS.md"), "~/.config/opencode/AGENTS.local.md"),
}


@pytest.mark.parametrize("adapter_cls", list(_REFERRER))
def test_deployed_instruction_file_reaches_the_users_local_file(
    adapter_cls: type[ToolAdapter], ignore: InstallIgnore
) -> None:
    """The real plan for each tool, flattened as at deploy, carries the reference."""
    plan = build_plan(adapter_cls(), repo_root=_REPO_ROOT, ignore=ignore)
    flatten_plan_templates(plan, repo_root=_REPO_ROOT, io=ScriptedIO())

    dest, reference = _REFERRER[adapter_cls]
    content = plan.items[dest].content
    assert content is not None
    assert reference in content.decode("utf-8")


@pytest.mark.parametrize("adapter_cls", list(_REFERRER))
def test_installer_never_stages_the_users_local_file(
    adapter_cls: type[ToolAdapter], ignore: InstallIgnore
) -> None:
    """No item in any tool's real plan is named ``AGENTS.local.md``, so the
    user's copy is never written, backed up, or pruned."""
    plan = build_plan(adapter_cls(), repo_root=_REPO_ROOT, ignore=ignore)
    flatten_plan_templates(plan, repo_root=_REPO_ROOT, io=ScriptedIO())

    assert not [p for p in plan.items if p.name == _LOCAL_NAME]
