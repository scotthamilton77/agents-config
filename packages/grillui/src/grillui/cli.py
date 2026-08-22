"""Argument parsing for the grillui console script.

`serve` runs one backend process over one session directory, and is a session
end to end: it prints the URL, serves the board on loopback until the process
exits, and leaves the terminal result on stdout. `--open` additionally opens a
browser at that URL once the board is answering; without it the printed URL is
the whole hand-over, since the caller is usually an agent and the desktop is
somebody else's. A new directory is
started from a handoff -- named with `--handoff`, or `handoff.json` inside the
directory itself -- and a directory whose log already holds entries is resumed
from that log, whatever the handoff file now says. Refusing a handoff exits
non-zero naming the field, and leaves nothing behind.

`capture` is the same terminal result over a directory nothing is serving, for
a session that ended without one being written or that ended last week. It runs
no server and needs no process to have survived.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from grillui import __version__
from grillui.launch import DEFAULT_PORT, launch, report
from grillui.log import HANDOFF_FILE, LOG_FILE
from grillui.session import HandoffRefusedError

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
        help=f"preferred loopback port (default {DEFAULT_PORT}; the next free one is taken)",
    )
    serve_command.add_argument(
        "--open",
        action="store_true",
        help="open a browser at the session URL once the board is answering",
    )
    capture_command = commands.add_parser(
        "capture", help="write and print a finished session's terminal result"
    )
    capture_command.add_argument(
        "session_dir",
        type=Path,
        help="the session directory to capture; nothing need be serving it",
    )
    return parser


def entry(argv: list[str] | None = None) -> int:
    """Console-script entry point. A bare invocation prints help rather than
    exiting silently, since there is no default action to take."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        try:
            return launch(args.session_dir, args.port, args.handoff, open_browser=args.open)
        except HandoffRefusedError as refusal:
            # The one failure a caller can act on: the message names the field.
            # Nothing was initialised, so fixing the file and re-running is the
            # whole recovery.
            print(refusal, file=sys.stderr)
            return REFUSED_STATUS
    if args.command == "capture":
        return capture_session(args.session_dir)
    parser.print_help()
    return 0


def capture_session(session_dir: Path) -> int:
    """Capture a directory that holds a session, or say it does not.

    A directory with no log is refused rather than captured: the fold over an
    empty log is a well-formed result saying a session decided nothing, and
    handing that to someone who mistyped a path would answer their question
    falsely.
    """
    if not (session_dir / LOG_FILE).is_file():
        missing = f"no session log at {str(session_dir / LOG_FILE)!r}"
        print(missing, file=sys.stderr)
        return REFUSED_STATUS
    return report(session_dir, out=sys.stdout)
