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

from installer.core.clis import MIN_UV_VERSION, cli_source_digest
from installer.core.consent import require_consent
from installer.core.model import Counters, InstallOutcome, Outcome, Tool
from installer.core.prune_flow import run_prune
from installer.core.prune_hash import is_safe_to_prune, partition_file_orphans
from installer.core.receipt import CliReceiptEntry, Receipt, ReceiptEntry
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
    from collections.abc import Iterable, Mapping

    from installer.core.clis import CliDeployPort, CliSpec
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
    # Materialize once: the body iterates ``adapters`` several times, so a
    # one-shot iterator/generator would be exhausted after the first pass and
    # silently disable pruning / produce empty dest_roots.
    adapters = tuple(adapters)
    # Materialize: the body iterates ``plugins`` several times (live roots,
    # desired route keys, the missing-source guard); a one-shot iterator would be
    # exhausted after the first pass and silently disable the later guards.
    plugins = tuple(plugins)
    str_plans = {adapter.name: plans[Tool(adapter.name)] for adapter in adapters}
    dest_roots = {adapter.name: adapter.dest_dir(home) for adapter in adapters}

    owners = scope_owners(set(str_plans), discovered_plugin_names, prior)

    live_roots_by_owner: dict[str, set[Path]] = {
        adapter.name: {adapter.dest_dir(home).relative_to(home)} for adapter in adapters
    }
    for plugin in plugins:
        # MERGE, never overwrite: a plugin whose name collides with an active tool
        # (the repo ships both a `codex` tool and a `codex` plugin) must not clobber
        # the tool's live root. A generic plugin contributes no routes, so a bare
        # assignment would replace the tool's `.codex` root with an empty set, and the
        # codex tool's own entries would then fail validation — skipped, never pruned
        # even when the codex tool IS targeted. The union is correct: owner X
        # legitimately owns its tool root and any of its plugin route roots.
        live_roots_by_owner.setdefault(plugin.name, set()).update(
            Path(route.dest_dir.relative_to(home).parts[0]) for route in plugin.routes(home)
        )
    allowlist = set(prior.roots)

    keys = desired_staged_keys(
        str_plans, dest_roots=dest_roots, home=home, scope_owners=owners
    ) | desired_route_keys(plugins, home=home)
    # Fail closed on active-plugin route-source skew: a missing route source dir is a
    # packaging/checkout anomaly, not a retirement, so preserve that plugin's prior
    # entries instead of letting the empty desired set orphan (and delete) them.
    keys |= _protect_missing_route_sources(plugins, prior=prior, home=home, io=io)
    orphans = diff_orphans(
        prior,
        desired_keys=keys,
        scope_owners=owners,
        home=home,
        live_roots_by_owner=live_roots_by_owner,
        allowlist=allowlist,
    )
    recorded_sha_by_path = {e.path: e.sha256 for e in prior.entries}
    recorded_digest_by_path = {e.path: e.dir_digest for e in prior.entries}
    to_prune, relinquished = partition_file_orphans(
        orphans,
        home=home,
        recorded_sha_by_path=recorded_sha_by_path,
        recorded_digest_by_path=recorded_digest_by_path,
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
        # Re-check ownership at the destructive boundary (closes the TOCTOU window
        # between this partition and the actual delete — see prune_hash.is_safe_to_prune).
        revalidate=lambda o: is_safe_to_prune(
            o,
            home=home,
            recorded_sha_by_path=recorded_sha_by_path,
            recorded_digest_by_path=recorded_digest_by_path,
        ),
    )
    pruned_paths = {p.relative_to(home) for p in removed}
    return PruneOutcome(
        counters=counters, pruned_paths=pruned_paths, relinquished_paths=relinquished
    )


