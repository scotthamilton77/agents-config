"""`defer`/`undefer` -- setting an idea aside, and picking it back up.

An item nobody has chosen to start is not stuck. It has no obstruction to
name, no attempt to count and nothing decaying while it waits, so the park
family's machinery would all be lying about it: a typed failure reason, and a
staleness report that nags forever about a cause that never existed.

Deferring is therefore its own state and carries none of that. It moves the
item to the `deferred` status and stops -- no handle label, no vocabulary, no
clock. Two properties follow, and they are the whole reason the state is a
status rather than another park reason. The item leaves `ready` on the
backend's own semantics, and it stays invisible to both parked surfaces,
which select on the park handle. And a read envelope tells the two apart on
`status` alone: `deferred` for an idea, `blocked` beside the `parked` label
for an obstruction, with no marker note read to decide it.

An item may hold one of the two states, never both, so `defer` refuses a
parked item outright rather than overwriting half of it.
"""

from __future__ import annotations

from argparse import Namespace
from datetime import datetime

from workcli.backend import Backend
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.lifecycle.park import PARKED_LABEL

DEFERRED_STATUS = "deferred"
DEFERRED_MARKER = "[work] deferred"  # full: "[work] deferred <ISO-8601>[: <text>]"
UNDEFERRED_MARKER = "[work] undeferred"  # full: "[work] undeferred <ISO-8601>"

# What a repaired marker says about itself. A repair can only ever record the
# repairing call's instant -- the crashed defer's is unrecoverable -- so the
# marker admits it, in the free text where no reader parses.
REPAIR_TEXT = "marker repaired on re-defer; this timestamp is the repairing call's"


def _marker(marker: str, now: datetime, text: str | None) -> str:
    """One marker line: the kind, the instant, and the caller's free text.

    Everything a reader interprets is the kind and the instant; the text
    after the first `": "` is prose nothing parses.
    """
    head = f"{marker} {now.isoformat()}"
    return f"{head}: {text}" if text else head


def _last_marker(notes: str) -> str | None:
    """Which of the two markers the LAST defer/undefer line is, or None.

    Both transitions read it to decide whether the stint they are about to
    record is already recorded. That is what makes each idempotent on replay:
    a re-issued call converges on the one marker already written instead of
    minting a second one stamped at a later instant. Scoped to the last line
    of either kind, so a marker from an earlier defer/undefer cycle can never
    stand in for the current stint's.
    """
    last: str | None = None
    for line in notes.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{DEFERRED_MARKER} "):
            last = DEFERRED_MARKER
        elif stripped.startswith(f"{UNDEFERRED_MARKER} "):
            last = UNDEFERRED_MARKER
    return last


def defer(backend: Backend, args: Namespace) -> JsonValue:
    """`work defer ID [--note TEXT]` -- set an item aside as not-now.

    Mutation order is `park`'s graceful-degradation order for the same
    reason: the status lands FIRST, so a crash mid-defer leaves an item that
    is at worst un-ready, never a claimable one that reports itself deferred.
    That order also makes the marker the only thing a partial defer can be
    missing, and re-deferring such an item repairs it.
    """
    item = backend.get(args.id)
    if item.status == "closed":
        raise WorkError(ErrorCode.USAGE, f"defer {args.id}: cannot defer a closed item")
    if PARKED_LABEL in item.labels:
        # Two different claims about one item -- an idea nobody started,
        # versus work that started and stuck. Holding both would leave a read
        # envelope saying deferred while the parked report still listed it,
        # which is exactly the ambiguity this state exists to remove. Clearing
        # the park is a decision, so it is made deliberately, by its own verb.
        raise WorkError(
            ErrorCode.USAGE,
            f"defer {args.id}: parked, not idle; `work redispatch` or `work abandon` first",
        )
    if item.status == DEFERRED_STATUS:
        # Idempotent replay: mint nothing -- unless this stint has no marker,
        # which is what a defer that died between its two writes leaves. The
        # status short-circuits every later defer, so this branch is the only
        # one that can ever repair it.
        if _last_marker(item.notes) != DEFERRED_MARKER:
            text = f"{REPAIR_TEXT}; {args.note}" if args.note else REPAIR_TEXT
            backend.append_note(args.id, _marker(DEFERRED_MARKER, args.now(), text))
        return {"id": args.id, "status": DEFERRED_STATUS}

    backend.set_status(args.id, DEFERRED_STATUS)
    backend.append_note(args.id, _marker(DEFERRED_MARKER, args.now(), args.note))
    return {"id": args.id, "status": DEFERRED_STATUS}


def undefer(backend: Backend, args: Namespace) -> JsonValue:
    """`work undefer ID` -- the idea's turn has come; back to ready.

    Mutation order is the inverse of `defer`'s, from the same rule read the
    other way. Here the status IS the handle a replay re-enters on, so it
    drops STRICTLY LAST: the marker lands while the item is still deferred,
    and every crash window therefore leaves an item that is still out of
    `ready` and still reachable by this path. Clearing the status first would
    strand the transition unrecorded, because the replay would meet an open
    item and return the no-op. The dedup guard keeps that replay from minting
    a second marker.
    """
    item = backend.get(args.id)
    if item.status == "closed":
        raise WorkError(ErrorCode.USAGE, f"undefer {args.id}: cannot undefer a closed item")
    if item.status != DEFERRED_STATUS:
        if item.status == "open":
            return {"id": args.id, "status": "open"}  # idempotent no-op
        raise WorkError(ErrorCode.USAGE, f"undefer {args.id}: not deferred (status {item.status})")

    if _last_marker(item.notes) != UNDEFERRED_MARKER:
        backend.append_note(args.id, _marker(UNDEFERRED_MARKER, args.now(), None))
    backend.set_status(args.id, "open")
    return {"id": args.id, "status": "open"}
