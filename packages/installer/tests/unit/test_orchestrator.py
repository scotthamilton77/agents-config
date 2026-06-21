"""The transform pass over every active adapter — first call site for
ToolAdapter.post_staging_transforms.

Pins: Gemini rewrites agent frontmatter; the identity adapters (Claude, Codex)
return their agent items unchanged through this call site; OpenCode contributes
no shared agents at all; and each tool is routed through its own adapter in a
single call.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from installer.core.installignore import InstallIgnore
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


def test_stage_and_transform_gemini_rewrites_agent_frontmatter(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    plans = stage_and_transform(
        [Tool.GEMINI], repo_root=_make_repo(tmp_path), io=ScriptedIO(), ignore=ignore
    )
    content = plans[Tool.GEMINI].items[_AGENT].content
    assert content is not None
    fm = _frontmatter(content)
    assert "color" not in fm
    assert fm["tools"] == ["Read", "Grep"]


def test_stage_and_transform_claude_leaves_agent_frontmatter_unchanged(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    io = ScriptedIO()
    plans = stage_and_transform([Tool.CLAUDE], repo_root=_make_repo(tmp_path), io=io, ignore=ignore)
    assert plans[Tool.CLAUDE].items[_AGENT].content == _CLAUDE_AGENT
    assert not any("frontmatter" in e.message.lower() for e in io.transcript)


def test_stage_and_transform_codex_leaves_agent_frontmatter_unchanged(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    plans = stage_and_transform(
        [Tool.CODEX], repo_root=_make_repo(tmp_path), io=ScriptedIO(), ignore=ignore
    )
    assert plans[Tool.CODEX].items[_AGENT].content == _CLAUDE_AGENT


def test_stage_and_transform_opencode_skips_shared_agents(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    plans = stage_and_transform(
        [Tool.OPENCODE], repo_root=_make_repo(tmp_path), io=ScriptedIO(), ignore=ignore
    )
    assert _AGENT not in plans[Tool.OPENCODE].items


def test_stage_and_transform_dispatches_correct_adapter_per_tool(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    plans = stage_and_transform(
        [Tool.GEMINI, Tool.CLAUDE], repo_root=_make_repo(tmp_path), io=ScriptedIO(), ignore=ignore
    )
    gemini_content = plans[Tool.GEMINI].items[_AGENT].content
    assert gemini_content is not None
    assert "color" not in _frontmatter(gemini_content)
    assert plans[Tool.CLAUDE].items[_AGENT].content == _CLAUDE_AGENT


@dataclass(frozen=True, slots=True)
class _Plugin:
    """Minimal active PluginAdapter for the overlay-wiring test."""

    name: str
    source_path: Path

    def is_detected(self, home: Path) -> bool:  # noqa: ARG002  # inert  # pragma: no cover
        return True


def test_stage_and_transform_overlays_active_plugins(tmp_path: Path, ignore: InstallIgnore) -> None:
    """Phase 6 wiring: an active plugin's content is overlaid onto the tool's
    plan between base staging and the post-staging transform."""
    repo = _make_repo(tmp_path)
    plugin_root = tmp_path / "plugins" / "test-plugin"
    (plugin_root / ".claude" / "rules").mkdir(parents=True)
    (plugin_root / ".claude" / "rules" / "plugin-rule.md").write_bytes(b"from plugin")

    plans = stage_and_transform(
        [Tool.CLAUDE],
        repo_root=repo,
        io=ScriptedIO(),
        ignore=ignore,
        plugins=[_Plugin(name="test-plugin", source_path=plugin_root)],
    )

    assert plans[Tool.CLAUDE].items[Path("rules/plugin-rule.md")].content == b"from plugin"


def test_stage_and_transform_overlay_runs_before_gemini_transform(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    """A plugin-contributed Gemini agent must still pass through the Gemini
    frontmatter transform — proving the overlay runs BEFORE post_staging_transforms
    (brief phase ladder: 6 overlay, then 6.95 Gemini transform)."""
    repo = _make_repo(tmp_path)
    plugin_root = tmp_path / "plugins" / "test-plugin"
    (plugin_root / ".agents" / "agents").mkdir(parents=True)
    (plugin_root / ".agents" / "agents" / "plug-agent.md").write_bytes(_CLAUDE_AGENT)

    plans = stage_and_transform(
        [Tool.GEMINI],
        repo_root=repo,
        io=ScriptedIO(),
        ignore=ignore,
        plugins=[_Plugin(name="test-plugin", source_path=plugin_root)],
    )

    content = plans[Tool.GEMINI].items[Path("agents/plug-agent.md")].content
    assert content is not None
    assert "color" not in _frontmatter(content)  # transform ran on plugin content