def _protect_missing_route_sources(
    plugins: tuple[PluginAdapter, ...], *, prior: Receipt, home: Path, io: IOPort
) -> set[tuple[str, Path]]:
    """Desired keys to preserve when an ACTIVE plugin's route source dir is missing.

    ``desired_route_keys`` skips a route whose ``source_dir`` is absent, contributing
    no desired keys for it. Without this guard, an active (discovered) plugin with a
    missing route source would have its previously-installed files seen as retired and
    pruned — turning packaging/checkout skew into deletion authority instead of failing
    closed. A genuinely *retired* plugin is not in ``plugins`` at all (it is pruned via
    prior-receipt scope), so this guard fires only for active plugins. For each
    missing-source route that has prior entries, re-add those entries' keys as desired
    (preserve them) and warn; the user restores the source or removes the plugin to
    retire those files."""
    prior_by_owner: dict[str, list[ReceiptEntry]] = {}
    for entry in prior.entries:
        prior_by_owner.setdefault(entry.owner, []).append(entry)
    protected: set[tuple[str, Path]] = set()
    for plugin in plugins:
        for route in plugin.routes(home):
            if route.source_dir.is_dir():
                continue
            dest_rel = route.dest_dir.relative_to(home)
            kept = [e for e in prior_by_owner.get(plugin.name, ()) if e.path.parent == dest_rel]
            if not kept:
                continue
            io.warn(
                f"plugin '{plugin.name}' route source is missing ({route.source_dir}); "
                f"preserving {len(kept)} previously-installed file(s) under {dest_rel} "
                "instead of pruning — restore the source or remove the plugin to retire them"
            )
            protected.update((plugin.name, e.path) for e in kept)
    return protected


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
    cli_entries: tuple[CliReceiptEntry, ...] | None = None,
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
        clis=cli_entries,
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
    Outcomes are collected only on a real (non-dry-run) install: the channel
    feeds ``record_receipt``, whose contract is "what happened on disk", and a
    dry run writes nothing. Each tool key is still populated — with an empty list
    on a dry run — so callers see every adapter's key, never a phantom WRITTEN.
    """
    collect = outcomes_by_tool is not None and not dry_run
    result: dict[str, Counters] = {}
    for adapter in adapters:
        tool_outcomes: list[InstallOutcome] | None = [] if collect else None
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
        if outcomes_by_tool is not None:
            outcomes_by_tool[adapter.name] = tool_outcomes if tool_outcomes is not None else []
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
    caller can record routed-file entries from real install results. Outcomes are
    collected only on a real (non-dry-run) install: the channel feeds
    ``record_receipt``, whose contract is "what happened on disk", and a dry run
    writes nothing. Each plugin key is still populated — with an empty list on a
    dry run — so callers see every plugin's key, never a phantom WRITTEN.
    """
    collect = outcomes_by_plugin is not None and not dry_run
    result: dict[str, Counters] = {}
    for plugin in plugins:
        plugin_outcomes: list[InstallOutcome] | None = [] if collect else None
        result[plugin.name] = sync_routes(
            plugin.routes(home),
            io=io,
            dry_run=dry_run,
            auto_yes=auto_yes,
            timestamp=timestamp,
            outcomes=plugin_outcomes,
        )
        if outcomes_by_plugin is not None:
            outcomes_by_plugin[plugin.name] = plugin_outcomes if plugin_outcomes is not None else []
    return result


@dataclass(frozen=True, slots=True)
class CliDeployOutcome:
    """What the CLI deploy half did. ``deployed`` holds only this run's
    smoked-OK installs (keyed by registry name) — the merge rule retains
    prior entries for everything else. ``any_failed`` drives _run's exit
    code (spec §6 failure surfacing)."""

    deployed: dict[str, CliReceiptEntry]
    counters: dict[str, Counters]
    any_failed: bool


