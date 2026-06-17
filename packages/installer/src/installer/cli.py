from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from installer.config import Config, resolve_plugins, resolve_plugins_root, resolve_tools
from installer.core.consent import ConsentRequiredError
from installer.core.dump import dump_plan
from installer.core.installer_toml import load_installer_toml
from installer.core.orchestrator import stage_and_transform
from installer.core.prune_flow import PruneAbortedError
from installer.core.run import install_pipeline, prune_pipeline
from installer.tools.registry import UnknownToolError, get_adapter, known_tools

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan, Tool
    from installer.tools.base import ToolAdapter

# The repo root is the agents-config checkout containing ``src/user/.agents`` and
# ``src/plugins``. ``cli.py`` lives at ``<repo>/packages/installer/src/installer/
# cli.py``, so the fourth parent is the repo root. ``uv`` installs this package
# editable, so ``__file__`` stays inside the source tree and this resolution holds
# at runtime; tests inject ``repo_root`` directly. Mirrors the bash installer's
# ``PROJECT_ROOT="$SCRIPT_DIR/.."`` (scripts/install.sh:197-198). The bundled
# installer.toml path and the plugin source root are derived per-run from the
# injected repo_root (default: _REPO_ROOT), keeping repo_root fully authoritative
# for staging, config, and plugin discovery alike.
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
    # --dump-stage, --prune, and --prune-only are three mutually exclusive
    # terminal modes (dump the staging plan / install-then-prune / prune-only),
    # so any combination is rejected by argparse.
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--prune",
        action="store_true",
        help="After install, remove retired paths from installer.toml (with backup).",
    )
    mode_group.add_argument(
        "--prune-only",
        action="store_true",
        help="Skip install; scan + remove retired paths from installer.toml.",
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
    args = _build_parser().parse_args(argv)
    resolved_home = home if home is not None else Path.home()
    resolved_repo_root = repo_root if repo_root is not None else _REPO_ROOT

    if io is None:
        from installer.core.io_port import TerminalIO

        io = TerminalIO()

    try:
        tools = resolve_tools(home=resolved_home, override_csv=args.tools)
    except (UnknownToolError, ValueError) as exc:
        sys.stderr.write(f"installer: {exc}\n")
        return 2

    # Resolve plugins up front (after tools) so an invalid --plugins fails fast
    # on every path — matching the bash installer, which validates --plugins
    # before dispatching any mode (scripts/install.sh:298-307). The resolved set
    # feeds both --dump-stage and --prune below.
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

    if args.dump_stage is not None:
        plans = stage_and_transform(tools, repo_root=resolved_repo_root, io=io, plugins=plugins)
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
    plans = stage_and_transform(tools, repo_root=resolved_repo_root, io=io, plugins=plugins)

    # Default install path (also the install half of --prune): walk each active
    # tool's StagingPlan to disk via install_pipeline. Skipped only for
    # --prune-only, which removes retired paths without installing. Slots ahead
    # of the prune branch so --prune is install-then-prune, mirroring the bash
    # installer (scripts/install.sh copies before the retire sweep). Driving the
    # install through stage_and_transform is also what makes adapter post-staging
    # transforms (e.g. the Gemini frontmatter transform) fire in real installs,
    # not just --dump-stage / --prune.
    if not args.prune_only:
        try:
            install_pipeline(
                adapters,
                plans=plans,
                home=resolved_home,
                io=io,
                dry_run=args.dry_run,
                auto_yes=config.auto_yes,
            )
        except ConsentRequiredError:
            # A non-interactive run lacking --yes/--dry-run cannot answer the
            # per-file overwrite prompt; sync_plan's up-front guard raises before
            # any write. Surface it as the CLI's exit 1 (the prune flow uses the
            # same convention) rather than an uncaught traceback.
            return 1

    if args.prune or args.prune_only:
        return _run_prune(
            adapters,
            plans=plans,
            io=io,
            home=resolved_home,
            repo_root=resolved_repo_root,
            dry_run=args.dry_run,
            auto_yes=config.auto_yes,
            prune_only=args.prune_only,
        )

    return 0


def _run_prune(
    adapters: list[ToolAdapter],
    *,
    plans: dict[Tool, StagingPlan],
    io: IOPort,
    home: Path,
    repo_root: Path,
    dry_run: bool,
    auto_yes: bool,
    prune_only: bool,
) -> int:
    """Drive the prune pipeline behind --prune / --prune-only.

    Scans each active tool's dest tree against its already-built ``StagingPlan``
    (``plans``, produced once by ``main`` and shared with the install half), then
    runs the scan + interactive flow. Consent for ``--prune`` is owned upstream:
    ``main`` runs ``install_pipeline`` (whose ``sync_plan`` guard refuses a
    non-interactive run lacking ``--yes``/``--dry-run``) before this call, so the
    prune step needs no separate consent gate; ``--prune-only`` skips install and
    relies on the prune flow's own non-interactive hard-fail.

    The prune list is read from ``installer.toml`` under the passed ``repo_root``
    (not off ``__file__``), so the config tracks the same root the plans were
    staged from. When that file is absent — e.g. a wheel/install that bundles
    only ``src/installer`` and omits ``installer.toml`` — the load yields an empty
    prune list, so nothing would be pruned; a warning is emitted naming the
    missing path so the no-op is explained rather than silent. A *present but
    type-malformed* ``installer.toml`` makes ``load_installer_toml`` raise
    ``ValueError``; that is caught here and surfaced through ``io`` as a clean
    error with ``return 2`` (the CLI's config-error exit convention), never an
    uncaught traceback.

    The ``plans`` reflect the active ``--plugins`` selection (``main`` builds them
    with the resolved plugin set), so a plugin's overlaid files reach the orphan
    scan as known entries rather than retired ones.

    Returns 0 on success, 1 when the prune-only flow aborts the run, 2 when
    ``installer.toml`` is malformed.
    """
    installer_toml = repo_root / "packages" / "installer" / "installer.toml"
    if not installer_toml.is_file():
        io.warn(
            f"installer.toml not found at {installer_toml}; the prune list is "
            "empty, so nothing will be pruned."
        )
    try:
        config = load_installer_toml(installer_toml)
    except ValueError as exc:
        io.err(f"installer: {exc}")
        return 2

    try:
        prune_pipeline(
            adapters,
            plans=plans,
            home=home,
            config=config,
            io=io,
            dry_run=dry_run,
            auto_yes=auto_yes,
            prune_only=prune_only,
        )
    except PruneAbortedError:
        return 1
    return 0
