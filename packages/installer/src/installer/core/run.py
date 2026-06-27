"""Run-level composition for the install and prune pipelines (W1 / G.5).

``install_pipeline`` walks each active tool's ``StagingPlan`` to disk via
``sync_plan``; ``prune_pipeline`` diffs the prior install receipt against this
run's desired staged keys for orphans (``core/receipt_diff.py``), drives the
interactive prune flow over the result (``core/prune_flow.py``), then rewrites
the receipt to mirror the staged plan.

Both are kept separate from ``cli.py`` so the compositions are unit-testable
without argparse, and separate from ``orchestrator.stage_and_transform`` so the
staging-plan production (which needs ``repo_root`` + plugin resolution) stays in
the caller. ``cli.main`` (W3) stages once and feeds the shared plans to both:
``install_pipeline`` runs first (the install half of a plain install and of
``--prune``), then ``prune_pipeline`` runs the prune half against the same
plans. ``--prune-only`` skips the install half.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from installer.core.model import Counters, Tool
from installer.core.prune_flow import run_prune
from installer.core.prune_hash import partition_file_orphans
from installer.core.receipt import Receipt
from installer.core.receipt_build import (
    desired_staged_keys,
    entries_from_plans,
    merge_receipt,
)
from installer.core.receipt_diff import diff_orphans, scope_owners
from installer.core.receipt_store import ReadStatus, read_receipt, write_receipt
from installer.core.sync import sync_plan, sync_routes

if TYPE_CHECKING:
    from collections.abc import Iterable

    from installer.core.installer_toml import InstallerToml
    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan
    from installer.plugins.base import PluginAdapter
    from installer.tools.base import ToolAdapter


def prune_pipeline(
    adapters: Iterable[ToolAdapter],
    *,
    plugins: Iterable[PluginAdapter] = (),
    plans: dict[Tool, StagingPlan],
    home: Path,
    config: InstallerToml,  # noqa: ARG001  # glob config retired during the receipt cutover
    receipt_path: Path,
    io: IOPort,
    dry_run: bool = False,
    auto_yes: bool = False,
    prune_only: bool = False,
    timestamp: str | None = None,
) -> dict[str, Counters]:
    """Diff the prior receipt against the desired staged plan, then prune orphans.

    Orphans are recorded receipt entries (owner in scope) absent from this run's
    desired staged keys. ``scope_owners`` is the resolved tools plus the active
    plugins. After pruning, the receipt is rewritten to mirror the staged plan
    (the mirrors-disk subtraction of pruned/relinquished entries lands in a later
    task; the tracer overwrites). A missing/corrupt prior receipt yields an empty
    baseline, so nothing is treated as an orphan (fail-closed clean break).
    """
    str_plans = {adapter.name: plans[Tool(adapter.name)] for adapter in adapters}
    dest_roots = {adapter.name: adapter.dest_dir(home) for adapter in adapters}

    prior_read = read_receipt(receipt_path)
    prior = (
        prior_read.receipt
        if prior_read.status is ReadStatus.OK and prior_read.receipt is not None
        else Receipt()
    )

    owners = scope_owners(set(str_plans), {plugin.name for plugin in plugins}, prior)

    live_roots_by_owner: dict[str, set[Path]] = {
        adapter.name: {adapter.dest_dir(home).relative_to(home)} for adapter in adapters
    }
    for plugin in plugins:
        live_roots_by_owner[plugin.name] = {
            Path(route.dest_dir.relative_to(home).parts[0]) for route in plugin.routes(home)
        }
    allowlist = set(prior.roots)

    keys = desired_staged_keys(str_plans, dest_roots=dest_roots, home=home, scope_owners=owners)
    orphans = diff_orphans(
        prior,
        desired_keys=keys,
        scope_owners=owners,
        home=home,
        live_roots_by_owner=live_roots_by_owner,
        allowlist=allowlist,
    )
    recorded_sha_by_path = {e.path: e.sha256 for e in prior.entries}
    to_prune, relinquished = partition_file_orphans(
        orphans, home=home, recorded_sha_by_path=recorded_sha_by_path
    )

    removed: set[Path] = set()
    counters = run_prune(
        to_prune,
        io=io,
        dry_run=dry_run,
        auto_yes=auto_yes,
        prune_only=prune_only,
        timestamp=timestamp,
        removed=removed,
    )
    if not dry_run:
        pruned_paths = {p.relative_to(home) for p in removed}
        installed = entries_from_plans(str_plans, dest_roots=dest_roots, home=home)
        live_roots = {dest_roots[name].relative_to(home) for name in dest_roots}
        new = merge_receipt(
            prior,
            installed=installed,
            pruned_paths=pruned_paths,
            relinquished_paths=relinquished,
            live_roots=live_roots,
        )
        write_receipt(receipt_path, new)
    return counters


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
