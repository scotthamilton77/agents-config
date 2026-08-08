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
from workcli.lifecycle.closewalk import close_walk, walk_payload
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
    """`work update ID [--set-title] [--set-priority] [--set-description] [--set-parent]`.

    Replace semantics only; status never moves through this verb
    (lifecycle verbs own claiming/status). `--set-parent` is the move
    operation: a parent is single-valued, which is exactly the contract this
    verb already declares, and it maps to the seam's atomic reparent — the old
    parent-child edge is replaced, never added beside. `dep add` refuses a
    second parent and names this flag.

    `--set-notes` and `--set-acceptance` are recognized by argparse only so
    they reach this named clobber-guard rather than a generic `E_USAGE`. Notes
    only ever move through `work note`, and the criteria a claim is checked
    against only through `work acceptance set`, which records what they were —
    a replace here would leave neither the history nor the contract. (Both are
    suppressed from `--help`; rationale at their `add_argument` sites in
    `cli.py`.)
    """
    if args.set_notes is not None:
        raise WorkError(
            ErrorCode.FIELD_CLOBBER_GUARD,
            "notes are append-only; use `work note ID TEXT` instead of --set-notes",
        )
    if args.set_acceptance is not None:
        raise WorkError(
            ErrorCode.FIELD_CLOBBER_GUARD,
            "acceptance criteria are the contract a claim is checked against; use "
            "`work acceptance set ID TEXT` instead of --set-acceptance, which records "
            "the criteria it supersedes",
        )
    if args.set_parent is not None and not args.set_parent:
        # An empty parent reads as "remove the parent" at the backend, and an
        # unset shell variable expands to exactly that. Orphaning an item is
        # not what anyone typing a move means, and this verb replaces a value
        # with a value; detaching a parent is deliberately unexpressible here.
        raise WorkError(
            ErrorCode.USAGE,
            "--set-parent requires an item id; it moves an item, it cannot detach one",
            detail={"field": "parent"},
        )
    if (
        args.set_title is None
        and args.set_priority is None
        and args.set_description is None
        and args.set_parent is None
    ):
        raise WorkError(ErrorCode.USAGE, "update requires at least one --set-* flag")
    fields = UpdateFields(
        title=args.set_title,
        priority=args.set_priority,
        description=args.set_description,
        parent=args.set_parent,
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

    One batched `Backend.close` for all ids first, then one `append_note` per
    id carrying the disposition text (orchestrator ruling: the backend's own
    close-reason field is the wrong home; the disposition is an appended
    note), then the close-walk: exhausted parents close with a walk note, and
    exhausted parents carrying scope of their own are reported held. The ids
    named here are closed unconditionally -- the walk's rules govern what it
    infers, not what the caller states. `data` stays None when the walk had
    nothing to report (legacy envelope shape).
    """
    backend.close(args.ids)
    if args.disposition is not None:
        for item_id in args.ids:
            backend.append_note(item_id, args.disposition)
    payload = walk_payload(close_walk(backend, list(args.ids)))
    return payload or None


def reopen(backend: Backend, args: Namespace) -> JsonValue:
    """`work reopen ID`."""
    backend.reopen(args.id)
    return None
