from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from installer.config import Config, resolve_plugins, resolve_tools
from installer.core.consent import ConsentRequiredError, require_consent
from installer.core.dump import dump_plan
from installer.core.installer_toml import load_installer_toml
from installer.core.orchestrator import stage_and_transform
from installer.core.prune_flow import PruneAbortedError
from installer.core.run import prune_pipeline
from installer.tools.registry import UnknownToolError, get_adapter, known_tools

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.core.model import Tool

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

    if not tools:
        sys.stderr.write(
            "installer: no agent tools detected; cannot proceed.\n"
            "Auto-detection checks each known tool's installation signal:\n"
        )
        for known in known_tools():
            adapter = get_adapter(known)
            detected_path = resolved_home / adapter.detection_signal
            sys.stderr.write(f"  {known.value}: {detected_path}\n")
        sys.stderr.write(
            f"None of the above were found under {resolved_home}.\n"
            "To force installation, pass --tools=<csv>, e.g. --tools=claude.\n"
        )
        return 2

    if args.dump_stage is not None:
        plugins = resolve_plugins(
            home=resolved_home,
            plugins_root=resolved_repo_root / "src" / "plugins",
            override_csv=None,
        )
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

    # B.1: instantiation proves Config construction succeeds end-to-end; the
    # object is intentionally not bound — the full plan-walking install sync is
    # not wired here yet. When core/sync.py grows to walk a StagingPlan (Epic E),
    # main() must drive core.orchestrator.stage_and_transform(tools, ...) — NOT
    # build_plan->sync directly — so adapter post-staging transforms (e.g. the
    # Gemini frontmatter transform) actually run in real installs, and that sync
    # is where Config.auto_yes finds its consumer. Today auto_yes reaches the
    # prune path directly via args.yes below; the Config field is forward-wiring
    # for when sync() reads it. Tracked as a dedicated story.
    Config(home=resolved_home, tools=tools, auto_yes=args.yes)

    if args.prune or args.prune_only:
        return _run_prune(
            tools,
            io=io,
            home=resolved_home,
            repo_root=resolved_repo_root,
            dry_run=args.dry_run,
            auto_yes=args.yes,
            prune_only=args.prune_only,
        )

    return 0


def _run_prune(
    tools: tuple[Tool, ...],
    *,
    io: IOPort,
    home: Path,
    repo_root: Path,
    dry_run: bool,
    auto_yes: bool,
    prune_only: bool,
) -> int:
    """Drive the prune pipeline behind --prune / --prune-only.

    Builds the in-memory plans (the prune scan compares the dest tree against
    them), then runs scan + interactive flow. The install half of --prune is not
    performed: the plan-walking install sync is not yet wired into main() (see
    the Config note above), so today --prune performs only its prune half. The
    sequencing is structured so the install phase slots in ahead of this call
    when that story lands.

    The prune list is read from ``installer.toml`` under the passed
    ``repo_root`` (not off ``__file__``), so the config tracks the same root as
    ``stage_and_transform``. When that file is absent — e.g. a wheel/install
    that bundles only ``src/installer`` and omits ``installer.toml`` — the load
    yields an empty prune list, so nothing would be pruned; a warning is emitted
    naming the missing path so the no-op is explained rather than silent. A
    *present but type-malformed* ``installer.toml`` makes ``load_installer_toml``
    raise ``ValueError``; that is caught here and surfaced through ``io`` as a
    clean error with ``return 2`` (the CLI's config-error exit convention),
    never an uncaught traceback.

    Plugin discovery is likewise rooted at the passed ``repo_root``
    (``repo_root / "src" / "plugins"``), so ``repo_root`` is fully
    authoritative — config and plugins resolve against one injected root rather
    than splitting between the argument and a module-level constant.

    Returns 0 on success, 1 when the non-interactive consent guard or the
    prune-only flow aborts the run, 2 when ``installer.toml`` is malformed.
    """
    if not prune_only:
        try:
            require_consent(io, dry_run=dry_run, auto_yes=auto_yes)
        except ConsentRequiredError:
            return 1

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
    plugins_root = repo_root / "src" / "plugins"
    plugins = resolve_plugins(home=home, plugins_root=plugins_root, override_csv=None)
    plans = stage_and_transform(tools, repo_root=repo_root, io=io, plugins=plugins)
    adapters = [get_adapter(tool) for tool in tools]

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
