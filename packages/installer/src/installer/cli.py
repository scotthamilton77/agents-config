from __future__ import annotations

import argparse
import os
import sys
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

from installer.config import Config, resolve_plugins, resolve_plugins_root, resolve_tools
from installer.core.consent import ConsentRequiredError
from installer.core.dump import dump_plan
from installer.core.installignore import load_installignore
from installer.core.model import Counters, InstallOutcome
from installer.core.orchestrator import stage_and_transform
from installer.core.prune_flow import PruneAbortedError
from installer.core.receipt import Receipt
from installer.core.receipt_lock import ReceiptLockBusy, receipt_lock
from installer.core.receipt_store import ReadStatus, read_receipt
from installer.core.run import (
    install_pipeline,
    install_plugin_routes,
    prune_pipeline,
    record_receipt,
)
from installer.core.summary import render_summary
from installer.plugins.registry import discover
from installer.tools.registry import UnknownToolError, get_adapter, known_tools

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from installer.core.io_port import IOPort
    from installer.plugins.base import PluginAdapter

# The repo root is the agents-config checkout containing ``src/user/.agents`` and
# ``src/plugins``. ``cli.py`` lives at ``<repo>/packages/installer/src/installer/
# cli.py``, so the fourth parent is the repo root. ``uv`` installs this package
# editable, so ``__file__`` stays inside the source tree and this resolution holds
# at runtime; tests inject ``repo_root`` directly. The bundled installer.toml path
# and the plugin source root are derived per-run from the injected repo_root
# (default: _REPO_ROOT), keeping repo_root fully authoritative for staging,
# config, and plugin discovery alike.
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="installer",
        description="Install agent configurations for AI coding assistants.",
    )
    parser.add_argument(
        "--tools",
        metavar="CSV",
        default=None,
        help=(
            "Comma-separated tool list to install "
            f"(valid: {', '.join(t.value for t in known_tools())}). "
            "Default: auto-detect against $HOME."
        ),
    )
    parser.add_argument(
        "--plugins",
        metavar="CSV",
        default=None,
        help=(
            "Comma-separated plugin list to install (discovered under "
            "src/plugins). Default: auto-detect against $HOME. "
            "Pass --plugins= (empty) to install no plugins."
        ),
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Auto-accept all prompts (the scripted-install path).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show per-file progress (installed / up-to-date / updated).",
    )
    # --dump-stage, --prune, and --prune-only are three mutually exclusive
    # terminal modes (dump the staging plan / install-then-prune / prune-only),
    # so any combination is rejected by argparse.
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--prune",
        action="store_true",
        help="After install, remove orphaned paths from the prior install (with backup).",
    )
    mode_group.add_argument(
        "--prune-only",
        action="store_true",
        help="Skip install; scan + remove orphaned paths from the prior install.",
    )
    mode_group.add_argument(
        "--dump-stage",
        metavar="PATH",
        default=None,
        type=Path,
        help=(
            "Materialise the in-memory staging plan to PATH as a real directory "
            "tree (PATH/<tool>/...), print the path, and exit. Writes no install "
            "destination. For debugging template flattening, plugin overlay, and "
            "collision resolution."
        ),
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    home: Path | None = None,
    io: IOPort | None = None,
    repo_root: Path | None = None,
) -> int:
    """CLI entry point. Runs the installer, catching Ctrl-C at the boundary so an
    interactive abort (e.g. at an overwrite prompt) exits cleanly with code 130 and
    a short ``Aborted.`` notice instead of dumping a ``KeyboardInterrupt`` traceback.
    Every other exit — argparse's ``SystemExit``, the guarded config-error returns —
    passes through unchanged."""
    try:
        return _run(argv, home=home, io=io, repo_root=repo_root)
    except KeyboardInterrupt:
        sys.stderr.write("\nAborted.\n")
        return 130


