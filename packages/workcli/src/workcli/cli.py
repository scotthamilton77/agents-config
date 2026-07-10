"""workcli CLI — argparse wiring, protocol handshake, and the dispatch loop.

`main()` is the single injectable entry point: every outside-world dependency
(argv, the bd runner, stdout/stderr, sleep) arrives as an argument, never a
module global. The `Backend` itself is constructed lazily, inside `main()`,
only when a verb actually dispatches -- `--protocol-version` short-circuits
before it and never touches the runner (spec §5: the handshake is cheap and
side-effect-free).
"""

from __future__ import annotations

import sys
import time
import traceback
from argparse import ArgumentParser, _SubParsersAction
from collections.abc import Callable, Sequence
from typing import NoReturn, TextIO

from workcli import PROTOCOL_VERSION
from workcli.adapters.bd.backend import BdBackend
from workcli.adapters.bd.runner import BdRunner, SubprocessBdRunner
from workcli.envelope import ErrorCode, WorkError, emit_failure, emit_success
from workcli.verbs import VERBS, missing_capability


class _EnvelopeArgumentParser(ArgumentParser):
    """Raises on a parse failure instead of printing usage and calling `sys.exit`.

    Default argparse behavior on error prints a usage block to stderr and
    exits — that would violate the "stdout is always exactly one JSON
    envelope" invariant (spec §4). Raising lets `main()` convert the failure
    into an `E_USAGE` envelope instead.
    """

    def error(self, message: str) -> NoReturn:
        raise WorkError(ErrorCode.USAGE, message)


def _add_read_subparsers(subparsers: _SubParsersAction[_EnvelopeArgumentParser]) -> None:
    show_parser = subparsers.add_parser("show", help="show one or more items by id")
    show_parser.add_argument("ids", nargs="+", metavar="ID")

    list_parser = subparsers.add_parser("list", help="list items, unbounded unless --limit")
    list_parser.add_argument("--status")
    list_parser.add_argument("--label")
    list_parser.add_argument("--parent")
    list_parser.add_argument("--type")
    list_parser.add_argument("--limit", type=int, default=None)

    ready_parser = subparsers.add_parser("ready", help="list ready-to-work items, unbounded")
    ready_parser.add_argument("--label")

    search_parser = subparsers.add_parser("search", help="search items by query text")
    search_parser.add_argument("query", metavar="QUERY")


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
    # `parser_class` propagates the raise-don't-exit `error()` override to
    # every subparser too -- a bad flag inside `work show --bogus` must reach
    # main()'s WorkError handling exactly like a bad top-level flag does,
    # never argparse's own stderr-and-exit path.
    subparsers = parser.add_subparsers(dest="verb", parser_class=_EnvelopeArgumentParser)
    _add_read_subparsers(subparsers)
    return parser


def _build_backend(runner: BdRunner | None, sleep: Callable[[float], None] | None) -> BdBackend:
    return BdBackend(
        runner if runner is not None else SubprocessBdRunner(),
        sleep=sleep if sleep is not None else time.sleep,
    )


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

    # Constructed only now -- never for --protocol-version above -- so the
    # handshake never touches the runner (spec §5).
    backend = _build_backend(runner, sleep)

    if missing_capability(args.verb, backend.capabilities):
        return emit_failure(
            WorkError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                f"{args.verb}: not supported by this backend",
            ),
            out,
        )

    try:
        data = handler(backend, args)
    except WorkError as verb_error:
        return emit_failure(verb_error, out)
    except Exception:
        traceback.print_exc(file=err)
        return emit_failure(WorkError(ErrorCode.INTERNAL, "internal error"), out)
    return emit_success(data, out)


def entry() -> None:
    sys.exit(main())
