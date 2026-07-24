"""workcli CLI — argparse wiring, protocol handshake, and the dispatch loop.

`main()` is the single injectable entry point: every outside-world dependency
(argv, the bd runner, stdout/stderr, sleep) arrives as an argument, never a
module global. The `Backend` itself is constructed lazily, inside `main()`,
only when a verb actually dispatches -- `--protocol-version` short-circuits
before it and never touches the runner: the handshake is cheap and
side-effect-free.
"""

from __future__ import annotations

import sys
import time
import traceback
from argparse import SUPPRESS, ArgumentParser, _SubParsersAction
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn, TextIO

from workcli import PROTOCOL_VERSION
from workcli.adapters.bd.backend import BdBackend
from workcli.adapters.bd.runner import BdRunner, SubprocessBdRunner
from workcli.config import TrackLayerConfig, load_config
from workcli.envelope import ErrorCode, JsonValue, WorkError, emit_failure, emit_success
from workcli.lifecycle.nouns import LEAF_NOUNS, Noun
from workcli.render import render_human
from workcli.verbs import VERBS, missing_capability


class _EnvelopeArgumentParser(ArgumentParser):
    """Raises on a parse failure instead of printing usage and calling `sys.exit`.

    Default argparse behavior on error prints a usage block to stderr and
    exits — that would violate the "stdout is always exactly one JSON
    envelope" invariant. Raising lets `main()` convert the failure into an
    `E_USAGE` envelope instead.
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
    list_parser.add_argument("--track", metavar="NAME")

    ready_parser = subparsers.add_parser("ready", help="list ready-to-work items, unbounded")
    ready_parser.add_argument("--label")

    search_parser = subparsers.add_parser("search", help="search items by query text")
    search_parser.add_argument("query", metavar="QUERY")


def _add_write_subparsers(subparsers: _SubParsersAction[_EnvelopeArgumentParser]) -> None:
    create_parser = subparsers.add_parser(
        "create",
        help="create --raw (adapter primitive) or create NOUN (lifecycle layer)",
    )
    create_parser.add_argument(
        "noun",
        nargs="?",
        choices=[noun.value for noun in Noun],
        metavar="NOUN",
        help="spike|chore|decision|feat|bugfix|spec|epic|milestone -- omit with --raw",
    )
    create_parser.add_argument("--raw", action="store_true")
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--description")
    create_parser.add_argument("--type")
    create_parser.add_argument("--priority")
    create_parser.add_argument("--parent")
    create_parser.add_argument("--label", action="append", default=[], metavar="LABEL")
    create_parser.add_argument("--orphan", action="store_true")
    create_parser.add_argument("--spec")
    create_parser.add_argument("--trivial", action="store_true")
    create_parser.add_argument("--acceptance")
    create_parser.add_argument("--track", metavar="NAME")

    update_parser = subparsers.add_parser(
        "update", help="update title/priority/description (replace semantics only)"
    )
    update_parser.add_argument("id", metavar="ID")
    update_parser.add_argument("--set-title")
    update_parser.add_argument("--set-priority")
    update_parser.add_argument("--set-description")
    # Recognized only so it reaches the named E_FIELD_CLOBBER_GUARD instead
    # of a generic E_USAGE unknown-flag error -- notes are append-only.
    # help=SUPPRESS hides it from --help entirely: it's a tripwire, not an
    # advertised option, so it never invites the attempt it then rejects.
    update_parser.add_argument("--set-notes", help=SUPPRESS)

    note_parser = subparsers.add_parser("note", help="append a note (append-only)")
    note_parser.add_argument("id", metavar="ID")
    note_parser.add_argument("text", metavar="TEXT")

    close_parser = subparsers.add_parser("close", help="close one or more items")
    close_parser.add_argument("ids", nargs="+", metavar="IDS")
    close_parser.add_argument("--disposition")

    reopen_parser = subparsers.add_parser("reopen", help="reopen a closed item")
    reopen_parser.add_argument("id", metavar="ID")


def _add_transition_subparsers(subparsers: _SubParsersAction[_EnvelopeArgumentParser]) -> None:
    claim_parser = subparsers.add_parser("claim", help="claim a ready, unclaimed leaf")
    claim_parser.add_argument("id", metavar="ID")

    release_parser = subparsers.add_parser("release", help="release a claimed item back to open")
    release_parser.add_argument("id", metavar="ID")

    park_parser = subparsers.add_parser(
        "park", help="park a non-merging item with a typed reason; the machine disengages"
    )
    park_parser.add_argument("id", metavar="ID")
    park_parser.add_argument(
        "--reason",
        required=True,
        metavar="CODE",
        help="ci-failure|merge-conflict|approval-required|bot-declined|budget-exhausted",
    )
    park_parser.add_argument("--note", metavar="TEXT")

    redispatch_parser = subparsers.add_parser(
        "redispatch", help="un-park an item whose cause is fixed; back to ready"
    )
    redispatch_parser.add_argument("id", metavar="ID")

    abandon_parser = subparsers.add_parser(
        "abandon", help="un-park an item whose PR is closed; back to ready"
    )
    abandon_parser.add_argument("id", metavar="ID")

    plan_parser = subparsers.add_parser("plan", help="add/remove an item from the Planning queue")
    plan_parser.add_argument("id", metavar="ID")
    plan_parser.add_argument("--done", action="store_true")
    plan_parser.add_argument("--undo", action="store_true")
    plan_parser.add_argument("--force", action="store_true")

    promote_parser = subparsers.add_parser(
        "promote", help="promote a shape-feat leaf to a shape-spec container"
    )
    promote_parser.add_argument("id", metavar="ID")

    deliver_parser = subparsers.add_parser(
        "deliver",
        help="deliver a leaf (evidence-gated) or reconcile a design child's placeholder",
    )
    deliver_parser.add_argument("id", metavar="ID")
    deliver_parser.add_argument("--spec")
    deliver_parser.add_argument("--pr")
    deliver_parser.add_argument("--items")
    deliver_parser.add_argument("--trivial", action="store_true")

    reconcile_parser = subparsers.add_parser(
        "reconcile", help="sweep bd-observable recoverable states"
    )
    reconcile_parser.add_argument("--dry-run", action="store_true")


def _add_discover_subparser(subparsers: _SubParsersAction[_EnvelopeArgumentParser]) -> None:
    discover_parser = subparsers.add_parser(
        "discover", help="file a discovered-work item with a mechanically-enforced triage record"
    )
    discover_parser.add_argument(
        "--noun",
        required=True,
        choices=[noun.value for noun in LEAF_NOUNS],
        help="spike|chore|decision|feat|bugfix -- leaf nouns only, a discovery is not a container",
    )
    discover_parser.add_argument("--title", required=True)
    discover_parser.add_argument("--description")
    discover_parser.add_argument("--anchor")
    discover_parser.add_argument("--orphan", action="store_true")
    discover_parser.add_argument("--discovered-from", dest="discovered_from")
    discover_parser.add_argument("--scope")
    discover_parser.add_argument("--scope-why", dest="scope_why")
    discover_parser.add_argument("--priority")
    discover_parser.add_argument("--priority-why", dest="priority_why")
    discover_parser.add_argument("--anchor-why", dest="anchor_why")
    discover_parser.add_argument("--escalation-why", dest="escalation_why")
    discover_parser.add_argument("--track", metavar="NAME")


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


def _add_track_subparsers(subparsers: _SubParsersAction[_EnvelopeArgumentParser]) -> None:
    track_parser = subparsers.add_parser(
        "track", help="track assignment: track set ID NAME [--cascade]"
    )
    track_parser.add_argument("action", choices=["set"])
    track_parser.add_argument("id", metavar="ID")
    track_parser.add_argument("name", metavar="NAME")
    track_parser.add_argument("--cascade", action="store_true")


def _add_report_subparsers(subparsers: _SubParsersAction[_EnvelopeArgumentParser]) -> None:
    subparsers.add_parser("lint", help="track/milestone hygiene report (advisory; always exits 0)")
    graph_parser = subparsers.add_parser(
        "graph", help="bulk node/edge export for visualization consumers"
    )
    graph_parser.add_argument("--json", action="store_true", dest="json_output")
    subparsers.add_parser("triggers", help="extraction pressure/eligibility per track (advisory)")

    parked_parser = subparsers.add_parser(
        "parked", help="read-only parked-item staleness report (reports, never acts)"
    )
    parked_parser.add_argument("--stale-days", type=int, default=7, dest="stale_days")

    groom_parser = subparsers.add_parser(
        "groom", help="Backlog Grooming state: --done records completion, --status reports nag"
    )
    groom_group = groom_parser.add_mutually_exclusive_group(required=True)
    groom_group.add_argument("--done", action="store_true")
    groom_group.add_argument("--status", action="store_true")


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
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="explicit project-config.toml path; overrides the upward search",
    )
    # `parser_class` propagates the raise-don't-exit `error()` override to
    # every subparser too -- a bad flag inside `work show --bogus` must reach
    # main()'s WorkError handling exactly like a bad top-level flag does,
    # never argparse's own stderr-and-exit path.
    subparsers = parser.add_subparsers(dest="verb", parser_class=_EnvelopeArgumentParser)
    _add_read_subparsers(subparsers)
    _add_write_subparsers(subparsers)
    _add_transition_subparsers(subparsers)
    _add_discover_subparser(subparsers)
    _add_relations_subparsers(subparsers)
    _add_track_subparsers(subparsers)
    _add_report_subparsers(subparsers)
    _add_sync_subparser(subparsers)
    return parser


def _peek_format(argv: list[str] | None) -> str:
    """Best-effort recovery of `--format` when full parsing has already failed.

    `parse_args()` can raise (bad flag, unknown verb) before we learn whether
    `--format human` was requested, yet the human view still renders to
    stderr alongside the stdout envelope even on usage errors. A
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

    stdout always carries the envelope regardless of `fmt` -- this never
    replaces `emit_success`, only adds the human view alongside it.
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


