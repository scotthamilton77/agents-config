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
            "installer: unable to apply changes — no agent tools detected.\n"
            "Auto-detection checks each known tool's installation signal:\n"
        )
        for known in known_tools():
            adapter = get_adapter(known)
            sys.stderr.write(f"  {known.value}: {resolved_home}/{adapter.detection_signal}\n")
        sys.stderr.write(
            f"None of the above were found under {resolved_home}.\n"
            "To force installation, pass --tools=<csv>, e.g. --tools=claude.\n"
        )
        return 2

    # B.1: instantiation proves Config construction succeeds end-to-end;
    # B.2's sync engine will consume the returned value.
    Config(home=resolved_home, tools=tools)
    return 0
