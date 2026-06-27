"""Run-level composition for the install and prune pipelines (W1 / G.5).

``install_pipeline`` walks each active tool's ``StagingPlan`` to disk via
``sync_plan``; ``prune_pipeline`` diffs a prior install receipt against this
run's desired staged keys for orphans (``core/receipt_diff.py``), drives the
interactive prune flow over the result (``core/prune_flow.py``), and returns a
``PruneOutcome``. It is **pure prune**: the caller reads the prior receipt and
writes the new one via ``record_receipt``, so the receipt is updated on every
non-dry-run install — not only on prune runs.

These are kept separate from ``cli.py`` so the compositions are unit-testable
without argparse, and separate from ``orchestrator.stage_and_transform`` so the
staging-plan production (which needs ``repo_root`` + plugin resolution) stays in
the caller. ``cli.main`` (W3) stages once and feeds the shared plans to both:
``install_pipeline`` runs first (the install half of a plain install and of
``--prune``), then ``prune_pipeline`` runs the prune half against the same
plans. ``--prune-only`` skips the install half. ``record_receipt`` then mirrors
disk into the receipt from the real per-item install outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from installer.core.model import Counters, InstallOutcome, Outcome, Tool
from installer.core.prune_flow import run_prune
from installer.core.prune_hash import partition_file_orphans
from installer.core.receipt import Receipt, ReceiptEntry
from installer.core.receipt_build import (
    desired_route_keys,
    desired_staged_keys,
    entries_from_outcomes,
    entries_from_route_outcomes,
    merge_receipt,
)
from installer.core.receipt_diff import diff_orphans, scope_owners
from installer.core.receipt_store import write_receipt
from installer.core.sync import sync_plan, sync_routes

if TYPE_CHECKING:
    from collections.abc import Iterable

    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan
    from installer.plugins.base import PluginAdapter
    from installer.tools.base import ToolAdapter


@dataclass(frozen=True, slots=True)
class PruneOutcome:
    """What a prune pass did: per-target counters + the home-relative path sets the
    caller needs to rewrite the receipt (mirrors-disk)."""

    counters: dict[str, Counters]
    pruned_paths: set[Path]
    relinquished_paths: set[Path]


def prune_pipeline(
    adapters: Iterable[ToolAdapter],
    *,
    plugins: Iterable[PluginAdapter] = (),
    plans: dict[Tool, StagingPlan],
    prior: Receipt,
    home: Path,
    discovered_plugin_names: set[str],
    io: IOPort,
    dry_run: bool = False,
    auto_yes: bool = False,
    prune_only: bool = False,
    timestamp: str | None = None,
) -> PruneOutcome:
    """Diff ``prior`` against this run's desired staged keys and prune the orphans.

    Pure prune: the caller reads ``prior`` and writes the receipt (via
    ``record_receipt``) so the receipt is updated on every install, not only on
    prune runs. Scope is the resolved tools plus the full discovered plugin set
    plus any retired plugin owners recorded in ``prior``. Orphans are validated
    (structural + symlink-aware containment + root legitimacy) and partitioned by
    on-disk hash before deletion: a file whose bytes drifted from the recorded
    sha256 is relinquished (kept), never deleted. Returns the per-target counters
    and the home-relative pruned / relinquished path sets."""
    str_plans = {adapter.name: plans[Tool(adapter.name)] for adapter in adapters}
    dest_roots = {adapter.name: adapter.dest_dir(home) for adapter in adapters}

    owners = scope_owners(set(str_plans), discovered_plugin_names, prior)

    live_roots_by_owner: dict[str, set[Path]] = {
        adapter.name: {adapter.dest_dir(home).relative_to(home)} for adapter in adapters
    }
    for plugin in plugins:
        live_roots_by_owner[plugin.name] = {
            Path(route.dest_dir.relative_to(home).parts[0]) for route in plugin.routes(home)
        }
    allowlist = set(prior.roots)

    keys = desired_staged_keys(
        str_plans, dest_roots=dest_roots, home=home, scope_owners=owners
    ) | desired_route_keys(plugins, home=home)
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
    pruned_paths = {p.relative_to(home) for p in removed}
    return PruneOutcome(
        counters=counters, pruned_paths=pruned_paths, relinquished_paths=relinquished
    )


def record_receipt(
    receipt_path: Path,
    *,
    prior: Receipt,
    dest_roots: dict[str, Path],
    home: Path,
    tool_outcomes: dict[str, list[InstallOutcome]],
    plugin_outcomes: dict[str, list[InstallOutcome]],
    pruned_paths: set[Path],
    relinquished_paths: set[Path],
) -> None:
    """Write the receipt to mirror disk after an install+prune pass.

    ``installed`` is built from the real per-item outcomes (DECLINED excluded,
    real sha256). A declined overwrite of a previously-recorded path relinquishes
    it (the user's bytes win). Roots accumulate (tool dest roots plus any plugin
    route roots actually written)."""
    installed: list[ReceiptEntry] = []
    for tool, outs in tool_outcomes.items():
        installed.extend(
            entries_from_outcomes(outs, tool=tool, dest_root=dest_roots[tool], home=home)
        )
    for plugin, outs in plugin_outcomes.items():
        installed.extend(entries_from_route_outcomes(outs, plugin=plugin, home=home))

    declined: set[Path] = {
        o.dest.relative_to(home)
        for outs in (*tool_outcomes.values(), *plugin_outcomes.values())
        for o in outs
        if o.outcome is Outcome.DECLINED
    }
    prior_paths = {e.path for e in prior.entries}
    all_relinquished = relinquished_paths | (declined & prior_paths)

    live_roots = {dest_roots[name].relative_to(home) for name in dest_roots} | {
        e.root for e in installed
    }
    new = merge_receipt(
        prior,
        installed=installed,
        pruned_paths=pruned_paths,
        relinquished_paths=all_relinquished,
        live_roots=live_roots,
    )
    write_receipt(receipt_path, new)


def install_pipeline(
    adapters: Iterable[ToolAdapter],
    *,
    plans: dict[Tool, StagingPlan],
    home: Path,
    io: IOPort,
    dry_run: bool = False,
    auto_yes: bool = False,
    timestamp: str | None = None,
    outcomes_by_tool: dict[str, list[InstallOutcome]] | None = None,
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

    The per-tool plan is indexed strictly (``plans[Tool(adapter.name)]``) — an
    adapter without a staged plan is an orchestrator bug (a loud `KeyError`),
    not a silent no-op.

    When ``outcomes_by_tool`` is provided, each tool's per-item ``InstallOutcome``
    list is captured into it (keyed by ``adapter.name``) so the caller can build
    the receipt from real install results (real sha256, DECLINED excluded).
    """
    result: dict[str, Counters] = {}
    for adapter in adapters:
        tool_outcomes: list[InstallOutcome] | None = [] if outcomes_by_tool is not None else None
        result[adapter.name] = sync_plan(
            adapter,
            plans[Tool(adapter.name)],
            home=home,
            io=io,
            dry_run=dry_run,
            auto_yes=auto_yes,
            timestamp=timestamp,
            outcomes=tool_outcomes,
        )
        if outcomes_by_tool is not None and tool_outcomes is not None:
            outcomes_by_tool[adapter.name] = tool_outcomes
    return result


def install_plugin_routes(
    plugins: Iterable[PluginAdapter],
    *,
    home: Path,
    io: IOPort,
    dry_run: bool = False,
    auto_yes: bool = False,
    timestamp: str | None = None,
    outcomes_by_plugin: dict[str, list[InstallOutcome]] | None = None,
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

    When ``outcomes_by_plugin`` is provided, each plugin's per-item
    ``InstallOutcome`` list is captured into it (keyed by ``plugin.name``) so the
    caller can record routed-file entries from real install results.
    """
    result: dict[str, Counters] = {}
    for plugin in plugins:
        plugin_outcomes: list[InstallOutcome] | None = (
            [] if outcomes_by_plugin is not None else None
        )
        result[plugin.name] = sync_routes(
            plugin.routes(home),
            io=io,
            dry_run=dry_run,
            auto_yes=auto_yes,
            timestamp=timestamp,
            outcomes=plugin_outcomes,
        )
        if outcomes_by_plugin is not None and plugin_outcomes is not None:
            outcomes_by_plugin[plugin.name] = plugin_outcomes
    return result
