"""`park`/`redispatch`/`abandon`/`parked` -- disengagement from non-merging
work.

A work item whose PR won't merge parks with a typed reason and the machine
disengages: parked is the backend's `blocked` status (drops it out of `ready`,
so `claim` refuses it) + the `parked` label (the cheap queryable handle) + a
timestamped `[work] parked` marker note carrying the reason. The two human
verbs walk it back to `open` with distinct recorded intent -- recut is
abandon at the tracker layer. `parked` is a read-only staleness report; the
machine NEVER acts on a parked item of its own accord.

`parked_stale` is the second, narrower surface over the same reads: the block
`ready` and `claim` carry so that pulling new work always shows the stuck
work first (S9T1-D10). Both surfaces read; neither writes.
"""

from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass
from datetime import datetime, timedelta

from workcli.backend import Backend
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.model import Item, QueryFilters

PARKED_LABEL = "parked"
PARKED_MARKER = "[work] parked"  # full: "[work] parked <ISO-8601> <code>: <text>"
REDISPATCHED_MARKER = "[work] redispatched"  # full: "[work] redispatched <ISO-8601>"
ABANDONED_MARKER = "[work] abandoned"  # full: "[work] abandoned <ISO-8601>"

# S2-D4's threshold, and the ONE definition of it: `work parked --stale-days`
# defaults to it, and the `parked_stale` block rides it with no flag of its
# own -- tuning stays on the report, so the surfacing every `ready`/`claim`
# carries cannot be quietly widened per call site.
DEFAULT_STALE_DAYS = 7

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

# What a repaired marker says about itself. A repair can only ever record the
# repairing call's instant and reason -- the failed park's are unrecoverable --
# so the marker admits it, in the free text where no reader parses.
REPAIR_TEXT = "marker repaired on re-park; this timestamp and reason are the repairing call's"


def _park_marker(now: datetime, reason: str, text: str) -> str:
    """The one park-marker format: `[work] parked <ISO-8601> <code>: <text>`.

    Everything before the first `": "` is the head `_last_park_record` parses
    and must stay exactly two whitespace-separated tokens; `text` is free
    prose no reader interprets.
    """
    return f"{PARKED_MARKER} {now.isoformat()} {reason}: {text}"


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


@dataclass(frozen=True)
class _Stint:
    """The last park stint as it can actually be read off an item's notes.

    `parked_at is None` is the load-bearing case: it means the age is
    *unknowable* -- no marker, a malformed head, or a timestamp that isn't
    ISO-8601 -- which the two surfaces treat oppositely. `stale` is
    PROVABLY-older-than-threshold and stays false when the age is unknowable
    (S2-B7); the `parked_stale` block adds the unknowable ones back.
    """

    parked_at: str | None
    reason: str | None
    stale: bool


def _read_stint(notes: str, now: datetime, threshold: timedelta) -> _Stint:
    parked_at, reason = _last_park_record(notes)
    stale = False
    if parked_at is not None:
        try:
            stale = now - datetime.fromisoformat(parked_at) > threshold
        except (ValueError, TypeError):
            # Not an ISO timestamp (or naive where aware is expected):
            # degrade the field, never the report.
            parked_at = None
    return _Stint(parked_at=parked_at, reason=reason, stale=stale)


def _stint_row(item: Item, stint: _Stint) -> dict[str, JsonValue]:
    """The fields both surfaces share; `parked` appends its own `stale` flag."""
    return {
        "id": item.id,
        "title": item.title,
        "reason": stint.reason,
        "category": REASONS.get(stint.reason) if stint.reason is not None else None,
        "parked_at": stint.parked_at,
    }


def park(backend: Backend, args: Namespace) -> JsonValue:
    """`work park ID --reason CODE [--note TEXT]`.

    Vocabulary check first -- an unknown code fails before any backend call.
    Mutation order is graceful-degradation order: status `blocked` FIRST
    (kills claimability the instant anything lands), then the `parked`
    handle, then the marker note -- a crash mid-park leaves an item that is
    at worst un-ready, never a claimable "parked" item. That order also makes
    the marker the only thing a partial park can be missing, and re-parking
    such an item repairs it.
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
        # Idempotent replay: report the existing stint, mint nothing -- unless
        # there is no readable stint to report. The three primitives make a
        # park that failed after the label a parked item with nothing
        # recorded, and the label short-circuits every later park, so this
        # branch is the only one that can ever repair it; reporting the
        # incoming reason over an item that stores none would disguise the
        # damage instead. Mint the marker the failed park owed, then report it.
        _, existing = _last_park_record(item.notes)
        if existing is None:
            text = f"{REPAIR_TEXT}; {args.note}" if args.note else REPAIR_TEXT
            backend.append_note(args.id, _park_marker(args.now(), args.reason, text))
            existing = args.reason
        return {
            "id": args.id,
            "status": "parked",
            "reason": existing,
            "category": REASONS[existing],
        }

    backend.set_status(args.id, "blocked")
    backend.label_mutate("add", args.id, [PARKED_LABEL])
    text = args.note if args.note is not None else ""
    backend.append_note(args.id, _park_marker(args.now(), args.reason, text))
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


def _read_parked_items(backend: Backend) -> list[Item]:
    """The two-read join both surfaces share: the parked set, notes included.

    Query results are lean (no notes fidelity guarantee), so the parked set is
    re-read via one `batch_get` -- the same re-get seam `reconcile` uses on
    its candidates. Reads only; a caller of either surface issues no write on
    account of it (S9T1-P2).
    """
    lean = backend.query(QueryFilters(label=PARKED_LABEL))
    return backend.batch_get([entry.id for entry in lean])


def parked(backend: Backend, args: Namespace) -> JsonValue:
    """`work parked [--stale-days N]` -- the read-only staleness report.

    Reports, never acts: reads only.
    """
    threshold = timedelta(days=args.stale_days)
    now = args.now()
    rows: list[JsonValue] = []
    for item in _read_parked_items(backend):
        stint = _read_stint(item.notes, now, threshold)
        rows.append({**_stint_row(item, stint), "stale": stint.stale})
    return {"items": rows, "stale_days": args.stale_days}


def parked_stale(backend: Backend, now: datetime, *, verb: str) -> list[JsonValue]:
    """The `parked_stale` block `ready` and `claim` carry (S9T1-D10).

    Membership is *proven-stale OR unknown-age*: an item past
    `DEFAULT_STALE_DAYS`, plus every item whose park marker cannot be read at
    all. That is deliberately wider than `work parked`'s `stale` flag, which
    stays false when the age is unprovable (S2-B7) -- here a corrupted marker
    must never be the thing that exempts an item from being surfaced.

    Fail-closed: a failed read raises rather than returning a short block, so
    no `ready`/`claim` success envelope can ever carry a silently
    under-reported surfacing. The underlying error's code and detail survive
    (a caller's retry logic keys on them); only the message gains the stage,
    so the envelope says which of the verb's two reads went down.
    """
    threshold = timedelta(days=DEFAULT_STALE_DAYS)
    try:
        items = _read_parked_items(backend)
    except WorkError as read_error:
        raise WorkError(
            read_error.code,
            f"{verb}: cannot read the parked-work surfacing ({read_error.message}); "
            f"the block is mandatory, so {verb} fails rather than reporting without it",
            {**read_error.detail, "stage": "parked_stale"},
        ) from read_error
    rows: list[JsonValue] = []
    for item in items:
        stint = _read_stint(item.notes, now, threshold)
        if stint.stale or stint.parked_at is None:
            rows.append(_stint_row(item, stint))
    return rows
