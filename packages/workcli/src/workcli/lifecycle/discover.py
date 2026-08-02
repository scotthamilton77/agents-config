"""`work discover` -- mechanical enforcement of discovered-work triage form.

Implements the 2026-07-17 design spec: refuses to file a discovery without an
anchor (or an explicit `--orphan` escalation) and a complete, well-formed
triage record (Scope / Priority / Anchor), then mints the work item through the
existing `create <noun>` path -- inheriting its noun template, duplicate
guard, and track gate -- adds the `discovered-from` provenance edge, and
returns the completion-report manifest row as a structured envelope field.
The verb enforces *form*; scope correctness stays caller judgment.

Composes over `create_noun` (lifecycle/create.py) and adds no new minting
logic: noun->type/shape templating, the duplicate-title guard, placement
validation, and track resolution all execute unchanged.
"""

from __future__ import annotations

import re
from argparse import Namespace
from typing import cast

from workcli.backend import Backend
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.lifecycle import is_container
from workcli.lifecycle.create import create_noun
from workcli.lifecycle.nouns import LEAF_NOUNS, Noun, resolve_noun
from workcli.model import Item
from workcli.tracks import derive_track

_HATCHES = ("externally-blocked", "blast-radius", "own-cycle")
_PRIORITY_RE = re.compile(r"^P[0-4]$")
_BARE_PRIORITY_RE = re.compile(r"^[0-4]$")
_DISCOVERED_FROM_TYPE = "discovered-from"
_ORPHAN_ANCHOR_DISPLAY = "none: escalated"


def _triage_incomplete(field: str, message: str) -> WorkError:
    return WorkError(ErrorCode.TRIAGE_INCOMPLETE, message, detail={"field": field})


def _require_rationale(value: str | None, field: str, flag: str) -> str:
    """The rationale-shape rule: required, non-blank after strip, single-line."""
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


def _normalize_priority(value: str) -> str:
    """A bare digit ('2') normalizes to the canonical 'P2' notation.

    Nothing else about the value is ambiguous -- only the notation was ever
    rejected -- so anything not matching the bare-digit shape passes through
    unchanged for `_PRIORITY_RE` to accept or reject as before.
    """
    if _BARE_PRIORITY_RE.match(value):
        return f"P{value}"
    return value


def _validate_priority(value: str | None) -> str:
    if value is None:
        raise _triage_incomplete("priority", "--priority is required")
    normalized = _normalize_priority(value)
    if not _PRIORITY_RE.match(normalized):
        raise _triage_incomplete("priority", f"priority must be one of P0-P4, got {value!r}")
    return normalized


def _validate_noun(value: str) -> Noun:
    noun = resolve_noun(value)
    if noun is not None and noun in LEAF_NOUNS:
        return noun
    raise WorkError(
        ErrorCode.USAGE,
        f"invalid choice: {value!r} (choose from {', '.join(n.value for n in LEAF_NOUNS)})",
        detail={"field": "noun"},
    )


def _combined_error(errors: list[WorkError]) -> WorkError:
    """Fold 2+ independent field failures into one well-formed error.

    Each field's own message (still naming its valid choices/vocabulary) is
    preserved verbatim in both `message` and `detail.errors`, so nothing a
    single-field failure used to report is lost -- the caller just learns
    about every bad field from one invocation instead of one round-trip per
    field.

    The top-level `code` is `E_TRIAGE_INCOMPLETE` if any folded failure is
    triage-semantic, `E_USAGE` only when every folded failure is pure
    arg-shape. Per the discover spec's own design decision 6, the separate
    `E_TRIAGE_INCOMPLETE` code exists so a consumer can grep the top level
    for "triage rejected" -- collapsing to `E_USAGE` whenever a second,
    unrelated arg-shape mistake happens to co-occur would make that signal
    *quieter* exactly when the caller made an additional mistake, which is
    backwards. `detail.errors` still carries every individual error's own
    code either way, so nothing is lost by this choice.
    """
    detail: dict[str, JsonValue] = {
        "errors": cast(
            "list[JsonValue]",
            [
                {
                    "code": str(error.code),
                    "field": error.detail.get("field"),
                    "message": error.message,
                }
                for error in errors
            ],
        )
    }
    message = "; ".join(f"{error.detail.get('field', '?')}: {error.message}" for error in errors)
    code = (
        ErrorCode.TRIAGE_INCOMPLETE
        if any(error.code is ErrorCode.TRIAGE_INCOMPLETE for error in errors)
        else ErrorCode.USAGE
    )
    return WorkError(code, message, detail)


def _validate_noun_and_priority(args: Namespace) -> tuple[Noun, str]:
    """Validate --noun and --priority together, in one pass.

    Both were previously validated by mechanisms that each raised on the
    first failure -- argparse's own `choices=` for --noun (which never even
    reached this module) and this module's own `_validate_priority` -- so a
    caller who got both wrong learned about only one per invocation. Neither
    check raises until both have run; a single-field failure still raises
    that field's own error unchanged (preserving the existing contract), and
    only a two-field failure changes shape, via `_combined_error`.
    """
    noun_result: Noun | WorkError
    try:
        noun_result = _validate_noun(args.noun)
    except WorkError as noun_error:
        noun_result = noun_error

    priority_result: str | WorkError
    try:
        priority_result = _validate_priority(args.priority)
    except WorkError as priority_error:
        priority_result = priority_error

    if isinstance(noun_result, WorkError) and isinstance(priority_result, WorkError):
        raise _combined_error([noun_result, priority_result])
    if isinstance(noun_result, WorkError):
        raise noun_result
    if isinstance(priority_result, WorkError):
        raise priority_result
    return noun_result, priority_result


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
    """Scope-dependent anchor validity. Only called when `--anchor` is given."""
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
    priority: str,
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
            # `priority` (validated/normalized), never args.priority (raw) --
            # an alternative-notation caller ('2') and a canonical-notation
            # caller ('P2') must render byte-identical stored records.
            f"- Priority: {priority} — {priority_why}",
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


def _build_create_namespace(
    args: Namespace, description: str, priority: str, noun: Noun
) -> Namespace:
    return Namespace(
        noun=noun.value,
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

    Validates the triage form and resolves the provenance source before any
    mint (steps 1-2), renders the triage block (step 3), mints via
    `create_noun` (step 4), adds the `discovered-from` edge (step 5), then
    assembles the envelope (step 6). The dep-write capability gate (step 0)
    is enforced by the `REQUIRED_CAPABILITY` registration in
    `verbs/__init__.py`, ahead of this handler ever running.
    """
    noun, priority = _validate_noun_and_priority(args)
    _validate_placement_usage(args)
    scope, hatch = _parse_scope(args.scope)
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

    description = _render_description(
        args, scope, hatch, scope_why, priority, priority_why, placement_why
    )

    created = cast(
        "dict[str, JsonValue]",
        create_noun(backend, _build_create_namespace(args, description, priority, noun)),
    )
    new_id = cast("str", created["id"])

    try:
        backend.dep_mutate("add", new_id, args.discovered_from, _DISCOVERED_FROM_TYPE)
    except WorkError as edge_error:
        raise WorkError(
            edge_error.code, edge_error.message, {**edge_error.detail, "created_id": new_id}
        ) from edge_error

    try:
        track = derive_track(backend.get(new_id).labels)
    except WorkError as read_error:
        raise WorkError(
            read_error.code, read_error.message, {**read_error.detail, "created_id": new_id}
        ) from read_error
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
