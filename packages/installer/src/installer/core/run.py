"""Run-level composition for the install and prune pipelines (W1 / G.5).

``install_pipeline`` walks each active tool's ``StagingPlan`` to disk via
``sync_plan``; ``prune_pipeline`` scans each tool's destination tree against its
in-memory ``StagingPlan`` for orphans (``core/prune.py``), then drives the
interactive prune flow over the result (``core/prune_flow.py``).

Both are kept separate from ``cli.py`` so the compositions are unit-testable
without argparse, and separate from ``orchestrator.stage_and_transform`` so the
staging-plan production (which needs ``repo_root`` + plugin resolution) stays in
the caller. ``cli.main`` (W3) stages once and feeds the shared plans to both:
``install_pipeline`` runs first (the install half of a plain install and of
``--prune``), then ``prune_pipeline`` runs the prune half against the same
plans. ``--prune-only`` skips the install half.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from installer.core.model import Counters, Tool
from installer.core.prune import scan_orphans
from installer.core.prune_flow import run_prune
from installer.core.sync import sync_plan, sync_routes

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from installer.core.installer_toml import InstallerToml
    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan
    from installer.plugins.base import PluginAdapter
    from installer.tools.base import ToolAdapter


def prune_pipeline(
    adapters: Iterable[ToolAdapter],
    *,
    plans: dict[Tool, StagingPlan],
    home: Path,
    config: InstallerToml,
    io: IOPort,
    dry_run: bool = False,
    auto_yes: bool = False,
    prune_only: bool = False,
    timestamp: str | None = None,
) -> dict[str, Counters]:
    """Scan ``adapters`` for orphans against ``plans``, then run the prune flow.

    ``prune_only`` is threaded to the flow so its non-interactive guard
    distinguishes a hard-fail (prune-only without consent) from a warn+skip
    (plain ``--prune``). Returns the flow's per-target ``Counters`` (pruned /
    backed_up) keyed by ``Orphan.tool`` — each tool or plugin namespace whose
    orphans were pruned gets its own bucket so the install summary can report a
    plugin pruned outside the active tool set (bash AC#19). An empty / no-op
    prune yields an empty mapping.
    """
    orphans = scan_orphans(adapters, plans=plans, home=home, config=config)
    return run_prune(
        orphans,
        io=io,
        dry_run=dry_run,
        auto_yes=auto_yes,
        prune_only=prune_only,
        timestamp=timestamp,
    )


def install_pipeline(
    adapters: Iterable[ToolAdapter],
    *,
    plans: dict[Tool, StagingPlan],
    home: Path,
    io: IOPort,
    dry_run: bool = False,
    auto_yes: bool = False,
    timestamp: str | None = None,
) -> dict[str, Counters]:
    """Walk each adapter's ``StagingPlan`` to disk via ``sync_plan``, per tool.

    The install-side analog of ``prune_pipeline``: ``cli.main`` (W3) calls this
    ahead of the prune step to perform the real install. Each adapter's plan is
    looked up by its tool (``Tool(adapter.name)``) and written under
    ``adapter.dest_dir(home)``. Returns a per-tool mapping keyed by
    ``adapter.name`` (each tool's own `Counters`) rather than one aggregate, so
    the install summary can render a separate block per tool. A summed total
    would throw the per-tool distinction away.

    ``dry_run`` and ``auto_yes`` are forwarded verbatim into every ``sync_plan``
    call, so the W2 consent gate and the shared no-TTY guard apply uniformly
    across tools (``auto_yes`` auto-accepts changed-item overwrites; ``dry_run``
    previews without prompting).

    Unlike ``scan_orphans``'s tolerant ``.get``, the per-tool plan is indexed
    strictly — an adapter without a staged plan is an orchestrator bug (a loud
    `KeyError`), not a silent no-op.
    """
    return {
        adapter.name: sync_plan(
            adapter,
            plans[Tool(adapter.name)],
            home=home,
            io=io,
            dry_run=dry_run,
            auto_yes=auto_yes,
            timestamp=timestamp,
        )
        for adapter in adapters
    }


def install_plugin_routes(
    plugins: Iterable[PluginAdapter],
    *,
    home: Path,
    io: IOPort,
    dry_run: bool = False,
    auto_yes: bool = False,
    timestamp: str | None = None,
) -> dict[str, Counters]:
    """Install every active plugin's bespoke routes (e.g. beads' ``~/.beads/...``).

    The plugin-side analog of ``install_pipeline``: it walks each plugin's
    ``routes(home)`` through ``sync_routes`` and returns a per-plugin mapping
    keyed by ``plugin.name`` (each plugin's own `Counters`). Per-plugin rather
    than one aggregate so the install summary renders a block per plugin. A
    routes-free generic plugin still gets an all-zero bucket — present so a
    verbose summary can print its (empty) block — so a tool-only plugin set is a
    no-op on disk, not on the mapping. ``cli.main`` (W3) calls this after
    ``install_pipeline`` (gated by ``not --prune-only``).

    ``dry_run`` and ``auto_yes`` thread into ``sync_routes`` so the consent gate
    and no-TTY guard apply uniformly with the tool install.
    """
    return {
        plugin.name: sync_routes(
            plugin.routes(home),
            io=io,
            dry_run=dry_run,
            auto_yes=auto_yes,
            timestamp=timestamp,
        )
        for plugin in plugins
    }
