"""`grind` CLI -- argparse wiring and the dispatch loop over `grind.verbs`.

`main()` is the single injectable entry point: argv, stdout/stderr, the wall
clock, the seed-file reader, the working directory, and the environment all
arrive as arguments, never a module global (same seam precedent as workcli's
`cli.py`). Every command emits exactly one JSON envelope on stdout and exits 0
unless the command itself failed (spec CLI contract: "exit code 0 unless the
command itself failed -- an anomalous event still exits 0, it was recorded").
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn, TextIO

from grind.envelope import GrindError
from grind.jsonio import NonFiniteJsonError, loads
from grind.model import JsonValue
from grind.resolve import GRIND_DIR_ENV, resolve_existing, resolve_for_create
from grind.verbs import cmd_check, cmd_create, cmd_finish, cmd_log, cmd_render, cmd_status


class _RaisingArgumentParser(ArgumentParser):
    """Raises `GrindError` on a parse failure instead of printing usage and
    calling `sys.exit` -- keeps the "stdout is always exactly one JSON
    envelope" invariant on a bad flag or unknown verb (same precedent as
    workcli's `_EnvelopeArgumentParser`)."""

    def error(self, message: str) -> NoReturn:
        raise GrindError(message)


def _add_dir_flag(parser: ArgumentParser) -> None:
    """`--dir` with **no default** -- omission must stay distinguishable from an
    explicit `--dir .`, since `grind.resolve` gives the two different meanings."""
    parser.add_argument(
        "--dir",
        default=None,
        metavar="DIR",
        help=f"the grind directory; falls back to ${GRIND_DIR_ENV}, "
        "then to the nearest grind at or above the current directory",
    )


def _build_parser() -> _RaisingArgumentParser:
    parser = _RaisingArgumentParser(
        prog="grind", description="grind — event-sourced grind runtime CLI"
    )
    subparsers = parser.add_subparsers(dest="verb", parser_class=_RaisingArgumentParser)

    create_parser = subparsers.add_parser("create", help="seed a new grind from a seed file")
    create_parser.add_argument("--file", required=True, metavar="PATH")
    _add_dir_flag(create_parser)

    log_parser = subparsers.add_parser("log", help="append a typed event and refold")
    log_parser.add_argument("type", metavar="TYPE")
    log_parser.add_argument("--json", required=True, dest="payload_json", metavar="JSON")
    _add_dir_flag(log_parser)

    status_parser = subparsers.add_parser("status", help="report the folded state")
    # Alternative projections of one fold, so the parser refuses the
    # combination outright rather than silently picking a winner.
    status_view = status_parser.add_mutually_exclusive_group()
    status_view.add_argument(
        "--full", action="store_const", const="full", dest="view", help="the entire folded state"
    )
    status_view.add_argument(
        "--handoff",
        action="store_const",
        const="handoff",
        dest="view",
        help="the re-orientation projection a contextless session resumes from",
    )
    status_parser.set_defaults(view="summary")
    _add_dir_flag(status_parser)

    check_parser = subparsers.add_parser("check", help="staleness probe (exits 1 when stale)")
    check_parser.add_argument("--max-age", default=None, dest="max_age", metavar="DUR")
    _add_dir_flag(check_parser)

    render_parser = subparsers.add_parser("render", help="refold and re-render dashboard.html only")
    _add_dir_flag(render_parser)

    finish_parser = subparsers.add_parser("finish", help="append grind_finished and final-fold")
    finish_parser.add_argument("--summary", required=True, metavar="TEXT")
    _add_dir_flag(finish_parser)

    return parser


def _read_seed_file(path: str, read_file: Callable[[str], str]) -> JsonValue:
    try:
        text = read_file(path)
    except OSError as read_error:
        raise GrindError(f"cannot read seed file {path}: {read_error}") from read_error
    try:
        return loads(text)
    except (json.JSONDecodeError, NonFiniteJsonError) as decode_error:
        raise GrindError(f"seed file {path} is not valid JSON: {decode_error}") from decode_error


def _parse_json_payload(raw: str) -> JsonValue:
    try:
        return loads(raw)
    except (json.JSONDecodeError, NonFiniteJsonError) as decode_error:
        raise GrindError(f"--json is not valid JSON: {decode_error}") from decode_error


def _dispatch(
    args: Namespace,
    now: Callable[[], datetime],
    read_file: Callable[[str], str],
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> JsonValue:
    # The verb check comes first: with no verb the namespace carries no `--dir`
    # at all, so resolving a directory up front would raise AttributeError and
    # surface as an "internal error" envelope instead of this usage message.
    if args.verb is None:
        raise GrindError("no verb given; choose one of: create, log, status, render, check, finish")

    if args.verb == "create":
        seed = _read_seed_file(args.file, read_file)
        if not isinstance(seed, dict):
            raise GrindError(f"seed file {args.file} must contain a JSON object")
        return cmd_create(resolve_for_create(args.dir, cwd=cwd, env=env).path, seed, now=now)

    # Every remaining verb reads or appends to an existing grind, so an
    # empty-state directory is a command error, never a quietly empty answer.
    grind_dir = resolve_existing(args.dir, cwd=cwd, env=env).path

    if args.verb == "log":
        payload = _parse_json_payload(args.payload_json)
        if not isinstance(payload, dict):
            raise GrindError("--json must contain a JSON object")
        return cmd_log(grind_dir, args.type, payload, now=now)

    if args.verb == "status":
        return cmd_status(grind_dir, view=args.view, now=now)

    if args.verb == "check":
        return cmd_check(grind_dir, args.max_age, now=now)
    if args.verb == "render":
        return cmd_render(grind_dir)

    # `finish` by elimination: argparse rejects any verb outside the six, and
    # the no-verb case was handled above, so nothing else can reach here.
    return cmd_finish(grind_dir, args.summary, now=now)


def _default_now() -> datetime:
    return datetime.now(UTC)


def _default_read_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
    now: Callable[[], datetime] | None = None,
    read_file: Callable[[str], str] | None = None,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    if out is None:
        out = sys.stdout
    if err is None:
        err = sys.stderr
    resolved_now = now if now is not None else _default_now
    resolved_read_file = read_file if read_file is not None else _default_read_file
    resolved_cwd = cwd if cwd is not None else Path.cwd()
    resolved_env: Mapping[str, str] = env if env is not None else os.environ

    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        data = _dispatch(args, resolved_now, resolved_read_file, cwd=resolved_cwd, env=resolved_env)
    except GrindError as command_error:
        json.dump({"ok": False, "error": {"message": command_error.message}}, out)
        out.write("\n")
        return 1
    except Exception:  # every path still yields exactly one envelope, never a bare traceback
        traceback.print_exc(file=err)
        json.dump({"ok": False, "error": {"message": "internal error"}}, out)
        out.write("\n")
        return 1

    json.dump(data, out, allow_nan=False)
    out.write("\n")
    # `grind check`'s exit code carries the staleness verdict itself (spec CLI
    # contract: "exit 1 when stale"), distinct from every other verb where exit
    # code only ever signals a command error (an `ok: true` envelope is always 0).
    if args.verb == "check" and isinstance(data, dict) and data.get("stale") is True:
        return 1
    return 0


def entry() -> None:
    sys.exit(main())
