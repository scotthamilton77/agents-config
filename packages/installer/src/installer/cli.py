from __future__ import annotations

import argparse
import sys
from pathlib import Path

from installer.config import Config, resolve_plugins, resolve_tools
from installer.core.dump import dump_plan
from installer.core.io_port import TerminalIO
from installer.core.orchestrator import stage_and_transform
from installer.tools.registry import UnknownToolError, get_adapter, known_tools

# The repo root is the agents-config checkout containing ``src/user/.agents`` and
# ``src/plugins``. ``cli.py`` lives at ``<repo>/packages/installer/src/installer/
# cli.py``, so the fourth parent is the repo root. ``uv`` installs this package
# editable, so ``__file__`` stays inside the source tree and this resolution holds
# at runtime; tests inject ``repo_root`` directly. Mirrors the bash installer's
# ``PROJECT_ROOT="$SCRIPT_DIR/.."`` (scripts/install.sh:197-198).
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
    # --dump-stage joins a mutually exclusive group so the prune flags (added by a
    # sibling story) can be dropped into the SAME group, making
    # --dump-stage ⊥ --prune/--prune-only fall out of argparse for free. On this
    # branch the group has a single member; that is intentional, not an oversight.
    exclusive = parser.add_mutually_exclusive_group()
    exclusive.add_argument(
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
    repo_root: Path | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    resolved_home = home if home is not None else Path.home()
    resolved_repo_root = repo_root if repo_root is not None else _REPO_ROOT

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
        io = TerminalIO()
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

    # B.1: instantiation proves Config construction succeeds end-to-end.
    # The full install pipeline is not wired here yet. When core/sync.py grows
    # to walk a StagingPlan (Epic E), main() must drive
    # core.orchestrator.stage_and_transform(tools, ...) — NOT build_plan->sync
    # directly — so adapter post-staging transforms (e.g. the Gemini frontmatter
    # transform) actually run in real installs. Tracked as a dedicated story.
    Config(home=resolved_home, tools=tools)
    return 0
