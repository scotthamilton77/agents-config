from __future__ import annotations

import argparse
import os
import sys
import tomllib
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

from installer.config import (
    Config,
    read_project_profiles,
    resolve_plugins,
    resolve_plugins_root,
    resolve_tools,
    write_project_profiles,
)
from installer.core.consent import ConsentRequiredError
from installer.core.dump import dump_plan
from installer.core.installignore import load_installignore
from installer.core.kits import kit_adapters, kit_name_of, kit_routes, kit_universe, stage_kits
from installer.core.merge.base import CollisionError
from installer.core.merge.registry import UnknownMergeKeyError
from installer.core.model import Counters, InstallOutcome
from installer.core.orchestrator import stage_and_transform
from installer.core.profiles import (
    Scope,
    _selector_matches,
    filter_plan_to_scope,
    load_manifest,
    project_universe,
    resolve,
)
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
    from installer.core.model import StagingPlan, Tool
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
        "--project",
        metavar="PATH",
        default=None,
        type=Path,
        help="Install project-scoped content into PATH instead of user space.",
    )
    parser.add_argument(
        "--profiles",
        metavar="CSV",
        default=None,
        help="Comma-separated profile names (requires --project in this version).",
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
    cwd: Path | None = None,
) -> int:
    """CLI entry point. Runs the installer, catching Ctrl-C at the boundary so an
    interactive abort (e.g. at an overwrite prompt) exits cleanly with code 130 and
    a short ``Aborted.`` notice instead of dumping a ``KeyboardInterrupt`` traceback.
    Every other exit — argparse's ``SystemExit``, the guarded config-error returns —
    passes through unchanged."""
    try:
        return _run(argv, home=home, io=io, repo_root=repo_root, cwd=cwd)
    except KeyboardInterrupt:
        sys.stderr.write("\nAborted.\n")
        return 130


