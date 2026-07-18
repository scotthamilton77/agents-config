"""`work discover` -- mechanical enforcement of discovered-work triage form.

Implements the 2026-07-17 design spec: refuses to file a discovery without an
anchor (or an explicit `--orphan` escalation) and a complete, well-formed
triage record (Scope / Priority / Anchor), then mints the bead through the
existing `create <noun>` path -- inheriting its noun template, duplicate
guard, and track gate -- adds the `discovered-from` provenance edge, and
returns the completion-report manifest row as a structured envelope field.
The verb enforces *form*; scope correctness stays caller judgment (spec §5).

Composes over `create_noun` (lifecycle/create.py) and adds no new minting
logic (spec §4 step 4): noun->type/shape templating, the duplicate-title
guard, placement validation, and track resolution all execute unchanged.
"""

from __future__ import annotations

import re
from argparse import Namespace
from typing import cast

from workcli.backend import Backend
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.lifecycle import is_container
from workcli.lifecycle.create import create_noun
from workcli.model import Item
from workcli.tracks import derive_track

_HATCHES = ("externally-blocked", "blast-radius", "own-cycle")
_PRIORITY_RE = re.compile(r"^P[0-4]$")
_DISCOVERED_FROM_TYPE = "discovered-from"
_ORPHAN_ANCHOR_DISPLAY = "none: escalated"


def _triage_incomplete(field: str, message: str) -> WorkError:
    return WorkError(ErrorCode.TRIAGE_INCOMPLETE, message, detail={"field": field})


def _require_rationale(value: str | None, field: str, flag: str) -> str:
    """The rationale-shape rule (spec §3.2): required, non-blank after strip, single-line."""
    if value is None:
        raise _triage_incomplete(field, f"{flag} is required")
    stripped = value.strip()
    if not stripped or "\n" in stripped or "\r" in stripped:
        raise _triage_incomplete(field, f"{flag} must be a non-blank, single-line rationale")
    return stripped


def _validate_placement_usage(args: Namespace) -> None:
    has_anchor = args.anchor is not None
    if has_anchor == args.orphan:
        raise WorkError(
            ErrorCode.USAGE, "discover: exactly one of --anchor or --orphan is required"
        )


def _parse_scope(value: str | None) -> tuple[str, str | None]:
    if value is None:
        raise _triage_incomplete("scope", "--scope is required")
    if value == "out-of-scope":
        return "out-of-scope", None
    if value.startswith("in-scope-deferred:"):
        hatch = value[len("in-scope-deferred:") :]
        if hatch in _HATCHES:
            return "in-scope-deferred", hatch
        raise _triage_incomplete(
            "scope",
            f"scope {value!r} has an unknown hatch; use one of {', '.join(_HATCHES)}",
        )
    raise _triage_incomplete(
        "scope",
        f"scope must be 'out-of-scope' or 'in-scope-deferred:HATCH', got {value!r}",
    )


def _validate_priority(value: str | None) -> str:
    if value is None:
        raise _triage_incomplete("priority", "--priority is required")
    if not _PRIORITY_RE.match(value):
        raise _triage_incomplete("priority", f"priority must be one of P0-P4, got {value!r}")
    return value


def _resolve_source(backend: Backend, discovered_from: str | None) -> Item:
    if discovered_from is None:
        raise _triage_incomplete("discovered_from", "--discovered-from is required")
    try:
        return backend.get(discovered_from)
    except WorkError as not_found:
        if not_found.code is not ErrorCode.NOT_FOUND:
            raise
        raise WorkError(
            ErrorCode.NOT_FOUND,
            f"--discovered-from names a nonexistent item: {discovered_from}",
            detail={"field": "discovered_from", "id": discovered_from},
        ) from not_found


def _validate_anchor(
    backend: Backend, anchor: str, scope: str, source: Item, source_id: str
) -> None:
    """Scope-dependent anchor validity (spec §3.4). Only called when `--anchor` is given."""
    if scope == "out-of-scope":
        target = backend.get(anchor)
        if not is_container(target):
            raise _triage_incomplete(
                "anchor",
                "out-of-scope work must anchor under a container (epic or milestone); "
                f"{anchor} is not a container",
            )
        return

    # in-scope-deferred: the anchor must be the exact parent of the resolved source.
    if source.parent is None:
        raise _triage_incomplete(
            "anchor",
            "the resolved --discovered-from item has no parent, so there is no sibling "
            "anchor to derive; file this out-of-scope under an epic/milestone instead",
        )
    if anchor == source_id:
        raise _triage_incomplete(
            "anchor",
            f"--anchor {anchor} is the --discovered-from item itself (the "
            "close-walk-unsafe child-of-in-flight shape); use its parent "
            f"{source.parent} instead",
        )
    if anchor != source.parent:
        raise _triage_incomplete(
            "anchor",
            "in-scope-deferred filings must anchor at the parent of --discovered-from "
            f"({source.parent}), the sibling-of-in-flight placement -- got {anchor}",
        )


