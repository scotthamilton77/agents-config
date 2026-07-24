"""`park`/`redispatch`/`abandon`/`parked` -- disengagement from non-merging
work.

A work item whose PR won't merge parks with a typed reason and the machine
disengages: parked is bd's `blocked` status (drops the item out of `ready`,
so `claim` refuses it) + the `parked` label (the cheap queryable handle) + a
timestamped `[work] parked` marker note carrying the reason. The two human
verbs walk it back to `open` with distinct recorded intent -- recut is
abandon at the tracker layer. `parked` is a read-only staleness report; the
machine NEVER acts on a parked item of its own accord.
"""

from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timedelta

from workcli.backend import Backend
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.model import QueryFilters

PARKED_LABEL = "parked"
PARKED_MARKER = "[work] parked"  # full: "[work] parked <ISO-8601> <code>: <text>"
REDISPATCHED_MARKER = "[work] redispatched"  # full: "[work] redispatched <ISO-8601>"
ABANDONED_MARKER = "[work] abandoned"  # full: "[work] abandoned <ISO-8601>"

# The typed-reason vocabulary: code -> category. Machine-actionable
# reasons arrive here only after the executor's bounded budget is spent;
# human-required reasons park immediately, zero attempts. The budget numbers
# themselves are executor policy, never counted here.
REASONS: dict[str, str] = {
    "ci-failure": "machine",
    "merge-conflict": "machine",
    "approval-required": "human",
    "bot-declined": "human",
    "budget-exhausted": "human",
}


def _last_park_record(notes: str) -> tuple[str | None, str | None]:
    """(parked_at, reason) from the LAST `[work] parked` marker, or Nones.

    The last marker wins: a re-parked item (park -> redispatch -> park)
    reports its current stint, not its first. An unparseable payload
    degrades field-by-field to None rather than failing the caller.
    """
    payload: str | None = None
    for line in notes.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{PARKED_MARKER} "):
            payload = stripped[len(PARKED_MARKER) + 1 :]
    if payload is None:
        return None, None
    head = payload.split(": ", 1)[0]
    parts = head.split()
    if len(parts) != 2:
        return None, None
    parked_at, code = parts
    return parked_at, code if code in REASONS else None


def park(backend: Backend, args: Namespace) -> JsonValue:
    """`work park ID --reason CODE [--note TEXT]`.

    Vocabulary check first -- an unknown code fails before any backend call.
    Mutation order is graceful-degradation order: status `blocked` FIRST
    (kills claimability the instant anything lands), then the `parked`
    handle, then the marker note -- a crash mid-park leaves an item that is
    at worst un-ready, never a claimable "parked" item.
    """
    if args.reason not in REASONS:
        raise WorkError(
            ErrorCode.USAGE,
            f"park: unknown reason {args.reason!r}; one of: {', '.join(REASONS)}",
        )
    item = backend.get(args.id)
    if item.status == "closed":
        raise WorkError(ErrorCode.USAGE, f"park {args.id}: cannot park a closed item")
    if PARKED_LABEL in item.labels:
        # Idempotent replay: report the existing stint, mint nothing.
        _, existing = _last_park_record(item.notes)
        reason = existing if existing is not None else args.reason
        return {
            "id": args.id,
            "status": "parked",
            "reason": reason,
            "category": REASONS[reason],
        }

    backend.set_status(args.id, "blocked")
    backend.label_mutate("add", args.id, [PARKED_LABEL])
    text = args.note if args.note is not None else ""
    backend.append_note(args.id, f"{PARKED_MARKER} {args.now().isoformat()} {args.reason}: {text}")
    return {
        "id": args.id,
        "status": "parked",
        "reason": args.reason,
        "category": REASONS[args.reason],
    }


def _unpark_recorded_since_last_park(notes: str) -> bool:
    """True when a redispatch/abandon marker already follows the last park marker.

    The replay-dedup guard for `_unpark`: a crash after the marker append but
    before the label removal must converge on replay without minting a second
    (differently-timestamped) marker. Scoped to the last park stint so a
    marker from a *previous* park/unpark cycle never suppresses the current
    stint's record.
    """
    last_park = -1
    last_unpark = -1
    for index, line in enumerate(notes.splitlines()):
        stripped = line.strip()
        if stripped.startswith(f"{PARKED_MARKER} "):
            last_park = index
        elif stripped.startswith((REDISPATCHED_MARKER, ABANDONED_MARKER)):
            last_unpark = index
    return last_unpark > last_park


def _unpark(backend: Backend, args: Namespace, verb: str, marker: str) -> JsonValue:
    """Shared `redispatch`/`abandon` transition: parked -> open.

    Status `open` first (the item re-enters `ready` the instant anything
    lands), the intent marker second, and the `parked` handle off STRICTLY
    LAST: every crash window leaves the label as the recoverable handle, so
    a replay re-enters this path -- never the no-op branch -- and the
    marker is guaranteed durable before the handle drops. The dedup guard
    keeps the replay from minting a second marker.
    """
    item = backend.get(args.id)
    if item.status == "closed":
        raise WorkError(ErrorCode.USAGE, f"{verb} {args.id}: cannot {verb} a closed item")
    if PARKED_LABEL not in item.labels:
        if item.status == "open":
            return {"id": args.id, "status": "open"}  # idempotent no-op
        raise WorkError(ErrorCode.USAGE, f"{verb} {args.id}: not parked (status {item.status})")
    backend.set_status(args.id, "open")
    if not _unpark_recorded_since_last_park(item.notes):
        backend.append_note(args.id, f"{marker} {args.now().isoformat()}")
    backend.label_mutate("remove", args.id, [PARKED_LABEL])
    return {"id": args.id, "status": "open"}


def redispatch(backend: Backend, args: Namespace) -> JsonValue:
    """`work redispatch ID` -- the cause is fixed; back to ready."""
    return _unpark(backend, args, "redispatch", REDISPATCHED_MARKER)


def abandon(backend: Backend, args: Namespace) -> JsonValue:
    """`work abandon ID` -- the PR is closed; the item returns to ready."""
    return _unpark(backend, args, "abandon", ABANDONED_MARKER)


def parked(backend: Backend, args: Namespace) -> JsonValue:
    """`work parked [--stale-days N]` -- the read-only staleness report.

    Reports, never acts: reads only. Query results are lean (no
    notes fidelity guarantee), so the parked set is re-read via one
    `batch_get` -- the same re-get seam `reconcile` uses on its candidates.
    """
    lean = backend.query(QueryFilters(label=PARKED_LABEL))
    threshold = timedelta(days=args.stale_days)
    now = args.now()
    rows: list[JsonValue] = []
    for item in backend.batch_get([entry.id for entry in lean]):
        parked_at, reason = _last_park_record(item.notes)
        stale = False
        if parked_at is not None:
            try:
                stale = now - datetime.fromisoformat(parked_at) > threshold
            except (ValueError, TypeError):
                # Not an ISO timestamp (or naive where aware is expected):
                # degrade the field, never the report.
                parked_at = None
        rows.append(
            {
                "id": item.id,
                "title": item.title,
                "reason": reason,
                "category": REASONS.get(reason) if reason is not None else None,
                "parked_at": parked_at,
                "stale": stale,
            }
        )
    return {"items": rows, "stale_days": args.stale_days}
