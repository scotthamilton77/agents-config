from __future__ import annotations

import argparse
import sys
from pathlib import Path

from installer.config import Config, resolve_tools
from installer.tools.registry import UnknownToolError, known_tools


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
        print(f"installer: {exc}", file=sys.stderr)
        return 2

    Config(home=resolved_home, tools=tools)
    return 0