def _default_read_file(path: str) -> str:
    """Read `path` as UTF-8, typing the two expected boundary failures.

    The default `--spec`/manifest reader `main()` installs when no `read_file`
    is injected. A raw `Path.read_text` here would let a missing/unreadable
    path or a non-UTF-8 file escape as a bare `OSError`/`UnicodeDecodeError`
    that main()'s catch-all reports as an opaque `E_INTERNAL` "internal error";
    both are *expected* input failures, so they belong in the type as typed
    envelopes instead: a bad `--spec` path is user error (`E_USAGE`), an
    undecodable spec is a malformed manifest input (`E_MANIFEST`). Injected
    `read_file` fakes bypass this helper entirely, so the seam stays
    test-injectable unchanged.
    """
    try:
        return Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError as decode_error:
        raise WorkError(
            ErrorCode.MANIFEST,
            f"spec file is not valid UTF-8: {path}",
            {"path": path},
        ) from decode_error
    except OSError as read_error:
        raise WorkError(
            ErrorCode.USAGE,
            f"cannot read spec file {path}: {read_error.strerror or read_error}",
            {"path": path},
        ) from read_error


def _default_config_loader(explicit_path: str | None) -> TrackLayerConfig:
    """The real track-layer config resolution: upward search from cwd."""
    return load_config(Path.cwd(), explicit_path)


