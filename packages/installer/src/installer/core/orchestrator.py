"""Run-orchestration seam: stage every active tool (Phases 1-5), overlay active
plugins (Phase 6), flatten instruction templates (Phase 6.5/6.75), then apply its
post-staging transform pass.

This is the call site for ``ToolAdapter.post_staging_transforms`` across all four
adapters. ``cli.main`` (W3) routes every active tool through this function and
feeds the transformed plans to ``install_pipeline`` (and the prune scan) — NOT
``build_plan``->``sync`` directly — so adapter transforms (e.g. the Gemini
frontmatter transform) run in real installs, not only when materialising the
stage via ``--dump-stage``.

Phase ordering (epic Plugin Seam Integration Brief): plugin overlay (6) runs
AFTER base staging; plugin extensions (6.5, F.5 YAML patches) run AFTER the
overlay — so a patch can target plugin-contributed and carrier-merged files;
DYNAMIC-INCLUDE flatten (6.5/6.75) then inlines the include-only templates and
drops their standalone copies, so an ALL-RULES marker sees plugin-contributed
rules; and all of this runs BEFORE ``post_staging_transforms`` (the Gemini
frontmatter transform at 6.95), so a transform sees flattened content.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from installer.core.merge.registry import default_registry
from installer.core.overlay import overlay_plugins
from installer.core.staging import build_plan
from installer.core.templates import flatten_plan_templates
from installer.plugins.extensions import apply_extensions
from installer.tools.registry import get_adapter

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from installer.core.installignore import InstallIgnore
    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan, Tool
    from installer.plugins.base import PluginAdapter


def stage_and_transform(
    tools: Iterable[Tool],
    *,
    repo_root: Path,
    io: IOPort,
    ignore: InstallIgnore,
    plugins: Sequence[PluginAdapter] = (),
) -> dict[Tool, StagingPlan]:
    """Build a StagingPlan for each active tool (staging Phases 1-5), overlay the
    active ``plugins`` onto it (Phase 6, through the merge registry), apply plugin
    extension YAML patches (Phase 6.5), flatten its instruction templates and drop
    the include-only templates (Phase 6.5/6.75), and run that tool's adapter
    ``post_staging_transforms`` pass over the result. Returns the transformed plan
    per tool, preserving iteration order. With no plugins the overlay is a no-op,
    so existing tool-only callers are unaffected.
    """
    registry = default_registry()
    plans: dict[Tool, StagingPlan] = {}
    for tool in tools:
        adapter = get_adapter(tool)
        plan = build_plan(adapter, repo_root=repo_root, ignore=ignore)
        plan = overlay_plugins(plan, plugins, adapter=adapter, registry=registry, ignore=ignore)
        plan = apply_extensions(plan, plugins)
        flatten_plan_templates(plan, repo_root=repo_root, io=io)
        plans[tool] = adapter.post_staging_transforms(plan, io)
    return plans
