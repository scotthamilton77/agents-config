"""create --raw, update, note, close, reopen — the write verbs.

Pure functions over a `Backend`: same shape as `verbs/read.py` (no
subprocess, no I/O beyond the injected seam). `cli.py` wraps the return
value in the envelope and translates a raised `WorkError` into a failure
envelope.
"""

from __future__ import annotations

from argparse import Namespace

from workcli.backend import Backend
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.model import CreateFields, UpdateFields


def create_raw(backend: Backend, args: Namespace) -> JsonValue:
    """`work create --raw --title T [...]` — the adapter primitive (spec §2).

    Public, noun-templated creation belongs to the lifecycle layer (bead
    .9.2); `--raw` gates this transport-layer passthrough so a caller can
    never reach it by accident (locked decision 7).
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

    Replace semantics only (spec §3); status never moves through this verb
    (lifecycle verbs own claiming/status). `--set-notes` is recognized by
    argparse only so it reaches this named clobber-guard rather than a
    generic `E_USAGE` (locked decision 6) — notes only ever move through
    `work note`. It is also suppressed from `--help` output (`cli.py`):
    a hidden tripwire, not an advertised option.
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
    """`work note ID TEXT` — append-only (spec §3; PDLC `append_audit_note`)."""
    backend.append_note(args.id, args.text)
    return None


def close(backend: Backend, args: Namespace) -> JsonValue:
    """`work close IDS... [--disposition TEXT]`.

    Batch `bd close` for all ids first, then one `--append-notes` call per
    id carrying the disposition text (orchestrator ruling: `bd close
    --reason` lands in the wrong field; the disposition is an appended note).
    """
    backend.close(args.ids)
    if args.disposition is not None:
        for item_id in args.ids:
            backend.append_note(item_id, args.disposition)
    return None


def reopen(backend: Backend, args: Namespace) -> JsonValue:
    """`work reopen ID`."""
    backend.reopen(args.id)
    return None