def deploy_clis(
    specs: tuple[CliSpec, ...],
    *,
    repo_root: Path,
    prior: Receipt,
    deploy: CliDeployPort,
    io: IOPort,
    dry_run: bool = False,
    auto_yes: bool = False,
) -> CliDeployOutcome:
    """The CLI deploy half (spec §6): registry order, PATH-independent
    decision signals, consent on any unproven overwrite, reachability
    invariant per bin dir."""
    deployed: dict[str, CliReceiptEntry] = {}
    counters: dict[str, Counters] = {}
    any_failed = False

    version = deploy.uv_version()
    if version is None or version < MIN_UV_VERSION:
        need = ".".join(str(p) for p in MIN_UV_VERSION)
        got = ".".join(str(p) for p in version) if version else "unknown"
        io.err(
            f"CLI deploys need uv >= {need} (found {got}); "
            f"upgrade uv (e.g. `brew upgrade uv`) and re-run"
        )
        return CliDeployOutcome(deployed={}, counters={}, any_failed=True)

    prior_by_name = {c.name: c for c in prior.clis}
    tools = deploy.tool_list()
    reach_ok_dirs: set[Path] = set()  # memoized update-shell success per bin dir

    for spec in specs:
        target = f"cli:{spec.name}"
        counters[target] = Counters()
        package_dir = repo_root / spec.package_dir
        failed, shim_present = _deploy_one(
            spec,
            package_dir=package_dir,
            prior_entry=prior_by_name.get(spec.name),
            tools=tools,
            deploy=deploy,
            io=io,
            dry_run=dry_run,
            auto_yes=auto_yes,
            deployed=deployed,
            c=counters[target],
        )
        any_failed = any_failed or failed
        # Reachability gate reuses the decision/install outcome — it never
        # re-reads shim_path, keeping the fake's queue budget deterministic
        # (1 decision read + 1 re-read per successful install).
        if not dry_run and shim_present:
            ok = _check_reachability(
                spec.binary,
                deploy=deploy,
                io=io,
                auto_yes=auto_yes,
                resolved_dirs=reach_ok_dirs,
            )
            any_failed = any_failed or not ok
    return CliDeployOutcome(deployed=deployed, counters=counters, any_failed=any_failed)


def _deploy_one(
    spec: CliSpec,
    *,
    package_dir: Path,
    prior_entry: CliReceiptEntry | None,
    tools: Mapping[str, frozenset[str]] | None,
    deploy: CliDeployPort,
    io: IOPort,
    dry_run: bool,
    auto_yes: bool,
    deployed: dict[str, CliReceiptEntry],
    c: Counters,
) -> tuple[bool, bool]:
    """Run the §6 decision table for one CLI.

    Returns (failed, shim_present_at_end); the caller's reachability gate
    keys off the second element instead of re-reading shim_path."""
    digest = cli_source_digest(package_dir)
    shim = deploy.shim_path(spec.binary)
    env_present = tools is not None and spec.name in tools
    # Provenance: the registered env currently provides the registered
    # binary. Unproven (tools is None) is never provenance (spec §6).
    provenance = tools is not None and spec.binary in tools.get(spec.name, frozenset())
    evidence = shim is not None or env_present or tools is None

    def _done(failed: bool, installed: bool) -> tuple[bool, bool]:
        return failed, (shim is not None) or installed

    if prior_entry is not None:
        if provenance or (tools is not None and not env_present and shim is None):
            # Owned per receipt AND (live provenance, or nothing there at
            # all — a user uninstall). Promptless paths.
            if shim is not None and prior_entry.digest == digest:
                if dry_run:
                    io.info(f"cli:{spec.name}: would skip (up to date)")
                    c.skipped += 1
                    return _done(False, False)
                smoke = deploy.smoke(shim, spec.smoke_args)
                if smoke.ok:
                    c.skipped += 1
                    return _done(False, False)
                io.warn(f"cli:{spec.name}: installed copy fails smoke; healing\n{smoke.output}")
                return _done(
                    *_install(
                        spec,
                        package_dir,
                        digest,
                        force=True,
                        deploy=deploy,
                        io=io,
                        deployed=deployed,
                        c=c,
                        counter_attr="created",
                    )
                )
            if shim is None:
                # Heal. force only when our env is provably still there.
                if dry_run:
                    io.info(f"cli:{spec.name}: would reinstall (shim missing)")
                    return _done(False, False)
                return _done(
                    *_install(
                        spec,
                        package_dir,
                        digest,
                        force=provenance,
                        deploy=deploy,
                        io=io,
                        deployed=deployed,
                        c=c,
                        counter_attr="created",
                    )
                )
            # shim present, digest differs -> upgrade (consent).
            return _done(
                *_consented_install(
                    spec,
                    package_dir,
                    digest,
                    prompt=f"Upgrade CLI '{spec.binary}' ({spec.name})?",
                    deploy=deploy,
                    io=io,
                    dry_run=dry_run,
                    auto_yes=auto_yes,
                    deployed=deployed,
                    c=c,
                    counter_attr="updated",
                    would="would upgrade",
                )
            )
        # Receipt present but provenance mismatch (foreign env/shim) ->
        # takeover consent (spec §6 provenance precondition / item 19).
        return _done(
            *_consented_install(
                spec,
                package_dir,
                digest,
                prompt=f"Take over existing '{spec.binary}' (not provably {spec.name}'s)?",
                deploy=deploy,
                io=io,
                dry_run=dry_run,
                auto_yes=auto_yes,
                deployed=deployed,
                c=c,
                counter_attr="updated",
                would="would take over",
            )
        )

    if not evidence:
        # Fresh: non-forcing; an already-exists failure re-routes to
        # takeover consent (spec §6 fresh row / item 18).
        if dry_run:
            io.info(f"cli:{spec.name}: would install")
            return _done(False, False)
        result = deploy.tool_install(package_dir, force=False)
        if result.ok:
            return _done(
                *_finish_install(
                    spec,
                    digest,
                    deploy=deploy,
                    io=io,
                    deployed=deployed,
                    c=c,
                    counter_attr="created",
                )
            )
        io.warn(f"cli:{spec.name}: install found existing state; asking to take over")
        return _done(
            *_consented_install(
                spec,
                package_dir,
                digest,
                prompt=f"Take over existing '{spec.binary}'?",
                deploy=deploy,
                io=io,
                dry_run=dry_run,
                auto_yes=auto_yes,
                deployed=deployed,
                c=c,
                counter_attr="updated",
                would="would take over",
            )
        )
    return _done(
        *_consented_install(
            spec,
            package_dir,
            digest,
            prompt=f"Take over existing '{spec.binary}' (manual install detected)?",
            deploy=deploy,
            io=io,
            dry_run=dry_run,
            auto_yes=auto_yes,
            deployed=deployed,
            c=c,
            counter_attr="updated",
            would="would take over",
        )
    )


