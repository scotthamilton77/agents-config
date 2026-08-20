"""Argument parsing for the grillui console script.

`serve` runs one backend process over one session directory. Loopback is the
only interface it binds; port fallback and handing the URL to a browser arrive
with the launch path.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from grillui import __version__
from grillui.api import create_app
from grillui.log import SessionLog

DEFAULT_PORT = 8765
LOOPBACK = "127.0.0.1"


def build_parser() -> argparse.ArgumentParser:
    """The CLI root. Subcommands land here as the backend is built out."""
    parser = argparse.ArgumentParser(
        prog="grillui",
        description="Backend for the grilling session UI.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    serve_command = commands.add_parser("serve", help="serve one grilling session over loopback")
    serve_command.add_argument(
        "session_dir",
        type=Path,
        help="the session directory; created if absent, resumed if it holds a log",
    )
    serve_command.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"loopback port (default {DEFAULT_PORT})",
    )
    return parser


def entry(argv: list[str] | None = None) -> int:
    """Console-script entry point. A bare invocation prints help rather than
    exiting silently, since there is no default action to take."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        return serve(args.session_dir, args.port)
    parser.print_help()
    return 0


def serve(session_dir: Path, port: int) -> int:  # pragma: no cover
    """Mint an epoch over the session directory and serve its board until the
    process is stopped."""
    uvicorn.run(create_app(SessionLog(session_dir)), host=LOOPBACK, port=port)
    return 0