def _scope_display(scope: str, hatch: str | None) -> str:
    if scope == "out-of-scope":
        return "out-of-scope"
    return f"in-scope — deferred: {hatch}"


def _render_description(
    args: Namespace,
    scope: str,
    hatch: str | None,
    scope_why: str,
    priority_why: str,
    placement_why: str,
) -> str:
    if scope == "out-of-scope":
        scope_line = f"Scope: out-of-scope — {scope_why}"
    else:
        scope_line = f"Scope: in-scope — deferred: {hatch} — {scope_why}"
    anchor_display = args.anchor if args.anchor is not None else _ORPHAN_ANCHOR_DISPLAY
    block = "\n".join(
        [
            "## Triage",
            f"- {scope_line}",
            f"- Priority: {args.priority} — {priority_why}",
            f"- Anchor: {anchor_display} — {placement_why}",
        ]
    )
    if args.description:
        return f"{args.description}\n\n{block}"
    return block


def _derive_lands_in(scope: str, anchor: str | None, orphan: bool) -> str:
    if orphan:
        return "unanchored — needs your call"
    if scope == "in-scope-deferred":
        return f"parent work item ({anchor})"
    return str(anchor)


def _build_create_namespace(args: Namespace, description: str, priority: str) -> Namespace:
    return Namespace(
        noun=args.noun,
        raw=False,
        title=args.title,
        description=description,
        type=None,
        priority=priority,
        parent=None if args.orphan else args.anchor,
        label=[],
        orphan=args.orphan,
        spec=None,
        trivial=False,
        acceptance=None,
        track=args.track,
        load_config=args.load_config,
    )


def discover(backend: Backend, args: Namespace) -> JsonValue:
    """`work discover --noun N --title T (--anchor ID | --orphan) --discovered-from ID ...`.

    Body mirrors spec §4: validate the triage form and resolve the provenance
    source before any mint (steps 1-2), render the triage block (step 3),
    mint via `create_noun` (step 4), add the `discovered-from` edge (step 5),
    then assemble the envelope (step 6). The dep-write capability gate (step
    0) is enforced by the `REQUIRED_CAPABILITY` registration in
    `verbs/__init__.py`, ahead of this handler ever running.
    """
    _validate_placement_usage(args)
    scope, hatch = _parse_scope(args.scope)
    priority = _validate_priority(args.priority)
    scope_why = _require_rationale(args.scope_why, "scope_why", "--scope-why")
    priority_why = _require_rationale(args.priority_why, "priority_why", "--priority-why")
    if args.orphan:
        placement_why = _require_rationale(
            args.escalation_why, "escalation_why", "--escalation-why"
        )
    else:
        placement_why = _require_rationale(args.anchor_why, "anchor_why", "--anchor-why")

    source = _resolve_source(backend, args.discovered_from)

    if not args.orphan:
        _validate_anchor(backend, args.anchor, scope, source, args.discovered_from)

    description = _render_description(args, scope, hatch, scope_why, priority_why, placement_why)

    created = cast(
        "dict[str, JsonValue]",
        create_noun(backend, _build_create_namespace(args, description, priority)),
    )
    new_id = cast("str", created["id"])

    try:
        backend.dep_mutate("add", new_id, args.discovered_from, _DISCOVERED_FROM_TYPE)
    except WorkError as edge_error:
        raise WorkError(
            edge_error.code, edge_error.message, {**edge_error.detail, "created_id": new_id}
        ) from edge_error

    track = derive_track(backend.get(new_id).labels)
    lands_in = _derive_lands_in(scope, args.anchor, args.orphan)
    manifest_row: dict[str, JsonValue] = {
        "item": args.title,
        "scope": _scope_display(scope, hatch),
        "lands_in": lands_in,
        "tracked_item": new_id,
        "priority_why": f"{priority} — {priority_why}",
    }
    warnings = created.get("warnings", [])
    data: dict[str, JsonValue] = {
        "item": {"id": new_id, "title": args.title, "track": track},
        "edges": {"parent": args.anchor, "discovered_from": args.discovered_from},
        "triage": {"scope": args.scope, "priority": priority, "anchor": args.anchor},
        "manifest_row": manifest_row,
        "remaining_work": scope == "in-scope-deferred",
        "warnings": warnings if isinstance(warnings, list) else [],
    }
    return data
