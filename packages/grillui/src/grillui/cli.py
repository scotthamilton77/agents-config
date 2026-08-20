"""Argument parsing for the grillui console script.

`serve` runs one backend process over one session directory. A new directory is
started from a handoff -- named with `--handoff`, or `handoff.json` inside the
directory itself -- and a directory whose log already holds entries is resumed
from that log, whatever the handoff file now says. Refusing a handoff exits
non-zero naming the field, and leaves nothing behind.

Loopback is the only interface it binds; port fallback and handing the URL to a
browser arrive with the launch path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from grillui import __version__
from grillui.api import create_app
from grillui.drivers import FastDriver
from grillui.log import HANDOFF_FILE
from grillui.session import HandoffRefusedError, open_session
from grillui.tiers import TierConfig

DEFAULT_PORT = 8765
LOOPBACK = "127.0.0.1"
REFUSED_STATUS = 2


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
        "--handoff",
        type=Path,
        default=None,
        help=(
            f"the handoff file a new session is briefed from "
            f"(default: {HANDOFF_FILE} in the session directory); "
            f"ignored when the directory's log already holds entries"
        ),
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
        try:
            return serve(args.session_dir, args.port, args.handoff)
        except HandoffRefusedError as refusal:
            # The one failure a caller can act on: the message names the field.
            # Nothing was initialised, so fixing the file and re-running is the
            # whole recovery.
            print(refusal, file=sys.stderr)
            return REFUSED_STATUS
    parser.print_help()
    return 0


def serve(session_dir: Path, port: int, handoff: Path | None = None) -> int:  # pragma: no cover
    """Open the session -- seeding a new one from its handoff, resuming an
    existing one from its log -- and serve its board until the process stops.

    The fast tier takes the turns: it is what a channel starts on, and moving one
    to the heavy tier is the human's gesture rather than a launch setting. Which
    models both tiers are comes from the environment.
    """
    log = open_session(session_dir, handoff)
    app = create_app(log, FastDriver(TierConfig.from_env()))
    uvicorn.run(app, host=LOOPBACK, port=port)
    return 0