def _default_now() -> datetime:
    """The real wall clock: `work groom`'s only source of "now" (never a bare
    `datetime.now()` call anywhere in the verb layer -- injected for testability,
    same seam precedent as `read_file`/`config_loader`)."""
    return datetime.now(UTC)


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
    read_file: Callable[[str], str] | None = None,
    config_loader: Callable[[str | None], TrackLayerConfig] | None = None,
    now: Callable[[], datetime] | None = None,
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

    # Resolved once here and attached to the parsed Namespace -- only
    # `deliver` reads it, but every handler keeps the transport's
    # `(Backend, Namespace) -> JsonValue` signature, so this travels as an
    # `args` attribute rather than an extra handler parameter.
    args.read_file = read_file if read_file is not None else _default_read_file

    # Same args-attachment precedent as read_file: resolved once, loaded
    # LAZILY -- only a track-layer surface calls args.load_config(), so
    # pre-existing verbs never trigger config resolution.
    resolved_config_loader = config_loader if config_loader is not None else _default_config_loader
    args.load_config = lambda: resolved_config_loader(args.config)

    # Same args-attachment precedent as read_file -- but attached
    # unconditionally, not lazily: reading the clock has no I/O cost, so
    # there is no laziness contract to preserve (unlike config_loader, which
    # stays lazy so pre-existing verbs never trigger config resolution).
    args.now = now if now is not None else _default_now

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
    # stdout (the invariant holds even on internal bugs; see the
    # `E_INTERNAL` note) rather than escaping with a raw traceback and no
    # envelope at all.
    try:
        # Constructed only now -- never for --protocol-version above -- so the
        # handshake never touches the runner.
        backend = _build_backend(runner, sleep)

        if missing_capability(args.verb, backend.capabilities, args):
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