def _has_install_table(project_config_path: Path) -> bool:
    """True iff ``project_config_path`` exists, parses as TOML, and has an
    ``[install]`` table. Best-effort: any read/parse failure counts as "no
    table" rather than raising — this feeds a passive, suggest-only notice
    on the USER path, which must never fail a real install over a malformed
    or unreadable file it does not own."""
    if not project_config_path.is_file():
        return False
    try:
        data = tomllib.loads(project_config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False
    return isinstance(data.get("install"), dict)


def _run(
    argv: list[str] | None = None,
    *,
    home: Path | None = None,
    io: IOPort | None = None,
    repo_root: Path | None = None,
    cwd: Path | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    resolved_home = home if home is not None else Path.home()
    resolved_repo_root = repo_root if repo_root is not None else _REPO_ROOT
    resolved_cwd = cwd if cwd is not None else Path.cwd()

    if args.profiles is not None and args.project is None:
        sys.stderr.write("installer: --profiles requires --project in this version\n")
        return 2
    if args.project is not None and not args.project.is_dir():
        sys.stderr.write(f"installer: --project path is not a directory: {args.project}\n")
        return 2

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

    # Stage once, up front, for EVERY path (--dump-stage, install, --prune): the
    # same StagingPlan set feeds the dump, the install, and the prune orphan-scan,
    # so --prune is install-then-prune over ONE plan. Staging is deterministic,
    # writes nothing to disk, and does not read installer.toml, so producing the
    # plan here changes neither the prune outcome nor its error handling — only a
    # verbose adapter transform notice (e.g. Gemini) may now precede a toml error,
    # which is immaterial. A fatal staging error — a registry wiring miss
    # (UnknownMergeKeyError) or an irreconcilable file collision (CollisionError) —
    # surfaces as an actionable exit 1 (matching the ConsentRequiredError
    # convention and bash's `err … exit 1`), not an uncaught traceback; the
    # exception message names the offending key / paths. This single guard covers
    # both the --dump-stage and install paths.
    try:
        plans = stage_and_transform(
            tools, repo_root=resolved_repo_root, io=io, ignore=ignore, plugins=plugins
        )
    except (UnknownMergeKeyError, CollisionError) as exc:
        sys.stderr.write(f"installer: {exc}\n")
        return 1

    # A `--project` run forks here to the project-scoped tail: it installs kit
    # content (tool-agnostic project refs) under a project-local receipt and
    # never touches user space or runs the user tool/plugin install below. This
    # fork sits BEFORE the user `--dump-stage` branch below so `--project
    # --dump-stage` renders the resolved PROJECT plan (tool refs + kit refs)
    # from inside `_run_project` instead of falling through to the user dump.
    if args.project is not None:
        return _run_project(
            args, plans=plans, project_root=args.project, repo_root=resolved_repo_root, io=io
        )

    if args.dump_stage is not None:
        try:
            dump_plan(plans, args.dump_stage, io=io)
        except ValueError as exc:
            # A non-empty target or an escaping plan path fails the dump cleanly
            # (exit 2) rather than as an uncaught traceback, matching the CLI's
            # other guarded error paths.
            sys.stderr.write(f"installer: {exc}\n")
            return 2
        return 0

    # Resolver-on for the user path (S2 Task 9): narrow every tool plan to the
    # USER-bound refs the active profile selection resolves to. The user CLI
    # exposes no --profiles flag yet, so the selection is always empty, which
    # resolve() treats as the "full" profile (`include = ["**"]`) — every
    # staged item matches, so filtering changes nothing and the install stays
    # byte-identical to the pre-resolver output. Guarded on a non-empty
    # universe: an empty universe (every active tool plan staged zero items)
    # has nothing to resolve or filter, and skipping avoids both a spurious
    # profiles.toml requirement and resolve()'s "matches nothing"/"resolves to
    # zero items" errors on synthetic all-empty fixtures — real installs always
    # stage at least one item, so this guard never changes real behavior.
    universe = project_universe(plans.values())
    if universe:
        manifest = load_manifest(resolved_repo_root / "profiles.toml")
        resolved = resolve(manifest, (), universe, bound_scopes=frozenset({Scope.USER}))
        kept_by_tool: dict[Tool, set[Path]] = {}
        for ref in resolved.included.get(Scope.USER, ()):
            if ref.tool is not None:
                kept_by_tool.setdefault(ref.tool, set()).add(ref.dest_relpath)
        plans = {
            tool: filter_plan_to_scope(plan, kept_by_tool.get(tool, set()))
            for tool, plan in plans.items()
        }

    config = Config(home=resolved_home, tools=tools, auto_yes=args.yes)
    adapters = [get_adapter(tool) for tool in tools]

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

    # Passive, suggest-only notice for the USER path only (a --project run
    # returns earlier via _run_project and never reaches here): if cwd looks
    # like a project (a .beads/ dir, or a project-config.toml carrying an
    # [install] table), point at the project-scoped install without acting
    # on it. No scan beyond cwd itself.
    if (resolved_cwd / ".beads").is_dir() or _has_install_table(
        resolved_cwd / "project-config.toml"
    ):
        io.info(
            "This looks like a project. To install project-scoped content "
            "here: install.sh --project ."
        )

    return 0


def _run_project(
    args: argparse.Namespace,
    *,
    plans: dict[Tool, StagingPlan],
    project_root: Path,
    repo_root: Path,
    io: IOPort,
) -> int:
    """The project-scoped tail: install kit content under ``project_root``.

    Tracer scope only (S2 plan Task 8) — kit refs alone. A kit rides the
    existing plugin-route machinery under owner ``kit:<name>`` via
    ``_KitRouteAdapter``, so it needs no new receipt/prune plumbing: this
    mirrors the user path's plugin-route install + receipt-record, scoped to a
    project-local receipt and lock instead of the user one. The user tool
    sync, user plugin routes, prune, and validation passes never run here.
    """
    kits_root = repo_root / "src" / "kits"
    staged_kits = stage_kits(kits_root)
    universe = project_universe(plans.values())
    for key, refs in kit_universe(staged_kits).items():
        universe.setdefault(key, []).extend(refs)

    manifest = load_manifest(repo_root / "profiles.toml")
    if args.profiles:
        selection: tuple[str, ...] = tuple(p.strip() for p in args.profiles.split(","))
    else:
        persisted = read_project_profiles(project_root)
        if persisted is not None:
            selection = persisted
        else:
            sys.stderr.write(
                "installer: project install needs an explicit profile (no implicit full)\n"
            )
            return 2
    # Pre-resolve kit-scope guard: kits are project-only. resolve() discards a
    # dropped ref's identity into anonymous per-scope counts, so a check after
    # resolve() would be a tautology — it can never name the offending
    # selector. Walk the selected profiles' IncludeEntries directly instead.
    kit_keys = set(kit_universe(staged_kits))
    for name in selection:
        profile = manifest.profiles.get(name)
        if profile is None:
            continue  # let resolve() raise the real unknown-profile error
        for entry in profile.includes:
            scope = entry.scope
            if (
                scope is not None
                and scope is not Scope.PROJECT
                and any(_selector_matches(entry.selector, key) for key in kit_keys)
            ):
                sys.stderr.write(
                    f"installer: kit selector {entry.selector!r} cannot be scoped to "
                    f"{scope.value!r}; kits are project-only\n"
                )
                return 2

    resolved = resolve(manifest, selection, universe, bound_scopes=frozenset({Scope.PROJECT}))

    # A kit is selected iff at least one of its refs' dest_relpaths landed in
    # the resolved PROJECT scope.
    project_dests = {r.dest_relpath for r in resolved.included.get(Scope.PROJECT, ())}
    selected_kits = {
        kit_name_of(sk.selector_key) for sk in staged_kits if sk.ref.dest_relpath in project_dests
    }
    kit_route_adapters = kit_adapters(kits_root, project_root, selected=selected_kits)

    # Tool tail: refs in the resolved PROJECT scope with a tool (as opposed to
    # tool-agnostic kit refs, whose `ref.tool is None`) get synced under
    # `project_root`'s tool tree instead of the plugin-route path above.
    # Validation-first: every such ref's top-level namespace segment must be
    # one of the destination tool's declared `project_namespaces()` — a tool
    # with an empty `project_namespaces()` (Codex/Gemini/OpenCode today)
    # accepts no project-scoped tool refs at all. Fails loud, naming the tool
    # and namespace, before any file is written.
    tool_dest_relpaths: dict[Tool, set[Path]] = {}
    for ref in resolved.included.get(Scope.PROJECT, ()):
        if ref.tool is not None:
            tool_dest_relpaths.setdefault(ref.tool, set()).add(ref.dest_relpath)
    for tool, dest_relpaths in tool_dest_relpaths.items():
        allowed_namespaces = set(get_adapter(tool).project_namespaces())
        for dest_relpath in sorted(dest_relpaths):
            namespace = dest_relpath.parts[0]
            if namespace not in allowed_namespaces:
                sys.stderr.write(
                    f"installer: tool {tool.value!r} cannot install {namespace!r} to "
                    f"project scope (not in its project_namespaces()); selected "
                    f"path: {dest_relpath}\n"
                )
                return 1

    tool_adapters = [get_adapter(tool) for tool in tool_dest_relpaths]
    tool_dest_roots = {adapter.name: adapter.dest_dir(project_root) for adapter in tool_adapters}
    tool_plans = {
        tool: filter_plan_to_scope(plans[tool], dest_relpaths)
        for tool, dest_relpaths in tool_dest_relpaths.items()
    }

    # `--project --dump-stage` renders the resolved PROJECT plan and returns —
    # read-only, like the user dump branch it replaces for this path. Tool
    # refs materialise via the same `dump_plan` tree the user path uses (empty
    # when the resolved plan carries none); kit refs have no tool tree to land
    # in, so they render as a `kit:<name>  <dest_relpath>` listing instead.
    # Nothing under `project_root` is written — no kit content, no receipt.
    if args.dump_stage is not None:
        try:
            dump_plan(tool_plans, args.dump_stage, io=io)
        except ValueError as exc:
            sys.stderr.write(f"installer: {exc}\n")
            return 2
        for name, dest_relpath in sorted(
            (kit_name_of(sk.selector_key), sk.ref.dest_relpath)
            for sk in staged_kits
            if sk.ref.dest_relpath in project_dests
        ):
            io.info(f"kit:{name}  {dest_relpath}")
        return 0

    receipt_path = project_root / ".agents-config" / "install-receipt.json"
    lock_cm: AbstractContextManager[None] = (
        nullcontext() if args.dry_run else receipt_lock(receipt_path.with_suffix(".lock"))
    )
    counters: dict[str, Counters] = {}
    tool_outcomes: dict[str, list[InstallOutcome]] = {}
    plugin_outcomes: dict[str, list[InstallOutcome]] = {}
    pruned_paths: set[Path] = set()
    relinquished_paths: set[Path] = set()
    # ALL kit names present under src/kits/ — selected or not — so a
    # deselected kit's prior receipt entry lands in scope_owners and is
    # prunable (mirrors the user path's discovered_plugin_names, which is
    # also the full discovered set, not just the resolved selection).
    all_kit_owner_names = {f"kit:{name}" for name in kit_routes(kits_root, project_root)}
    try:
        with lock_cm:
            prior_read = read_receipt(receipt_path)
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
                            tool_adapters,
                            plans=tool_plans,
                            home=project_root,
                            io=io,
                            dry_run=args.dry_run,
                            auto_yes=args.yes,
                            outcomes_by_tool=tool_outcomes,
                        ),
                    )
                    _merge_into(
                        counters,
                        install_plugin_routes(
                            kit_route_adapters,
                            home=project_root,
                            io=io,
                            dry_run=args.dry_run,
                            auto_yes=args.yes,
                            outcomes_by_plugin=plugin_outcomes,
                        ),
                    )
                except ConsentRequiredError:
                    return 1

            if args.prune or args.prune_only:
                try:
                    outcome = prune_pipeline(
                        tool_adapters,
                        plugins=kit_route_adapters,
                        plans=tool_plans,
                        prior=prior,
                        home=project_root,
                        discovered_plugin_names=all_kit_owner_names,
                        io=io,
                        dry_run=args.dry_run,
                        auto_yes=args.yes,
                        prune_only=args.prune_only,
                    )
                except PruneAbortedError:
                    return 1
                _merge_into(counters, outcome.counters)
                pruned_paths = outcome.pruned_paths
                relinquished_paths = outcome.relinquished_paths

            if not args.dry_run:
                record_receipt(
                    receipt_path,
                    prior=prior,
                    dest_roots=tool_dest_roots,
                    home=project_root,
                    tool_outcomes=tool_outcomes,
                    plugin_outcomes=plugin_outcomes,
                    pruned_paths=pruned_paths,
                    relinquished_paths=relinquished_paths,
                )
                write_project_profiles(project_root, selection)
    except ReceiptLockBusy:
        io.err(f"another install holds the project receipt lock at {receipt_path}")
        return 1

    render_summary(
        counters,
        tools=[t.value for t in tool_dest_relpaths],
        plugins=sorted(plugin_outcomes),
        all_tools=[],
        all_plugins=[],
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
