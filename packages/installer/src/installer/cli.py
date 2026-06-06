from __future__ import annotations

import argparse
import sys
from pathlib import Path

from installer.config import Config, resolve_tools
from installer.tools.registry import UnknownToolError, get_adapter, known_tools


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
    return parser


def main(argv: list[str] | None = None, *, home: Path | None = None) -> int:
    args = _build_parser().parse_args(argv)
    resolved_home = home if home is not None else Path.home()

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

    # B.1: instantiation proves Config construction succeeds end-to-end.
    # The full install pipeline is not wired here yet. When core/sync.py grows
    # to walk a StagingPlan (Epic E), main() must drive
    # core.orchestrator.stage_and_transform(tools, ...) — NOT build_plan->sync
    # directly — so adapter post-staging transforms (e.g. the Gemini frontmatter
    # transform) actually run in real installs. Tracked as a dedicated story.
    Config(home=resolved_home, tools=tools)
    return 0
