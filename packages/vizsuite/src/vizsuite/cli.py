"""vizsuite CLI — argparse wiring, protocol handshake, and the dispatch loop.

`main()` is the single injectable entry point: every outside-world dependency
(argv, the git/scc/gh runners, stdout/stderr) arrives as an argument, never a
module global. The `Runners` bundle is constructed lazily, inside `main()`, only
when a verb actually dispatches — `--protocol-version` short-circuits before it
and never touches any adapter (the handshake is cheap and side-effect-free).

Stdout always carries exactly one JSON envelope `{"protocol","ok","data",
"error"}`; `--format human` adds a rendering to stderr but never displaces the
stdout envelope. Exit is 0 on success, 1 on `VizError` or any unhandled error.
"""

from __future__ import annotations

import sys
import traceback
from argparse import ArgumentParser, _SubParsersAction
from collections.abc import Sequence
from typing import NoReturn, TextIO

from vizsuite import PROTOCOL_VERSION
from vizsuite.adapters.gh.runner import GhRunner, SubprocessGhRunner
from vizsuite.adapters.git.runner import GitRunner, SubprocessGitRunner
from vizsuite.adapters.scc.runner import SccRunner, SubprocessSccRunner
from vizsuite.envelope import ErrorCode, JsonValue, VizError, emit_failure, emit_success
from vizsuite.render import render_human
from vizsuite.runners import Runners
from vizsuite.verbs import VERBS


class _EnvelopeArgumentParser(ArgumentParser):
    """Raises on a parse failure instead of printing usage and calling `sys.exit`.

    Default argparse behavior on error prints a usage block to stderr and exits —
    that would violate the "stdout is always exactly one JSON envelope"
    invariant. Raising lets `main()` convert the failure into an `E_USAGE`
    envelope instead.
    """

    def error(self, message: str) -> NoReturn:
        raise VizError(ErrorCode.USAGE, message)


def _add_pr_subparser(subparsers: _SubParsersAction[_EnvelopeArgumentParser]) -> None:
    pr_parser = subparsers.add_parser("pr", help="build the PR-shape HTML artifact")
    pr_parser.add_argument("number", type=int, metavar="N", help="the pull-request number")


def _build_parser() -> _EnvelopeArgumentParser:
    parser = _EnvelopeArgumentParser(prog="viz", description="viz — repo/PR visualization suite")
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
    # `parser_class` propagates the raise-don't-exit `error()` override to every
    # subparser too — a bad flag inside `viz pr --bogus` must reach main()'s
    # VizError handling exactly like a bad top-level flag does.
    subparsers = parser.add_subparsers(dest="verb", parser_class=_EnvelopeArgumentParser)
    _add_pr_subparser(subparsers)
    return parser


def _peek_format(argv: list[str] | None) -> str:
    """Best-effort recovery of `--format` when full parsing has already failed.

    `parse_args()` can raise (bad flag, unknown verb) before we learn whether
    `--format human` was requested, yet the human view still renders to stderr
    alongside the stdout envelope even on usage errors. A lenient parser that
    knows only `--format` recovers the value without re-raising on the very
    error we're about to report; anything it can't make sense of falls back to
    the JSON default.
    """
    peek = _EnvelopeArgumentParser(add_help=False)
    peek.add_argument("--format", choices=["json", "human"], default="json")
    try:
        known, _ = peek.parse_known_args(argv)
    except VizError:
        return "json"
    return str(known.format)


def _finish_success(data: JsonValue, out: TextIO, err: TextIO, fmt: str) -> int:
    """Emit the success envelope to `out`; additionally render it to `err` on `--format human`."""
    exit_code = emit_success(data, out)
    if fmt == "human":
        render_human({"protocol": PROTOCOL_VERSION, "ok": True, "data": data, "error": None}, err)
    return exit_code


def _finish_failure(viz_error: VizError, out: TextIO, err: TextIO, fmt: str) -> int:
    """Emit the failure envelope to `out`; additionally render it to `err` on `--format human`."""
    exit_code = emit_failure(viz_error, out)
    if fmt == "human":
        render_human(
            {
                "protocol": PROTOCOL_VERSION,
                "ok": False,
                "data": None,
                "error": {
                    "code": str(viz_error.code),
                    "message": viz_error.message,
                    "detail": viz_error.detail,
                },
            },
            err,
        )
    return exit_code


def main(
    argv: Sequence[str] | None = None,
    *,
    git_runner: GitRunner | None = None,
    scc_runner: SccRunner | None = None,
    gh_runner: GhRunner | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    if out is None:
        out = sys.stdout
    if err is None:
        err = sys.stderr

    argv_list = list(argv) if argv is not None else None
    parser = _build_parser()
    try:
        args = parser.parse_args(argv_list)
    except VizError as usage_error:
        return _finish_failure(usage_error, out, err, _peek_format(argv_list))

    if args.protocol_version:
        return _finish_success({"protocol": PROTOCOL_VERSION}, out, err, args.format)

    if args.verb is None:
        return _finish_failure(
            VizError(ErrorCode.USAGE, f"no verb given; choose one of: {', '.join(VERBS)}"),
            out,
            err,
            args.format,
        )

    # argparse's subparser `choices` already rejected any non-None verb that
    # isn't a registered subcommand, so a name reaching here is always in VERBS.
    handler = VERBS[args.verb]

    # Everything from here on — runner construction and the handler call — runs
    # inside one guarded region so an exception anywhere still yields exactly one
    # envelope on stdout (the invariant holds even on internal bugs) rather than
    # escaping with a raw traceback and no envelope.
    try:
        # Constructed only now — never for --protocol-version above — so the
        # handshake never touches any adapter.
        runners = Runners(
            git=git_runner if git_runner is not None else SubprocessGitRunner(),
            gh=gh_runner if gh_runner is not None else SubprocessGhRunner(),
            scc=scc_runner if scc_runner is not None else SubprocessSccRunner(),
        )
        data = handler(runners, args)
    except VizError as verb_error:
        return _finish_failure(verb_error, out, err, args.format)
    except Exception:
        traceback.print_exc(file=err)
        internal = VizError(ErrorCode.INTERNAL, "internal error")
        return _finish_failure(internal, out, err, args.format)
    return _finish_success(data, out, err, args.format)


def entry() -> None:  # pragma: no cover - console-script shim, exercised by verify-entry
    sys.exit(main())
