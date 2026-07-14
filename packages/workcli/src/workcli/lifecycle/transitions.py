"""`claim`/`release`/`plan`/`promote` -- guarded lifecycle transitions (plan Task 4).

Every mutation here reads current state first and no-ops when already applied
(L7). `claim`'s container guard is declared-state (`is_container`), never
child-count (L16/§5 invariant 5) -- a childless `epic` is refused exactly
like a populated one. `promote` mirrors `create spec`'s L16 mint-before-
`planned` discipline: the two label swaps, then `instantiate_spec_shape`,
then `planned` stamped strictly last, so an interrupted promote leaves a
self-reporting, not-yet-planned container in the Planning queue rather than
a queue-invisible one.
"""

from __future__ import annotations

from argparse import Namespace

from workcli.backend import Backend
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.lifecycle import is_container
from workcli.lifecycle.create import finalize_spec_instantiation
from workcli.lifecycle.nouns import CREATING_SPEC_LABEL, PLANNED_LABEL


def claim(backend: Backend, args: Namespace) -> JsonValue:
    """`work claim ID` (plan L1: bd's own atomic `--claim`; invariant 3 staleness detection)."""
    item = backend.get(args.id)
    if item.status == "closed":
        raise WorkError(ErrorCode.NOT_CLAIMABLE, f"{args.id}: a closed item cannot be claimed")
    if item.status == "in_progress":
        return {"id": args.id, "status": "in_progress"}
    if is_container(item):
        raise WorkError(ErrorCode.NOT_CLAIMABLE, f"{args.id}: container; planned, not claimed")

    ready_ids = {ready_item.id for ready_item in backend.ready(None)}
    if args.id not in ready_ids:
        raise WorkError(ErrorCode.NOT_CLAIMABLE, f"{args.id}: blocked by an open dependency")

    backend.claim(args.id)
    return {"id": args.id, "status": "in_progress"}


def release(backend: Backend, args: Namespace) -> JsonValue:
    """`work release ID` -- returns a claimed item to `open` (plan L1)."""
    item = backend.get(args.id)
    if item.status == "in_progress":
        backend.set_status(args.id, "open")
        return {"id": args.id, "status": "open"}
    if item.status == "open":
        return {"id": args.id, "status": "open"}
    raise WorkError(ErrorCode.USAGE, f"{args.id}: cannot release a {item.status} item")


def plan(backend: Backend, args: Namespace) -> JsonValue:
    """`work plan ID (--done | --undo) [--force]` -- Planning-queue membership (§5, L16)."""
    if args.done == args.undo:
        raise WorkError(ErrorCode.USAGE, "plan: exactly one of --done or --undo is required")

    if args.undo:
        backend.label_mutate("remove", args.id, [PLANNED_LABEL])
        return {"id": args.id, "planned": False}

    item = backend.get(args.id)
    if not is_container(item) and not args.force:
        raise WorkError(ErrorCode.USAGE, f"plan --done {args.id}: expects a container or --force")
    if PLANNED_LABEL in item.labels:
        return {"id": args.id, "planned": True}

    backend.label_mutate("add", args.id, [PLANNED_LABEL])
    return {"id": args.id, "planned": True}


def promote(backend: Backend, args: Namespace) -> JsonValue:
    """`work promote ID` -- a `shape-feat` leaf becomes a `shape-spec` container (L16)."""
    item = backend.get(args.id)
    # `shape-spec` short-circuit FIRST, so a promote rerun is replay-safe: an
    # interrupted promote leaves `[shape-spec, creating-spec]` (shape-feat already
    # swapped off), and re-running must return a graceful no-op -- not trip the
    # "only a feat" guard below on the now-absent shape-feat. The reconcile sweep
    # finishes the still-present handle.
    if "shape-spec" in item.labels:
        return {"id": args.id, "promoted": "spec"}
    if "shape-feat" not in item.labels:
        raise WorkError(ErrorCode.USAGE, f"{args.id}: only a feat can be promoted")

    # `creating-spec` is added FIRST -- before the shape swap -- so any crash
    # from here on leaves the handle set and the `reconcile` sweep replays the
    # shared completion tail (`finalize_spec_instantiation`: swap shape-feat->
    # shape-spec, mint the template children, stamp `planned`, drop the handle
    # strictly last, L16). A crash before the handle is added leaves an untouched
    # `shape-feat` leaf -- promote simply never started.
    backend.label_mutate("add", args.id, [CREATING_SPEC_LABEL])
    finalize_spec_instantiation(backend, args.id, item.title)
    return {"id": args.id, "promoted": "spec"}
