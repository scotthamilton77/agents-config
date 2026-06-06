"""The transform pass over every active adapter — first call site for
ToolAdapter.post_staging_transforms.

Pins: Gemini rewrites agent frontmatter; the identity adapters (Claude, Codex)
return their agent items unchanged through this call site; OpenCode contributes
no shared agents at all; and each tool is routed through its own adapter in a
single call.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from installer.core.io_port import ScriptedIO
from installer.core.model import Tool
from installer.core.orchestrator import stage_and_transform

_AGENT = Path("agents/quality.md")
_CLAUDE_AGENT = b"---\nname: quality\ncolor: purple\ntools: Read, Grep\n---\nReview body.\n"


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shared = repo / "src" / "user" / ".agents"
    (shared / "agents").mkdir(parents=True)
    (shared / "agents" / "quality.md").write_bytes(_CLAUDE_AGENT)
    for tool in ("claude", "codex", "gemini", "opencode"):
        (repo / "src" / "user" / f".{tool}").mkdir(parents=True)
    return repo


def _frontmatter(content: bytes) -> dict[str, object]:
    parsed = yaml.safe_load(content.decode("utf-8").split("---\n", 2)[1])
    assert isinstance(parsed, dict)
    return parsed


def test_stage_and_transform_gemini_rewrites_agent_frontmatter(tmp_path: Path) -> None:
    plans = stage_and_transform([Tool.GEMINI], repo_root=_make_repo(tmp_path), io=ScriptedIO())
    content = plans[Tool.GEMINI].items[_AGENT].content
    assert content is not None
    fm = _frontmatter(content)
    assert "color" not in fm
    assert fm["tools"] == ["Read", "Grep"]


def test_stage_and_transform_claude_leaves_agent_frontmatter_unchanged(tmp_path: Path) -> None:
    io = ScriptedIO()
    plans = stage_and_transform([Tool.CLAUDE], repo_root=_make_repo(tmp_path), io=io)
    assert plans[Tool.CLAUDE].items[_AGENT].content == _CLAUDE_AGENT
    assert not any("frontmatter" in e.message.lower() for e in io.transcript)


def test_stage_and_transform_codex_leaves_agent_frontmatter_unchanged(tmp_path: Path) -> None:
    plans = stage_and_transform([Tool.CODEX], repo_root=_make_repo(tmp_path), io=ScriptedIO())
    assert plans[Tool.CODEX].items[_AGENT].content == _CLAUDE_AGENT


def test_stage_and_transform_opencode_skips_shared_agents(tmp_path: Path) -> None:
    plans = stage_and_transform([Tool.OPENCODE], repo_root=_make_repo(tmp_path), io=ScriptedIO())
    assert _AGENT not in plans[Tool.OPENCODE].items


def test_stage_and_transform_dispatches_correct_adapter_per_tool(tmp_path: Path) -> None:
    plans = stage_and_transform(
        [Tool.GEMINI, Tool.CLAUDE], repo_root=_make_repo(tmp_path), io=ScriptedIO()
    )
    gemini_content = plans[Tool.GEMINI].items[_AGENT].content
    assert gemini_content is not None
    assert "color" not in _frontmatter(gemini_content)
    assert plans[Tool.CLAUDE].items[_AGENT].content == _CLAUDE_AGENT
