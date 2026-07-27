"""`executor` CLI -- argparse wiring over the S9T1-D12 pairing table.

`main()` is the injectable entry point: argv, stdout/stderr and both ports
arrive as arguments, never a module global, so the whole suite runs with the
ports faked and neither `grind` nor `work` on PATH.

The contract, since this docstring is what the package's other artifacts point
at:

- Every invocation emits exactly one protocol-versioned JSON envelope on
  stdout, failures included. A parse failure is enveloped too (see
  `_RaisingArgumentParser`), and an unexpected exception is caught and typed --
  a traceback is never the answer.
- Exit 0 on success, 1 on any typed failure.
- `--help` is the one path that emits no envelope: argparse raises `SystemExit`
  and nothing here catches it, so `executor --help` prints plain usage.
"""

from __future__ import annotations

import sys
import traceback
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence
from typing import NoReturn, TextIO

from executor.enact import enact
from executor.envelope import ErrorCode, ExecutorError, emit_failure, emit_success
from executor.pairing import FAILURE_REASONS, SCHEDULING_REASONS, VerbArgs, build_plan
from executor.ports import GrindRuntime, RuntimePort, SubprocessRunner, TrackerPort, WorkTracker

# `pr_closed.next` is the runtime's own vocabulary; the parser refuses anything
# else rather than letting the runtime record an anomaly for it.
_PR_CLOSED_NEXT = ("in-progress", "queued", "parked")
_PARK_REASONS_HELP = "|".join((*FAILURE_REASONS, *SCHEDULING_REASONS))


class _RaisingArgumentParser(ArgumentParser):
    """Raises instead of printing usage and exiting, so a bad flag or an
    unknown verb still leaves exactly one JSON envelope on stdout."""

    def error(self, message: str) -> NoReturn:
        raise ExecutorError(ErrorCode.USAGE, message)


def _item(parser: ArgumentParser) -> None:
    parser.add_argument("item", metavar="ID", help="the runtime's item id")


def _configure_start(parser: ArgumentParser) -> None:
    _item(parser)


def _configure_park(parser: ArgumentParser) -> None:
    _item(parser)
    parser.add_argument("--reason", required=True, metavar="CODE", help=_PARK_REASONS_HELP)
    parser.add_argument("--note", metavar="TEXT", help="defaults to the reason code")


def _configure_redispatch(parser: ArgumentParser) -> None:
    _item(parser)


def _configure_abandon(parser: ArgumentParser) -> None:
    _item(parser)
    parser.add_argument("--pr", required=True, type=int, metavar="N")
    parser.add_argument(
        "--reason", metavar="TEXT", help="the closure note; defaults to 'abandoned'"
    )


def _configure_pr_opened(parser: ArgumentParser) -> None:
    _item(parser)
    parser.add_argument("--pr", required=True, type=int, metavar="N")


def _configure_pr_closed(parser: ArgumentParser) -> None:
    _item(parser)
    parser.add_argument("--pr", required=True, type=int, metavar="N")
    parser.add_argument("--next", required=True, dest="next_status", choices=_PR_CLOSED_NEXT)
    parser.add_argument("--reason", required=True, metavar="TEXT")


def _configure_merged(parser: ArgumentParser) -> None:
    _item(parser)
    parser.add_argument("--sha", required=True, metavar="SHA")


def _configure_done(parser: ArgumentParser) -> None:
    _item(parser)


# The parser is built FROM this mapping, so the CLI surface and the enumeration
# it is checked against are one list, not two that can drift. A slice that
# wires `attempt` or `next` adds its entry here and drops the name from
# `PENDING_VERBS`.
_VERB_PARSERS: dict[str, tuple[str, Callable[[ArgumentParser], None]]] = {
    "start": ("claim the item and record it started", _configure_start),
    "park": ("park the item with a typed reason", _configure_park),
    "redispatch": ("return a parked item to its lane", _configure_redispatch),
    "abandon": ("return a parked item to its lane, recording its PR's closure", _configure_abandon),
    "pr-opened": ("record that a PR opened for the item", _configure_pr_opened),
    "pr-closed": ("record that the item's PR closed", _configure_pr_closed),
    "merged": ("record the merge and close the tracker item", _configure_merged),
    "done": ("record post-merge teardown as complete", _configure_done),
}

CLI_VERBS: tuple[str, ...] = tuple(_VERB_PARSERS)


def _build_parser() -> _RaisingArgumentParser:
    parser = _RaisingArgumentParser(
        prog="executor", description="executor — pair runtime events with tracker verbs"
    )
    parser.add_argument(
        "--dir",
        default=None,
        metavar="DIR",
        help="the grind directory; omitted, the runtime resolves it itself",
    )
    subparsers = parser.add_subparsers(dest="verb", parser_class=_RaisingArgumentParser)
    for verb, (help_text, configure) in _VERB_PARSERS.items():
        configure(subparsers.add_parser(verb, help=help_text))
    return parser


def _verb_args(args: Namespace) -> VerbArgs:
    return VerbArgs(
        item=args.item,
        reason=getattr(args, "reason", None),
        note=getattr(args, "note", None),
        pr=getattr(args, "pr", None),
        sha=getattr(args, "sha", None),
        next_status=getattr(args, "next_status", None),
    )


def _require_verb(args: Namespace) -> None:
    if args.verb is None:
        raise ExecutorError(
            ErrorCode.USAGE, "no verb given; choose one of: " + ", ".join(CLI_VERBS)
        )


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
    runtime: RuntimePort | None = None,
    tracker: TrackerPort | None = None,
) -> int:
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    try:
        args = _build_parser().parse_args(list(argv) if argv is not None else None)
        _require_verb(args)
        resolved_runtime = (
            runtime if runtime is not None else GrindRuntime(SubprocessRunner(), grind_dir=args.dir)
        )
        resolved_tracker = tracker if tracker is not None else WorkTracker(SubprocessRunner())
        plan = build_plan(args.verb, _verb_args(args), resolved_runtime.state())
        data = enact(plan, resolved_runtime, resolved_tracker)
    except ExecutorError as failure:
        return emit_failure(failure, out)
    except Exception:  # every path still yields one envelope, never a traceback
        traceback.print_exc(file=err)
        return emit_failure(ExecutorError(ErrorCode.INTERNAL, "internal error"), out)
    return emit_success(data, out)


def entry() -> None:
    sys.exit(main())
