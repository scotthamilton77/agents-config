from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from installer.config import Config, resolve_plugins, resolve_tools
from installer.core.consent import ConsentRequiredError, require_consent
from installer.core.installer_toml import load_installer_toml
from installer.core.orchestrator import stage_and_transform
from installer.core.prune_flow import PruneAbortedError
from installer.core.run import prune_pipeline
from installer.tools.registry import UnknownToolError, get_adapter, known_tools

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.core.model import Tool

# Repo root is four parents up from this file:
# packages/installer/src/installer/cli.py -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
# Bundled installer config (prune list + tool overrides) and plugin source root.
_INSTALLER_TOML = _REPO_ROOT / "packages" / "installer" / "installer.toml"
_PLUGINS_ROOT = _REPO_ROOT / "src" / "plugins"


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
    # --prune and --prune-only are mutually exclusive. This group is the seam a
    # later story extends to add the --dump-stage ⊥ --prune exclusion (the
    # --dump-stage flag lands in a sibling PR); keep prune flags grouped so that
    # integration only has to widen the group, not restructure the parser.
    prune_group = parser.add_mutually_exclusive_group()
    prune_group.add_argument(
        "--prune",
        action="store_true",
        help="After install, remove retired paths from installer.toml (with backup).",
    )
    prune_group.add_argument(
        "--prune-only",
        action="store_true",
        help="Skip install; scan + remove retired paths from installer.toml.",
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

    Returns 0 on success, 1 when the non-interactive consent guard or the
    prune-only flow aborts the run.
    """
    if not prune_only:
        try:
            require_consent(io, dry_run=dry_run, auto_yes=auto_yes)
        except ConsentRequiredError:
            return 1

    config = load_installer_toml(_INSTALLER_TOML)
    plugins = resolve_plugins(home=home, plugins_root=_PLUGINS_ROOT, override_csv=None)
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
