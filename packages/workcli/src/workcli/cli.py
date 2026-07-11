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
from workcli.envelope import ErrorCode, JsonValue, WorkError, emit_failure, emit_success
from workcli.render import render_human
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


def _add_write_subparsers(subparsers: _SubParsersAction[_EnvelopeArgumentParser]) -> None:
    create_parser = subparsers.add_parser(
        "create",
        help="create --raw: adapter primitive; public creation is the lifecycle layer's job",
    )
    create_parser.add_argument("--raw", action="store_true")
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--description")
    create_parser.add_argument("--type")
    create_parser.add_argument("--priority")
    create_parser.add_argument("--parent")
    create_parser.add_argument("--label", action="append", default=[], metavar="LABEL")

    update_parser = subparsers.add_parser(
        "update", help="update title/priority/description (replace semantics only)"
    )
    update_parser.add_argument("id", metavar="ID")
    update_parser.add_argument("--set-title")
    update_parser.add_argument("--set-priority")
    update_parser.add_argument("--set-description")
    # Recognized only so it reaches the named E_FIELD_CLOBBER_GUARD instead
    # of a generic E_USAGE unknown-flag error -- notes are append-only.
    update_parser.add_argument("--set-notes")

    note_parser = subparsers.add_parser("note", help="append a note (append-only)")
    note_parser.add_argument("id", metavar="ID")
    note_parser.add_argument("text", metavar="TEXT")

    close_parser = subparsers.add_parser("close", help="close one or more items")
    close_parser.add_argument("ids", nargs="+", metavar="IDS")
    close_parser.add_argument("--disposition")

    reopen_parser = subparsers.add_parser("reopen", help="reopen a closed item")
    reopen_parser.add_argument("id", metavar="ID")


def _add_relations_subparsers(subparsers: _SubParsersAction[_EnvelopeArgumentParser]) -> None:
    dep_parser = subparsers.add_parser("dep", help="manage dependency edges")
    dep_parser.add_argument("action", choices=["add", "remove", "list"])
    dep_parser.add_argument("id", metavar="ID")
    dep_parser.add_argument("target", nargs="?", metavar="TARGET")
    dep_parser.add_argument("--type")

    label_parser = subparsers.add_parser("label", help="manage labels")
    label_parser.add_argument("action", choices=["add", "remove", "list"])
    label_parser.add_argument("id", metavar="ID")
    label_parser.add_argument("labels", nargs="*", metavar="LABELS")


def _add_sync_subparser(subparsers: _SubParsersAction[_EnvelopeArgumentParser]) -> None:
    sync_parser = subparsers.add_parser(
        "sync", help="sync with the backend (bd: dolt commit+push, or --pull)"
    )
    sync_parser.add_argument("--pull", action="store_true")


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
    _add_write_subparsers(subparsers)
    _add_relations_subparsers(subparsers)
    _add_sync_subparser(subparsers)
    return parser


def _peek_format(argv: list[str] | None) -> str:
    """Best-effort recovery of `--format` when full parsing has already failed.

    `parse_args()` can raise (bad flag, unknown verb) before we learn whether
    `--format human` was requested, yet spec §4 says the human view still
    renders to stderr alongside the stdout envelope even on usage errors. A
    lenient parser that knows only `--format` and ignores everything else
    recovers the value without re-raising on the very error we're about to
    report; anything it can't make sense of (e.g. an invalid `--format`
    value) falls back to the JSON default.
    """
    peek = _EnvelopeArgumentParser(add_help=False)
    peek.add_argument("--format", choices=["json", "human"], default="json")
    try:
        known, _ = peek.parse_known_args(argv)
    except WorkError:
        return "json"
    return str(known.format)


def _finish_success(data: JsonValue, out: TextIO, err: TextIO, fmt: str) -> int:
    """Emit the success envelope to `out`; additionally render it to `err` on `--format human`.

    stdout always carries the envelope regardless of `fmt` (spec §4) -- this
    never replaces `emit_success`, only adds the human view alongside it.
    """
    exit_code = emit_success(data, out)
    if fmt == "human":
        render_human({"protocol": PROTOCOL_VERSION, "ok": True, "data": data, "error": None}, err)
    return exit_code


def _finish_failure(work_error: WorkError, out: TextIO, err: TextIO, fmt: str) -> int:
    """Emit the failure envelope to `out`; additionally render it to `err` on `--format human`."""
    exit_code = emit_failure(work_error, out)
    if fmt == "human":
        render_human(
            {
                "protocol": PROTOCOL_VERSION,
                "ok": False,
                "data": None,
                "error": {
                    "code": str(work_error.code),
                    "message": work_error.message,
                    "detail": work_error.detail,
                },
            },
            err,
        )
    return exit_code


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

    argv_list = list(argv) if argv is not None else None
    parser = _build_parser()
    try:
        args = parser.parse_args(argv_list)
    except WorkError as usage_error:
        return _finish_failure(usage_error, out, err, _peek_format(argv_list))

    if args.protocol_version:
        return _finish_success({"protocol": PROTOCOL_VERSION}, out, err, args.format)

    if args.verb is None:
        return _finish_failure(
            WorkError(
                ErrorCode.USAGE,
                f"no verb given; choose one of: {', '.join(VERBS)}",
            ),
            out,
            err,
            args.format,
        )

    # argparse's subparser `choices` already rejected any non-None verb that
    # isn't a registered subcommand, so a name reaching here is always in VERBS.
    handler = VERBS[args.verb]

    # Everything from here on -- backend construction, the capability gate,
    # and the handler call -- runs inside one guarded region. An exception
    # anywhere in this region must still yield exactly one envelope on
    # stdout (spec §4's invariant holds even on internal bugs, §4's
    # `E_INTERNAL` note) rather than escaping with a raw traceback and no
    # envelope at all.
    try:
        # Constructed only now -- never for --protocol-version above -- so the
        # handshake never touches the runner (spec §5).
        backend = _build_backend(runner, sleep)

        if missing_capability(args.verb, backend.capabilities):
            return _finish_failure(
                WorkError(
                    ErrorCode.UNSUPPORTED_CAPABILITY,
                    f"{args.verb}: not supported by this backend",
                ),
                out,
                err,
                args.format,
            )

        data = handler(backend, args)
    except WorkError as verb_error:
        return _finish_failure(verb_error, out, err, args.format)
    except Exception:
        traceback.print_exc(file=err)
        return _finish_failure(
            WorkError(ErrorCode.INTERNAL, "internal error"), out, err, args.format
        )
    return _finish_success(data, out, err, args.format)


def entry() -> None:
    sys.exit(main())
