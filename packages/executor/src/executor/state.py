"""The runtime's folded state, narrowed to what a pairing decision reads.

`grind status --full` serializes the whole fold. Parsing it into a typed view
here keeps every decision above this module free of dict-shaped access, and
makes the executor's dependency on the runtime's serialization one explicit,
testable surface rather than a scatter of `.get()` calls.

Fields absent or of the wrong JSON type degrade to `None`/`False` rather than
raising: the runtime is a separate versioned program, and a decision that needs
a field it did not get refuses by name (`E_USAGE`, `E_NO_OPEN_PR`) instead of
crashing on a shape mismatch. The exception is `parked`, where the degraded
reading would *authorise* rather than refuse -- see `_parked`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from executor.envelope import ErrorCode, ExecutorError, JsonValue

# The run-local slug grammar the runtime assigns to discovered work that has no
# tracker item yet (S9T1-D5 case (c)). An id matching this is NEVER sent to the
# tracker.
RUN_LOCAL_SLUG = re.compile(r"^disc-\d+$")

# The one runtime condition this package acts on (S9T1-C3). Every other
# condition name is read past: the runtime's vocabulary is free to grow, and a
# decision layer that parsed all of it would break on every addition.
BUDGET_SPENT_CONDITION = "attempt_budget_spent"


@dataclass(frozen=True)
class ItemView:
    """One folded item, narrowed to the fields a pairing decision reads.

    `parked` and `park_reason` are separate because the runtime's park can be
    untyped: `parked` with `park_reason is None` is an item parked by a closure
    whose text named no vocabulary member. Reading absence of a reason as
    absence of a park would put such an item back in play.

    `pr_number` and `pr_open` are separate for the same kind of reason. A
    closure leaves the reference behind and marks it closed, so a reference is
    evidence a PR cycle happened, not that one is live -- and the two fold
    rules want different halves: a failure-axis park needs a reference (the PR
    that failed to merge), while a fix attempt needs a live one.
    """

    id: str
    status: str
    lane: str | None
    work_id: str | None
    pr_number: int | None
    parked: bool
    park_reason: str | None = None
    pr_open: bool = False
    # The runtime's per-kind fix-attempt counts (S9T1-B6). Read to *report* a
    # count, never to decide one: whether the budget is spent is the runtime's
    # condition and nothing else (S9T1-C3), so a count this parser could not
    # read costs a wrong number in a report and can authorise nothing.
    attempts: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class BudgetSpent:
    """One `attempt_budget_spent` condition, exactly as the runtime reported it.

    S9T1-C3: exhaustion has one definition and it is the runtime's. The
    executor keeps no counter and recomputes no threshold -- this record's
    presence *is* the refusal, and its two numbers are the ones the refusal
    reports, so the report can never disagree with the fact it acted on.
    """

    item: str
    kind: str
    attempts: int
    budget: int


@dataclass(frozen=True)
class RunState:
    """The folded run: its items, the ledgers a retry is judged against, and the
    conditions the runtime reported over the same snapshot.

    `closures` maps an (item, PR) pair to when its closure was recorded, and
    `merged_shas` an item to the commit its merge recorded. Both are carried
    because an item alone cannot answer "have I recorded this already?" -- the
    runtime leaves a PR reference in place across a close, and a merged item
    says nothing about which commit merged it.

    `last_item_ts` is when each item was last touched by any event. It is what
    lets a ledger entry speak for the item's *current* position: the ledger
    records no outcome, so an item's status stands in for one, and it only
    stands in while that ledger entry is still the last thing that happened.

    `budget_spent` and `config` come from the *same* `status --full` reply as
    the items, which is what keeps a budget decision self-consistent: the
    condition the runtime computed and the config it computed it from are one
    snapshot, never two reads that could straddle an append.
    """

    items: Mapping[str, ItemView]
    closures: Mapping[tuple[str, int], str]
    merged_shas: Mapping[str, str]
    last_item_ts: Mapping[str, str]
    budget_spent: Mapping[tuple[str, str], BudgetSpent] = field(default_factory=dict)
    config: Mapping[str, JsonValue] = field(default_factory=dict)

    def item(self, item_id: str) -> ItemView:
        found = self.items.get(item_id)
        if found is None:
            raise ExecutorError(
                ErrorCode.USAGE,
                f"no item {item_id!r} in the runtime's folded state",
            )
        return found


def _opt_str(payload: Mapping[str, JsonValue], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value != "" else None


def _opt_int(payload: Mapping[str, JsonValue], key: str) -> int | None:
    value = payload.get(key)
    # `bool` is an `int` subclass and `true` is not a PR number.
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _parked(item_id: str, payload: Mapping[str, JsonValue]) -> Mapping[str, JsonValue] | None:
    """`parked` is the one field that may not degrade.

    Everywhere else a wrong-typed field falls back to `None` and the decision
    above fails closed -- a missing PR reference refuses, a missing lane
    refuses. Parkedness inverts that: read as a bare "not null", a malformed
    `parked: false` would make an unparked item look parked, which refuses
    legal commands *and* waves `redispatch`/`abandon` past their precondition
    into a tracker-first mutation the runtime then flags. A degraded value that
    authorises is not a degraded value; it is a corrupt reply.
    """
    parked = payload.get("parked")
    if parked is None or isinstance(parked, dict):
        return parked
    raise ExecutorError(
        ErrorCode.RUNTIME_ENVELOPE,
        f"item {item_id!r} carries a malformed `parked` value: {parked!r}",
    )


def _work_id(item_id: str, payload: Mapping[str, JsonValue]) -> str | None:
    """`work_id` is the other field that may not degrade.

    Degrading a malformed one to `None` makes `tracker_handle` fall back to
    the runtime's item id, so the executor would claim, park or close a
    tracker item named by that fallback on the strength of a reply that named
    no trustworthy handle. Like `parked`, the degraded reading authorises a
    mutation rather than refusing one.
    """
    work_id = payload.get("work_id")
    if work_id is None or (isinstance(work_id, str) and work_id != ""):
        return work_id
    raise ExecutorError(
        ErrorCode.RUNTIME_ENVELOPE,
        f"item {item_id!r} carries a malformed `work_id` value: {work_id!r}",
    )


def _pr_open(pr: JsonValue) -> bool:
    """A numbered reference the runtime states is *not* closed, and nothing
    weaker.

    `closed` is the field whose degraded reading authorises: an attempt claims
    to be fixing a PR that is still open, so anything short of an explicit
    `false` -- absent, null, mistyped, or `true` -- is not evidence of one and
    must not admit the attempt. Unlike `parked` and `work_id` this fails
    closed by *value* rather than by raising: a reference whose openness cannot
    be read is exactly the "no open PR" the rows reading it refuse for
    (S9T1-C4), and raising here would take down every other verb over a field
    only these two rows consult.
    """
    if not isinstance(pr, dict) or _opt_int(pr, "number") is None:
        return False
    return pr.get("closed") is False


def _attempts(payload: JsonValue) -> dict[str, int]:
    """The per-kind counts, keeping only entries that are actually counts.

    `bool` is an `int` subclass, so `true` would otherwise read as one attempt.
    """
    if not isinstance(payload, dict):
        return {}
    return {
        kind: count
        for kind, count in payload.items()
        if isinstance(count, int) and not isinstance(count, bool)
    }


def _item_view(item_id: str, payload: Mapping[str, JsonValue]) -> ItemView:
    pr = payload.get("pr")
    parked = _parked(item_id, payload)
    return ItemView(
        id=item_id,
        status=_opt_str(payload, "status") or "",
        lane=_opt_str(payload, "lane"),
        work_id=_work_id(item_id, payload),
        pr_number=_opt_int(pr, "number") if isinstance(pr, dict) else None,
        parked=parked is not None,
        park_reason=_opt_str(parked, "reason") if parked is not None else None,
        pr_open=_pr_open(pr),
        attempts=_attempts(payload.get("attempts")),
    )


def _closures(entries: JsonValue) -> dict[tuple[str, int], str]:
    """(item, PR) -> when its closure was recorded, latest wins.

    An entry missing its item, PR or timestamp is dropped: each is needed to
    decide whether a later `pr-closed` is that entry's retry, and an entry that
    cannot answer must not be read as one that answers yes.
    """
    if not isinstance(entries, list):
        return {}
    closures: dict[tuple[str, int], str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        item_id = _opt_str(entry, "item")
        pr = _opt_int(entry, "pr")
        ts = _opt_str(entry, "ts")
        if item_id is not None and pr is not None and ts is not None:
            closures[(item_id, pr)] = ts
    return closures


def _merged_shas(entries: JsonValue) -> dict[str, str]:
    """item -> the commit its merge recorded, latest wins."""
    if not isinstance(entries, list):
        return {}
    shas: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        item_id = _opt_str(entry, "item")
        sha = _opt_str(entry, "sha")
        if item_id is not None and sha is not None:
            shas[item_id] = sha
    return shas


def _timestamps(payload: JsonValue) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    return {key: value for key, value in payload.items() if isinstance(value, str)}


def _budget_spent(conditions: JsonValue) -> dict[tuple[str, str], BudgetSpent]:
    """The `attempt_budget_spent` conditions, keyed by (item, kind).

    Anything but a list is a fault, absent and null included. The runtime
    computes conditions on every `status` reply and already has an encoding for
    "none currently true" -- the empty list -- so a reply that omits the block
    or nulls it is not reporting an absence, it is a reply this package cannot
    read. Treating it as "no budget spent" would hand a corrupt or incompatible
    runtime the power to switch enforcement off silently, which is the whole
    mechanism `attempt` exists to be.

    It fails every verb rather than only `attempt`, on purpose: a runtime that
    cannot produce its own documented reply shape has not established that any
    of this package's readings of it hold. Same standing as the facade protocol
    pin, which refuses before mutating rather than after mis-parsing.

    The same rule one level down: an entry that names this condition and whose
    fields cannot be read is a fault, never a skipped entry.
    """
    if not isinstance(conditions, list):
        raise ExecutorError(
            ErrorCode.RUNTIME_ENVELOPE,
            f"the runtime reported no readable conditions block: {conditions!r}",
        )
    spent: dict[tuple[str, str], BudgetSpent] = {}
    for entry in conditions:
        if not isinstance(entry, dict) or entry.get("condition") != BUDGET_SPENT_CONDITION:
            continue
        item_id = _opt_str(entry, "item")
        kind = _opt_str(entry, "kind")
        attempts = _opt_int(entry, "attempts")
        budget = _opt_int(entry, "budget")
        if item_id is None or kind is None or attempts is None or budget is None:
            raise ExecutorError(
                ErrorCode.RUNTIME_ENVELOPE,
                f"the runtime reported an unreadable {BUDGET_SPENT_CONDITION} condition: {entry!r}",
            )
        spent[(item_id, kind)] = BudgetSpent(item_id, kind, attempts, budget)
    return spent


def parse_state(payload: JsonValue, conditions: JsonValue) -> RunState:
    """`grind status --full`'s `state` object and `conditions` list -> `RunState`.

    A reply that is not an object, or whose `items` is not an object, is an
    unparseable runtime envelope rather than an empty run: reporting "no items"
    for a garbled reply would let every verb refuse with the wrong reason.

    `conditions` is a second top-level key of the same reply rather than part
    of `state` -- the runtime recomputes conditions from the fold and never
    persists them -- so it arrives here as its own argument. It is required
    with no default: a default would be a value meaning "the runtime said
    nothing about budgets", and there is no such reading (see `_budget_spent`).
    """
    if not isinstance(payload, dict):
        raise ExecutorError(
            ErrorCode.RUNTIME_ENVELOPE,
            "runtime state is not a JSON object",
        )
    items = payload.get("items")
    if not isinstance(items, dict):
        raise ExecutorError(
            ErrorCode.RUNTIME_ENVELOPE,
            "runtime state carries no items object",
        )
    config = payload.get("config")
    return RunState(
        items={
            item_id: _item_view(item_id, body)
            for item_id, body in items.items()
            if isinstance(body, dict)
        },
        closures=_closures(payload.get("closed_ledger")),
        merged_shas=_merged_shas(payload.get("merged_ledger")),
        last_item_ts=_timestamps(payload.get("last_item_ts")),
        budget_spent=_budget_spent(conditions),
        config=dict(config) if isinstance(config, dict) else {},
    )


def tracker_handle(item: ItemView) -> str | None:
    """S9T1-D5: `tracker_id(item) = work_id or id`, with "no handle" first class.

    Three cases, in order:

    (a) `work_id` set -- the handle differs from `id`, guaranteed by both
        producers normalizing `work_id == id` away.
    (b) `work_id` absent and `id` outside the run-local slug grammar -- `id` is
        itself the handle.
    (c) `work_id` absent and `id` matching `disc-<n>` -- the item has no
        tracker handle at all. `None` here is a success value: every pairing
        decision for the item becomes "no tracker call" and the item is
        surfaced as unpromoted. Promotion is out of Tier 1.
    """
    if item.work_id is not None:
        return item.work_id
    if RUN_LOCAL_SLUG.match(item.id):
        return None
    return item.id
