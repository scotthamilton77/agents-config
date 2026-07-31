"""`executor` CLI -- argparse wiring over the S9T1-D12 pairing table, plus the
one verb that has no row in it.

`main()` is the injectable entry point: argv, stdout/stderr and both ports
arrive as arguments, never a module global, so the whole suite runs with the
ports faked and neither `grind` nor `work` on PATH.

Dispatch is two-way: a verb with a pairing row builds a `Plan` against the fold
and enacts it, and a read-only verb (`next`, S9T1-D10) composes facade reads
and touches neither the runtime nor a plan. The table closes the *mutation*
surface, so a verb that mutates nothing having no row in it is the design.

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
from executor.envelope import ErrorCode, ExecutorError, JsonValue, emit_failure, emit_success
from executor.pairing import (
    ATTEMPT_KINDS,
    FAILURE_REASONS,
    SCHEDULING_REASONS,
    VerbArgs,
    build_plan,
)
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


def _configure_attempt(parser: ArgumentParser) -> None:
    _item(parser)
    parser.add_argument(
        "--kind", required=True, choices=tuple(ATTEMPT_KINDS), help="the fix being attempted"
    )


def _configure_next(parser: ArgumentParser) -> None:
    """`next` names no item -- it is the surface that says which there are.

    `--stale-days` defaults to `None`, which is not the same as defaulting to
    a number: omitted, the flag is left off the facade call and the threshold
    stays the facade's own (S9T1-N4). Restating the number here would give the
    tree a second definition of it.
    """
    parser.add_argument(
        "--stale-days",
        type=int,
        default=None,
        metavar="N",
        help="passed through to the parked report; omitted, the facade's default stands",
    )


# The parser is built FROM this mapping, so the CLI surface and the enumeration
# it is checked against are one list, not two that can drift. Wiring a pending
# verb means adding its entry here and dropping the name from `PENDING_VERBS`.
_VERB_PARSERS: dict[str, tuple[str, Callable[[ArgumentParser], None]]] = {
    "start": ("claim the item and record it started", _configure_start),
    "park": ("park the item with a typed reason", _configure_park),
    "redispatch": ("return a parked item to its lane", _configure_redispatch),
    "abandon": ("return a parked item to its lane, recording its PR's closure", _configure_abandon),
    "pr-opened": ("record that a PR opened for the item", _configure_pr_opened),
    "pr-closed": ("record that the item's PR closed", _configure_pr_closed),
    "merged": ("record the merge and close the tracker item", _configure_merged),
    "done": ("record post-merge teardown as complete", _configure_done),
    "attempt": ("charge one fix attempt against the item's budget", _configure_attempt),
    "next": ("report the parked work and the ready queue, in that order", _configure_next),
}

CLI_VERBS: tuple[str, ...] = tuple(_VERB_PARSERS)


def _next(args: Namespace, tracker: TrackerPort) -> dict[str, JsonValue]:
    """`executor next` -- two facade reads, one envelope, nothing else.

    The parked report is read FIRST and the ready list is read only if it
    succeeds (S9T1-N1/N2). The order is the whole point: a degraded report that
    still handed out new work would invert D10's "reviewing stuck work is the
    price of pulling new work", so a failed parked read propagates and no ready
    list is fetched, let alone reported.

    Both keys are always present -- an empty parked report is an empty list,
    never an absent key (S9T1-N4). Neither read mutates anything, so by
    S9T1-D9 the invocation owes no sync, and no runtime event pairs with a
    command that enacts nothing: the runtime port is not touched at all.
    """
    # Two statements rather than one dict literal, so the order the contract
    # pins is the order a reader sees rather than a property of how Python
    # evaluates a display.
    parked = tracker.parked(stale_days=args.stale_days)
    return {"parked": parked, "ready": tracker.ready()}


# `next` is the whole read-only surface today (S9T1-D10). The mapping is
# explicit rather than a membership test against `READ_ONLY_VERBS` so a second
# read-only verb cannot silently inherit this one's handler; the totality suite
# asserts the two agree.
_READ_ONLY_HANDLERS: dict[str, Callable[[Namespace, TrackerPort], dict[str, JsonValue]]] = {
    "next": _next
}


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
        kind=getattr(args, "kind", None),
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
        resolved_tracker = tracker if tracker is not None else WorkTracker(SubprocessRunner())
        read_only = _READ_ONLY_HANDLERS.get(args.verb)
        if read_only is not None:
            # A read-only verb builds no plan and never reaches the runtime:
            # it has no pairing row to enact, and reading a fold it does not
            # consult would make it fail on a grind that is merely absent.
            data = read_only(args, resolved_tracker)
        else:
            resolved_runtime = (
                runtime
                if runtime is not None
                else GrindRuntime(SubprocessRunner(), grind_dir=args.dir)
            )
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
