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
) -> Counters:
    """Scan ``adapters`` for orphans against ``plans``, then run the prune flow.

    ``prune_only`` is threaded to the flow so its non-interactive guard
    distinguishes a hard-fail (prune-only without consent) from a warn+skip
    (plain ``--prune``). Returns the flow's ``Counters`` (pruned / backed_up).
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
) -> Counters:
    """Walk each adapter's ``StagingPlan`` to disk via ``sync_plan``; sum the totals.

    The install-side analog of ``prune_pipeline``: ``cli.main`` (W3) calls this
    ahead of the prune step to perform the real install. Each adapter's plan is
    looked up by its tool (``Tool(adapter.name)``) and written under
    ``adapter.dest_dir(home)``. Returns the aggregate `Counters`
    (created / updated / skipped / backed_up summed across tools).

    ``dry_run`` and ``auto_yes`` are forwarded verbatim into every ``sync_plan``
    call, so the W2 consent gate and the shared no-TTY guard apply uniformly
    across tools (``auto_yes`` auto-accepts changed-item overwrites; ``dry_run``
    previews without prompting).

    Unlike ``scan_orphans``'s tolerant ``.get``, the per-tool plan is indexed
    strictly — an adapter without a staged plan is an orchestrator bug (a loud
    `KeyError`), not a silent no-op.
    """
    total = Counters()
    for adapter in adapters:
        result = sync_plan(
            adapter,
            plans[Tool(adapter.name)],
            home=home,
            io=io,
            dry_run=dry_run,
            auto_yes=auto_yes,
            timestamp=timestamp,
        )
        total.created += result.created
        total.updated += result.updated
        total.skipped += result.skipped
        total.backed_up += result.backed_up
    return total


def install_plugin_routes(
    plugins: Iterable[PluginAdapter],
    *,
    home: Path,
    io: IOPort,
    dry_run: bool = False,
    auto_yes: bool = False,
    timestamp: str | None = None,
) -> Counters:
    """Install every active plugin's bespoke routes (e.g. beads' ``~/.beads/...``).

    The plugin-side analog of ``install_pipeline``: it flattens each plugin's
    ``routes(home)`` and walks them through ``sync_routes``. Generic plugins
    return no routes, so a routes-free or tool-only plugin set is a clean no-op.
    ``cli.main`` (W3) calls this after ``install_pipeline`` (gated by
    ``not --prune-only``), mirroring the bash installer, which runs
    ``stage_and_install_beads`` after the tool sync (``scripts/install.sh:948``).

    ``dry_run`` and ``auto_yes`` thread into ``sync_routes`` so the consent gate
    and no-TTY guard apply uniformly with the tool install. Returns the aggregate
    `Counters` from the route walk.
    """
    routes = [route for plugin in plugins for route in plugin.routes(home)]
    return sync_routes(routes, io=io, dry_run=dry_run, auto_yes=auto_yes, timestamp=timestamp)