def _run(
    argv: list[str] | None = None,
    *,
    home: Path | None = None,
    io: IOPort | None = None,
    repo_root: Path | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    resolved_home = home if home is not None else Path.home()
    resolved_repo_root = repo_root if repo_root is not None else _REPO_ROOT

    if io is None:
        from installer.core.io_port import TerminalIO

        io = TerminalIO(verbose=args.verbose)

    # Run-mode notice: a dry-run announces itself up front; an auto-yes run notes
    # that prompts and diffs are suppressed — but only when NOT verbose, since
    # verbose already narrates every file. Emitted before tool/plugin resolution
    # so it leads the transcript.
    if args.dry_run:
        io.info("DRY RUN -- no changes will be made")
    elif args.yes and not args.verbose:
        io.info("Auto-yes mode -- prompts and diffs suppressed")

    try:
        tools = resolve_tools(home=resolved_home, override_csv=args.tools)
    except (UnknownToolError, ValueError) as exc:
        sys.stderr.write(f"installer: {exc}\n")
        return 2

    # Resolve plugins up front (after tools) so an invalid --plugins fails fast
    # on every path. The resolved set feeds both --dump-stage and --prune below.
    try:
        plugins = resolve_plugins(
            home=resolved_home,
            plugins_root=resolve_plugins_root(resolved_repo_root, os.environ),
            override_csv=args.plugins,
        )
    except ValueError as exc:
        # UnknownPluginError (unknown name) and the stray-comma ValueError both
        # subclass ValueError; surface cleanly with exit 2, mirroring resolve_tools.
        sys.stderr.write(f"installer: {exc}\n")
        return 2

    # Warn about plugins an EXPLICIT --plugins= override dropped (auto-detect
    # dropping an undetected plugin is normal, not warn-worthy). Routed through
    # io.warn after resolution and before any mode dispatch so it fires on every
    # path (plain / --dump-stage / --prune / --prune-only) the override reaches.
    if args.plugins is not None:
        _warn_excluded_plugins(
            resolved=plugins,
            repo_root=resolved_repo_root,
            io=io,
            prune_active=args.prune or args.prune_only,
        )

    # Load the shared exclusion manifest up front. An absent, unreadable, or
    # non-UTF-8 .installignore is a hard error (exit 2) rather than a silent
    # empty-exclusion install — the manifest is load-bearing policy, and a missing
    # one would re-leak dead-docs silently. UnicodeDecodeError is a ValueError
    # (not an OSError), so it is caught explicitly here.
    try:
        ignore = load_installignore(resolved_repo_root / ".installignore")
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(f"installer: {exc}\n")
        return 2

    if args.dump_stage is not None:
        plans = stage_and_transform(
            tools, repo_root=resolved_repo_root, io=io, ignore=ignore, plugins=plugins
        )
        try:
            dump_plan(plans, args.dump_stage, io=io)
        except ValueError as exc:
            # A non-empty target or an escaping plan path fails the dump cleanly
            # (exit 2) rather than as an uncaught traceback, matching the CLI's
            # other guarded error paths.
            sys.stderr.write(f"installer: {exc}\n")
            return 2
        return 0

    config = Config(home=resolved_home, tools=tools, auto_yes=args.yes)

    # Stage once, up front: the same StagingPlan set feeds both the install and
    # the prune orphan-scan, so --prune is install-then-prune over ONE plan, not
    # two independent stagings. Staging is deterministic, writes nothing to disk,
    # and does not read installer.toml, so producing the plan before the
    # prune-only toml-load below changes neither the prune outcome nor its error
    # handling — only a verbose adapter transform notice (e.g. Gemini) may now
    # precede a toml error, which is immaterial.
    adapters = [get_adapter(tool) for tool in tools]
    plans = stage_and_transform(
        tools, repo_root=resolved_repo_root, io=io, ignore=ignore, plugins=plugins
    )

    # Default install path (also the install half of --prune): walk each active
    # tool's StagingPlan to disk via install_pipeline. Skipped only for
    # --prune-only, which removes retired paths without installing. Slots ahead of
    # the prune branch so --prune is install-then-prune. Driving the install
    # through stage_and_transform is also what makes adapter post-staging
    # transforms (e.g. the Gemini frontmatter transform) fire in real installs,
    # not just --dump-stage / --prune.
    # Per-target tallies accumulate across the install and prune halves so the
    # summary reports each tool/plugin's full activity merged (a tool that both
    # installs files and has orphans pruned shows both). Keyed by target name.
    counters: dict[str, Counters] = {}
    receipt_path = resolved_home / ".config" / "agents-config" / "install-receipt.json"
    dest_roots = {adapter.name: adapter.dest_dir(resolved_home) for adapter in adapters}
    discovered_plugin_names = set(discover(resolve_plugins_root(resolved_repo_root, os.environ)))
    tool_outcomes: dict[str, list[InstallOutcome]] = {}
    plugin_outcomes: dict[str, list[InstallOutcome]] = {}
    pruned_paths: set[Path] = set()
    relinquished_paths: set[Path] = set()

    # Single-writer advisory lock over the whole mutation section (receipt-read ->
    # install -> prune -> receipt-write). A concurrent second installer fails fast
    # rather than interleaving writes; reading `prior` inside the lock closes the
    # read-then-write window, so the new receipt mirrors the disk state this run
    # actually saw. Early returns out of the `with` release the lock via the
    # context manager. The read-only summary below stays outside the lock.
    #
    # --dry-run skips the lock entirely: it writes nothing and records nothing, so it
    # needs no mutation serialization — and acquiring the lock would itself CREATE
    # ~/.config/agents-config/ + the .lock file (violating "--dry-run writes nothing")
    # and would fail on a readable-but-not-writable HOME. Reading the prior receipt
    # unlocked is safe for a preview: read_receipt never mutates.
    lock_cm: AbstractContextManager[None] = (
        nullcontext() if args.dry_run else receipt_lock(receipt_path.with_suffix(".lock"))
    )
    try:
        with lock_cm:
            prior_read = read_receipt(receipt_path)
            receipt_corrupt = prior_read.status is ReadStatus.CORRUPT
            if receipt_corrupt:
                io.err(
                    f"install receipt at {receipt_path} is unreadable; skipping prune "
                    "and leaving it untouched — reset or migrate it to re-enable pruning"
                )
            prior = (
                prior_read.receipt
                if prior_read.status is ReadStatus.OK and prior_read.receipt is not None
                else Receipt()
            )
            if not args.prune_only:
                try:
                    _merge_into(
                        counters,
                        install_pipeline(
                            adapters,
                            plans=plans,
                            home=resolved_home,
                            io=io,
                            dry_run=args.dry_run,
                            auto_yes=config.auto_yes,
                            outcomes_by_tool=tool_outcomes,
                        ),
                    )
                    # Plugin routes (e.g. beads' ~/.beads/formulas + scripts) land
                    # outside any tool tree, so they install in a dedicated pass after
                    # the tool sync. Same consent gate; --prune-only skips it.
                    _merge_into(
                        counters,
                        install_plugin_routes(
                            plugins,
                            home=resolved_home,
                            io=io,
                            dry_run=args.dry_run,
                            auto_yes=config.auto_yes,
                            outcomes_by_plugin=plugin_outcomes,
                        ),
                    )
                except ConsentRequiredError:
                    # A non-interactive run lacking --yes/--dry-run cannot answer the
                    # per-file overwrite prompt; sync_plan's up-front guard raises
                    # before any write. Surface it as the CLI's exit 1 (the prune flow
                    # uses the same convention) rather than an uncaught traceback.
                    return 1

            if (args.prune or args.prune_only) and not receipt_corrupt:
                try:
                    outcome = prune_pipeline(
                        adapters,
                        plugins=plugins,
                        plans=plans,
                        prior=prior,
                        home=resolved_home,
                        discovered_plugin_names=discovered_plugin_names,
                        io=io,
                        dry_run=args.dry_run,
                        auto_yes=config.auto_yes,
                        prune_only=args.prune_only,
                    )
                except PruneAbortedError:
                    return 1
                _merge_into(counters, outcome.counters)
                pruned_paths = outcome.pruned_paths
                relinquished_paths = outcome.relinquished_paths

            # Write the receipt on every non-dry-run install (not only --prune):
            # built from the real per-item outcomes so it mirrors disk. Inside the
            # lock so a concurrent installer cannot interleave its own write. A
            # CORRUPT prior is left untouched (fail closed) so a scoped run never
            # erases another owner's recorded entries.
            if not args.dry_run and not receipt_corrupt:
                record_receipt(
                    receipt_path,
                    prior=prior,
                    dest_roots=dest_roots,
                    home=resolved_home,
                    tool_outcomes=tool_outcomes,
                    plugin_outcomes=plugin_outcomes,
                    pruned_paths=pruned_paths,
                    relinquished_paths=relinquished_paths,
                )
    except ReceiptLockBusy:
        io.err("another install is in progress; re-run when it finishes")
        return 1

    # Render the install / prune summary once at the end. ALL_TOOLS is the closed
    # tool universe (known_tools); ALL_PLUGINS is the discovered plugin set — both
    # feed the '(not detected, skipped)' verbose footers.
    render_summary(
        counters,
        tools=[t.value for t in tools],
        plugins=[p.name for p in plugins],
        all_tools=[t.value for t in known_tools()],
        all_plugins=list(discover(resolve_plugins_root(resolved_repo_root, os.environ))),
        verbose=args.verbose,
        io=io,
    )
    return 0


def _merge_into(target: dict[str, Counters], source: Mapping[str, Counters]) -> None:
    """Field-wise accumulate ``source`` into ``target`` per target name.

    A name may appear in more than one pipeline (e.g. a tool that installs files
    AND has orphans pruned), so each field is summed into the existing bucket
    rather than overwriting it — the merged tally is what the summary reports.
    """
    for name, c in source.items():
        bucket = target.setdefault(name, Counters())
        bucket.created += c.created
        bucket.updated += c.updated
        bucket.merged += c.merged
        bucket.skipped += c.skipped
        bucket.pruned += c.pruned
        bucket.backed_up += c.backed_up


def _warn_excluded_plugins(
    *,
    resolved: Iterable[PluginAdapter],
    repo_root: Path,
    io: IOPort,
    prune_active: bool,
) -> None:
    """Warn about each discovered plugin an explicit ``--plugins=`` override dropped.

    For every plugin in the discovered set absent from the resolved selection, emit
    a warning naming it. The wording branches on whether a prune phase is active —
    under ``--prune``/``--prune-only`` the excluded plugin's already-installed files
    become orphans that may be removed (strict mode); otherwise they are left in
    place. Caller gates this on an explicit override, so an auto-detected exclusion
    stays silent.
    """
    resolved_names = {adapter.name for adapter in resolved}
    discovered = discover(resolve_plugins_root(repo_root, os.environ))
    for name in discovered:
        if name in resolved_names:
            continue
        if prune_active:
            io.warn(
                f"Plugin '{name}' excluded via --plugins= — under --prune, "
                "previously-installed files become orphans and may be removed."
            )
        else:
            io.warn(
                f"Plugin '{name}' excluded via --plugins= — files already installed "
                "are not removed (use --prune or --prune-only to remove orphans "
                "under strict mode)."
            )
