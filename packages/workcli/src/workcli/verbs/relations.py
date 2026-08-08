"""dep, label — the relation verbs.

Same shape as `verbs/read.py`/`verbs/write.py`: pure functions over a
`Backend`, no subprocess, no I/O beyond the injected seam.
"""

from __future__ import annotations

import dataclasses
from argparse import Namespace
from typing import cast

from workcli.backend import Backend
from workcli.envelope import ErrorCode, JsonValue, WorkError

_DEFAULT_DEP_TYPE = "blocks"
_PARENT_DEP_TYPE = "parent-child"

# The facade's own closed edge vocabulary, read off bd's documented set
# (`bd dep add --help`, bd 1.0.3) and confirmed one type at a time against a
# scratch install. A backend is not obliged to enforce it, and bd does not:
# every string in that probe -- including a deliberate nonsense one -- was
# stored verbatim as a real edge, so a typo'd type produces an edge that
# exists, renders, and participates in nothing. This frozenset is where that
# enforcement lives instead, and it gates `dep add` ONLY.
#
# `dep remove` stays open to any type on purpose: edges carrying an
# unsanctioned type already exist in the wild, and a closed set on the removal
# path would strand exactly the edges this check exists to stop being made.
# `DepEdge.type` stays an open `str` for the same reason -- a read must be able
# to report an edge type the write path would now refuse.
DEP_TYPES = frozenset(
    {
        "blocks",
        "tracks",
        "related",
        "parent-child",
        "discovered-from",
        "until",
        "caused-by",
        "validates",
        "relates-to",
        "supersedes",
    }
)


def _dep_type_check(dep_type: str) -> None:
    """Reject a type outside `DEP_TYPES`, before any backend call.

    Pure: no read is needed to know the type is nonsense, so this runs first
    and a rejected `dep add` costs zero backend invocations.
    """
    if dep_type in DEP_TYPES:
        return
    raise WorkError(
        ErrorCode.USAGE,
        f"unknown dep type {dep_type!r} (choose from {', '.join(sorted(DEP_TYPES))})",
        detail={"field": "type", "dep_type": dep_type},
    )


def _parent_arity_check(backend: Backend, from_id: str, to_id: str, dep_type: str) -> None:
    """Refuse a second parent for an item that already has one.

    An item's parent is single-valued, but the backend reports it from two
    sources that a second `parent-child` edge drives apart: the `parent`
    scalar is the backend's own field, while `children` is derived from
    reverse edges. A backend need not refuse the second edge -- bd accepts it
    silently -- so the item ends up with two parent-child edges and one scalar,
    and the field most readers check is the one that then omits a parent the
    tree still walks from. Anything counting an epic's children counts that
    item twice.

    Redirecting to `work update --set-parent` (the seam's atomic reparent,
    verified to REPLACE the old edge rather than add beside it) is
    what makes the recovery discoverable at the moment it is needed. Same
    guard shape and error code as `update`'s append-only notes tripwire: a
    write that would corrupt a single-valued field is refused by name, and
    names the verb that expresses the intent properly.

    Re-adding the parent an item ALREADY has is not a violation -- the
    postcondition the caller asked for already holds, a repeat is a no-op at
    the backend (verified against bd 1.0.3), and erroring would fail a correct
    request and break retry-safety after a timeout.
    """
    if dep_type != _PARENT_DEP_TYPE:
        return
    child = backend.get(from_id)
    if child.parent is None or child.parent == to_id:
        return
    raise WorkError(
        ErrorCode.FIELD_CLOBBER_GUARD,
        f"{from_id} is already a child of {child.parent}; an item has one parent. "
        f"Use `work update {from_id} --set-parent {to_id}` to move it",
        detail={"id": from_id, "parent": child.parent, "requested_parent": to_id},
    )


def _type_wall_check(backend: Backend, from_id: str, to_id: str, dep_type: str) -> None:
    """Pre-check the `blocks` type wall.

    `blocks` requires both items epic, or both non-epic (a milestone counts
    as non-epic). One order-preserving `Backend.batch_get` read pays for
    this certainty; a
    violation raises before `dep_mutate` (the mutating backend call) is ever
    invoked -- the fake's call log must show zero `dep`-mutation
    invocations in that case.
    """
    if dep_type != _DEFAULT_DEP_TYPE:
        return
    from_item, to_item = backend.batch_get([from_id, to_id])
    from_is_epic = from_item.type == "epic"
    to_is_epic = to_item.type == "epic"
    if from_is_epic == to_is_epic:
        return
    # Diagnostic uses the items' actual types -- a hardcoded "task" label
    # would misreport every other non-epic type (milestone, bug, feature).
    raise WorkError(
        ErrorCode.TYPE_WALL,
        f"blocks: {from_item.type} may not block {to_item.type}",
        detail={"from": from_id, "to": to_id, "dep_type": dep_type},
    )


def dep(backend: Backend, args: Namespace) -> JsonValue:
    """`work dep {add,remove,list} ID [TARGET] [--type]`.

    `dep add A B` = A depends on B. `add` is an add primitive and stays one:
    it validates and refuses, and never silently relocates an edge to make a
    request succeed. `list` maps the backend's own direction vocabulary into
    `{depends_on, dependents}` (the ruling that kills that ambiguity
    permanently -- see `model.DepListing`).
    """
    if args.action in ("add", "remove") and args.target is None:
        raise WorkError(ErrorCode.USAGE, f"dep {args.action} requires ID and TARGET")
    if args.action == "list":
        listing = backend.dep_list(args.id)
        return {
            "depends_on": [
                cast("JsonValue", dataclasses.asdict(edge)) for edge in listing.depends_on
            ],
            "dependents": [
                cast("JsonValue", dataclasses.asdict(edge)) for edge in listing.dependents
            ],
        }

    dep_type = args.type if args.type is not None else _DEFAULT_DEP_TYPE
    if args.action == "add":
        # Every pre-check raises before `dep_mutate` (the mutating backend call) is
        # reached, cheapest first: the vocabulary check needs no read at all,
        # and the two that do need one are mutually exclusive by type.
        _dep_type_check(dep_type)
        _parent_arity_check(backend, args.id, args.target, dep_type)
        _type_wall_check(backend, args.id, args.target, dep_type)
        backend.dep_mutate("add", args.id, args.target, dep_type)
    else:
        # argparse's `choices=["add", "remove", "list"]` already restricts
        # `args.action` to these three, and "list" returned above -- this
        # branch is always "remove". Passing the "remove" string literal
        # directly (not the untyped `args.action` Namespace field) is the
        # explicit narrow to `Backend.dep_mutate`'s `DepOp` Literal (Finding
        # 2), never a bare cast.
        backend.dep_mutate("remove", args.id, args.target, dep_type)
    return None


def label(backend: Backend, args: Namespace) -> JsonValue:
    """`work label {add,remove,list} ID [LABELS...]`.

    `add`/`remove` accept many labels and still emit one envelope: where the
    backend takes exactly one label per call (bd does), the adapter fans the
    request out into one invocation per label. `list` returns a flat
    `string[]` -- the shape the seam promises, whatever the backend's own.
    """
    if args.action in ("add", "remove") and not args.labels:
        raise WorkError(ErrorCode.USAGE, f"label {args.action} requires at least one LABEL")
    if args.action == "list":
        return list(backend.labels(args.id))
    backend.label_mutate(args.action, args.id, args.labels)
    return None
