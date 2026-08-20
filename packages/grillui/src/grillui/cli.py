"""Argument parsing for the grillui console script.

The parser is all there is yet: it proves the entry point resolves and gives
`--help` and `--version` an answer. Serving the UI, folding the decision log
and driving the tiers arrive in the backend slices.
"""

from __future__ import annotations

import argparse

from grillui import __version__


def build_parser() -> argparse.ArgumentParser:
    """The CLI root. Subcommands land here as the backend is built out."""
    parser = argparse.ArgumentParser(
        prog="grillui",
        description="Backend for the grilling session UI. Under construction — no commands yet.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def entry(argv: list[str] | None = None) -> int:
    """Console-script entry point. Bare invocation prints help rather than
    exiting silently, since there is no default action to take yet."""
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
