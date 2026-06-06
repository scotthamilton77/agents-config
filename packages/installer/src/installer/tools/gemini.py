from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan

_CLAUDE_ONLY_KEYS = ("skills", "color", "memory")


def transform_agent_frontmatter(content: bytes) -> bytes:
    """Translate a shared (Claude-style) agent file's YAML frontmatter into the
    form Gemini's agent loader accepts: drop Claude-only keys (skills, color,
    memory) and convert a comma-separated ``tools:`` string into a YAML
    sequence. Port of bash ``transform_gemini_agent_frontmatter``
    (scripts/install.sh:639-684), via a pyyaml round-trip.

    Returns ``content`` unchanged when it has no leading ``---``…``---`` block,
    when that block is unterminated, when it does not parse to a mapping, or
    when there is nothing to strip or convert (so an already-clean file is
    never gratuitously reformatted). The body after the closing fence is
    preserved byte-for-byte.
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content

    lines = text.split("\n")
    if lines[0] != "---":
        return content
    closing = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    if closing is None:
        return content

    try:
        data = yaml.safe_load("\n".join(lines[1:closing]))
    except yaml.YAMLError:
        return content
    if not isinstance(data, dict):
        return content

    changed = False
    for key in _CLAUDE_ONLY_KEYS:
        if key in data:
            del data[key]
            changed = True
    tools = data.get("tools")
    if isinstance(tools, str):
        items = [t.strip() for t in tools.split(",") if t.strip()]
        if items:
            data["tools"] = items
            changed = True
    if not changed:
        return content

    dumped = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    body = "\n".join(lines[closing + 1 :])
    return ("---\n" + dumped + "---\n" + body).encode("utf-8")


class GeminiAdapter:
    """Adapter for Google's Gemini CLI. Probes ~/.gemini/ as a directory —
    mirrors the bash installer's [[ -d "$HOME/.gemini" ]] detection."""

    name: str = "gemini"
    detection_signal: str = ".gemini"

    def source_dir(self, repo_root: Path) -> Path:
        return repo_root / "src" / "user" / ".gemini"

    def dest_dir(self, home: Path) -> Path:
        return home / ".gemini"

    def is_detected(self, home: Path) -> bool:
        return (home / ".gemini").is_dir()

    def scoped_namespaces(self) -> tuple[str, ...]:
        return ()

    def should_install_namespace(
        self,
        namespace: str,  # noqa: ARG002  # protocol parameter; GeminiAdapter accepts uniformly
        source: str,  # noqa: ARG002  # protocol parameter; GeminiAdapter accepts uniformly
    ) -> bool:
        return True

    def post_staging_transforms(self, plan: StagingPlan, io: IOPort) -> StagingPlan:
        """Apply the Claude→Gemini agent frontmatter transform to every staged
        ``agents/`` file. Mirrors bash Phase 6.6 (scripts/install.sh:892-897):
        emits one verbose phase line when agent files are present, then rewrites
        each in place. Non-agent items and directory entries are left untouched.
        """
        logged = False
        for relpath, item in list(plan.items.items()):
            if item.namespace != "agents" or item.content is None:
                continue
            if not logged:
                io.info("Transforming agent frontmatter for Gemini", verbose=True)
                logged = True
            new_content = transform_agent_frontmatter(item.content)
            if new_content != item.content:
                plan.items[relpath] = replace(item, content=new_content)
        return plan
