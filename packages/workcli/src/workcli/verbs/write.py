"""create --raw, update, note, close, reopen — the write verbs.

Pure functions over a `Backend`: same shape as `verbs/read.py` (no
subprocess, no I/O beyond the injected seam). `cli.py` wraps the return
value in the envelope and translates a raised `WorkError` into a failure
envelope.
"""

from __future__ import annotations

from argparse import Namespace
from typing import cast

from workcli.backend import Backend
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.lifecycle.closewalk import close_walk
from workcli.model import CreateFields, UpdateFields


def create_raw(backend: Backend, args: Namespace) -> JsonValue:
    """`work create --raw --title T [...]` — the adapter primitive.

    Public, noun-templated creation belongs to the lifecycle layer; `--raw`
    gates this transport-layer passthrough so a caller can never reach it by
    accident.
    """
    if not args.raw:
        raise WorkError(
            ErrorCode.USAGE,
            "work create requires --raw; noun-templated creation belongs to "
            "the lifecycle layer (work create <noun>), not this transport verb",
        )
    fields = CreateFields(
        title=args.title,
        description=args.description,
        type=args.type,
        priority=args.priority,
        parent=args.parent,
        labels=tuple(args.label),
    )
    new_id = backend.create(fields)
    return {"id": new_id}


def update(backend: Backend, args: Namespace) -> JsonValue:
    """`work update ID [--set-title] [--set-priority] [--set-description]`.

    Replace semantics only; status never moves through this verb
    (lifecycle verbs own claiming/status). `--set-notes` is recognized by
    argparse only so it reaches this named clobber-guard rather than a
    generic `E_USAGE` — notes only ever move through
    `work note`. (Suppressed from `--help`; rationale at its
    `add_argument` site in `cli.py`.)
    """
    if args.set_notes is not None:
        raise WorkError(
            ErrorCode.FIELD_CLOBBER_GUARD,
            "notes are append-only; use `work note ID TEXT` instead of --set-notes",
        )
    if args.set_title is None and args.set_priority is None and args.set_description is None:
        raise WorkError(ErrorCode.USAGE, "update requires at least one --set-* flag")
    fields = UpdateFields(
        title=args.set_title,
        priority=args.set_priority,
        description=args.set_description,
    )
    backend.set_fields(args.id, fields)
    return None


def note(backend: Backend, args: Namespace) -> JsonValue:
    """`work note ID TEXT` — append-only."""
    backend.append_note(args.id, args.text)
    return None


def close(backend: Backend, args: Namespace) -> JsonValue:
    """`work close IDS... [--disposition TEXT]` -- close + close-walk + note,
    one call.

    Batch `bd close` for all ids first, then one `--append-notes` call per
    id carrying the disposition text (orchestrator ruling: `bd close
    --reason` lands in the wrong field; the disposition is an appended note),
    then the close-walk: exhausted non-milestone parents close with a walk
    note. `data` stays None when nothing walked (legacy envelope shape).
    """
    backend.close(args.ids)
    if args.disposition is not None:
        for item_id in args.ids:
            backend.append_note(item_id, args.disposition)
    walked = close_walk(backend, list(args.ids))
    if walked:
        return {"walked": cast("list[JsonValue]", list(walked))}
    return None


def reopen(backend: Backend, args: Namespace) -> JsonValue:
    """`work reopen ID`."""
    backend.reopen(args.id)
    return None
