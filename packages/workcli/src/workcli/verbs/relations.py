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


def _type_wall_check(backend: Backend, from_id: str, to_id: str, dep_type: str) -> None:
    """Pre-check the `blocks` type wall (spec item 4, decision 5).

    `blocks` requires both items epic, or both non-epic (a milestone counts
    as non-epic). One order-preserving `Backend.batch_get` read pays for
    this certainty; a
    violation raises before `dep_mutate` (the mutating bd call) is ever
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
    """`work dep {add,remove,list} ID [TARGET] [--type]` (spec §3).

    `dep add A B` = A depends on B. `list` maps bd's own inverted
    `--direction` naming into `{depends_on, dependents}` (the ruling that
    kills that ambiguity permanently -- see `model.DepListing`).
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

    bd's own `label add`/`label remove` accept exactly one label per call
    (orchestrator ruling) -- `add`/`remove` fan a multi-label request out
    into one bd invocation per label, still one envelope. `list` returns
    the flat `string[]` bd itself emits (spec §4: "labels are always
    `string[]`").
    """
    if args.action in ("add", "remove") and not args.labels:
        raise WorkError(ErrorCode.USAGE, f"label {args.action} requires at least one LABEL")
    if args.action == "list":
        return list(backend.labels(args.id))
    backend.label_mutate(args.action, args.id, args.labels)
    return None
