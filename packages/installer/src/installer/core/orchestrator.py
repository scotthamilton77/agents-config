"""Run-orchestration seam: stage every active tool (Phases 1-5), overlay active
plugins (Phase 6), then apply its post-staging transform pass.

This is the call site for ``ToolAdapter.post_staging_transforms`` across all four
adapters. ``cli.main`` (W3) routes every active tool through this function and
feeds the transformed plans to ``install_pipeline`` (and the prune scan) — NOT
``build_plan``->``sync`` directly — so adapter transforms (e.g. the Gemini
frontmatter transform) run in real installs, not only when materialising the
stage via ``--dump-stage``.

Phase ordering (epic Plugin Seam Integration Brief): plugin overlay (6) runs
AFTER base staging; plugin extensions (6.5, F.5 YAML patches) run AFTER the
overlay — so a patch can target plugin-contributed and carrier-merged files —
and BEFORE ``post_staging_transforms`` (the Gemini frontmatter transform at
6.95), so a transform sees extension-patched content, and a plugin-contributed
Gemini agent is normalised by the same transform as a base agent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from installer.core.merge.registry import default_registry
from installer.core.overlay import overlay_plugins
from installer.core.staging import build_plan
from installer.plugins.extensions import apply_extensions
from installer.tools.registry import get_adapter

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan, Tool
    from installer.plugins.base import PluginAdapter


def stage_and_transform(
    tools: Iterable[Tool],
    *,
    repo_root: Path,
    io: IOPort,
    plugins: Sequence[PluginAdapter] = (),
) -> dict[Tool, StagingPlan]:
    """Build a StagingPlan for each active tool (staging Phases 1-5), overlay the
    active ``plugins`` onto it (Phase 6, through the merge registry), apply plugin
    extension YAML patches (Phase 6.5), and run
    that tool's adapter ``post_staging_transforms`` pass over the result. Returns
    the transformed plan per tool, preserving iteration order. With no plugins
    the overlay is a no-op, so existing tool-only callers are unaffected.
    """
    registry = default_registry()
    plans: dict[Tool, StagingPlan] = {}
    for tool in tools:
        adapter = get_adapter(tool)
        plan = build_plan(adapter, repo_root=repo_root)
        plan = overlay_plugins(plan, plugins, adapter=adapter, registry=registry)
        plan = apply_extensions(plan, plugins)
        plans[tool] = adapter.post_staging_transforms(plan, io)
    return plans
