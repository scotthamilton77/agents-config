"""Run-orchestration seam: stage every active tool, then apply its
post-staging transform pass.

This is the FIRST call site for ``ToolAdapter.post_staging_transforms`` across
all four adapters. It is deliberately NOT yet invoked from ``cli.main()``: the
plan-walking sync that would consume these transformed plans does not exist yet
(``core/sync.py`` is the single-file B.2 slice; plan-walking sync arrives with
the Epic E merge dispatch). When the full install pipeline is wired into
``main()``, it MUST route every active tool through this function — not
``build_plan``->``sync`` directly — or adapter transforms (e.g. the Gemini
frontmatter transform) will silently never run in real installs. That wiring is
tracked as its own story.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from installer.core.staging import build_plan
from installer.tools.registry import get_adapter

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan, Tool


def stage_and_transform(
    tools: Iterable[Tool], *, repo_root: Path, io: IOPort
) -> dict[Tool, StagingPlan]:
    """Build a StagingPlan for each active tool (staging Phases 1-5) and run
    that tool's adapter ``post_staging_transforms`` pass over it. Returns the
    transformed plan per tool, preserving iteration order.
    """
    plans: dict[Tool, StagingPlan] = {}
    for tool in tools:
        adapter = get_adapter(tool)
        plan = build_plan(adapter, repo_root=repo_root)
        plans[tool] = adapter.post_staging_transforms(plan, io)
    return plans
