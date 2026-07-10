"""workcli CLI — argparse wiring, protocol handshake, and the dispatch loop.

`main()` is the single injectable entry point: every outside-world dependency
(argv, the bd runner, stdout/stderr, sleep) arrives as an argument, never a
module global. The verb registry (`VERBS`) starts empty in this scaffold;
later tasks populate it and wire matching argparse subparsers (Task 3+).
"""

from __future__ import annotations

import sys
import traceback
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence
from typing import NoReturn, TextIO

from workcli import PROTOCOL_VERSION
from workcli.adapters.bd.runner import BdRunner
from workcli.envelope import ErrorCode, JsonValue, WorkError, emit_failure, emit_success

#: verb name -> handler. Populated by later tasks; empty here means every verb
#: name is, correctly, unrecognized (E_USAGE).
VERBS: dict[str, Callable[[Namespace], JsonValue]] = {}


class _EnvelopeArgumentParser(ArgumentParser):
    """Raises on a parse failure instead of printing usage and calling `sys.exit`.

    Default argparse behavior on error prints a usage block to stderr and
    exits — that would violate the "stdout is always exactly one JSON
    envelope" invariant (spec §4). Raising lets `main()` convert the failure
    into an `E_USAGE` envelope instead.
    """

    def error(self, message: str) -> NoReturn:
        raise WorkError(ErrorCode.USAGE, message)


def _build_parser() -> _EnvelopeArgumentParser:
    parser = _EnvelopeArgumentParser(prog="work", description="work — issue-tracker facade CLI")
    parser.add_argument(
        "--protocol-version",
        action="store_true",
        help="print the envelope protocol version and exit",
    )
    parser.add_argument(
        "--format",
        choices=["json", "human"],
        default="json",
        help="human rendering goes to stderr; stdout always carries the JSON envelope",
    )
    parser.add_argument("verb", nargs="?", help="one of the work verbs")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: BdRunner | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
    sleep: Callable[[float], None] | None = None,
) -> int:
    if out is None:
        out = sys.stdout
    if err is None:
        err = sys.stderr

    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except WorkError as usage_error:
        return emit_failure(usage_error, out)

    if args.protocol_version:
        return emit_success({"protocol": PROTOCOL_VERSION}, out)

    handler = VERBS.get(args.verb)
    if handler is None:
        return emit_failure(WorkError(ErrorCode.USAGE, f"unknown verb: {args.verb!r}"), out)

    try:
        data = handler(args)
    except WorkError as verb_error:
        return emit_failure(verb_error, out)
    except Exception:
        traceback.print_exc(file=err)
        return emit_failure(WorkError(ErrorCode.INTERNAL, "internal error"), out)
    return emit_success(data, out)


def entry() -> None:
    sys.exit(main())