def _consented_install(
    spec: CliSpec,
    package_dir: Path,
    digest: str,
    *,
    prompt: str,
    deploy: CliDeployPort,
    io: IOPort,
    dry_run: bool,
    auto_yes: bool,
    deployed: dict[str, CliReceiptEntry],
    c: Counters,
    counter_attr: str,
    would: str,
) -> tuple[bool, bool]:
    if dry_run:
        io.info(f"cli:{spec.name}: {would}")
        return False, False
    require_consent(io, dry_run=dry_run, auto_yes=auto_yes)
    if not auto_yes and not io.confirm(prompt, default=False):
        c.skipped += 1
        return False, False
    return _install(
        spec,
        package_dir,
        digest,
        force=True,
        deploy=deploy,
        io=io,
        deployed=deployed,
        c=c,
        counter_attr=counter_attr,
    )


def _install(
    spec: CliSpec,
    package_dir: Path,
    digest: str,
    *,
    force: bool,
    deploy: CliDeployPort,
    io: IOPort,
    deployed: dict[str, CliReceiptEntry],
    c: Counters,
    counter_attr: str,
) -> tuple[bool, bool]:
    result = deploy.tool_install(package_dir, force=force)
    if not result.ok:
        io.err(f"cli:{spec.name}: install failed\n{result.output}")
        return True, False
    return _finish_install(
        spec, digest, deploy=deploy, io=io, deployed=deployed, c=c, counter_attr=counter_attr
    )


def _finish_install(
    spec: CliSpec,
    digest: str,
    *,
    deploy: CliDeployPort,
    io: IOPort,
    deployed: dict[str, CliReceiptEntry],
    c: Counters,
    counter_attr: str,
) -> tuple[bool, bool]:
    shim = deploy.shim_path(spec.binary)
    if shim is None:
        io.err(f"cli:{spec.name}: install reported ok but produced no shim")
        return True, False
    smoke = deploy.smoke(shim, spec.smoke_args)
    if not smoke.ok:
        io.err(f"cli:{spec.name}: smoke failed\n{smoke.output}")
        # The shim exists on disk, but the deploy FAILED — installed=False
        # keeps the reachability gate off this CLI; the failure is already
        # the run's signal.
        return True, False
    deployed[spec.name] = CliReceiptEntry(name=spec.name, binary=spec.binary, digest=digest)
    setattr(c, counter_attr, getattr(c, counter_attr) + 1)
    io.ok(f"cli:{spec.name}: deployed '{spec.binary}'")
    return False, True


def _check_reachability(
    binary: str,
    *,
    deploy: CliDeployPort,
    io: IOPort,
    auto_yes: bool,
    resolved_dirs: set[Path],
) -> bool:
    return True  # completed in Task 9 (reachability invariant)
