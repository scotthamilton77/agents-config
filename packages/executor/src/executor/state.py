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
from dataclasses import dataclass

from executor.envelope import ErrorCode, ExecutorError, JsonValue

# The run-local slug grammar the runtime assigns to discovered work that has no
# tracker item yet (S9T1-D5 case (c)). An id matching this is NEVER sent to the
# tracker.
RUN_LOCAL_SLUG = re.compile(r"^disc-\d+$")


@dataclass(frozen=True)
class ItemView:
    """One folded item, narrowed to the fields a pairing decision reads.

    `parked` and `park_reason` are separate because the runtime's park can be
    untyped: `parked` with `park_reason is None` is an item parked by a closure
    whose text named no vocabulary member. Reading absence of a reason as
    absence of a park would put such an item back in play.
    """

    id: str
    status: str
    lane: str | None
    work_id: str | None
    pr_number: int | None
    parked: bool
    park_reason: str | None = None


@dataclass(frozen=True)
class RunState:
    """The folded run: its items, and the ledgers a retry is judged against.

    `closures` maps an (item, PR) pair to when its closure was recorded, and
    `merged_shas` an item to the commit its merge recorded. Both are carried
    because an item alone cannot answer "have I recorded this already?" -- the
    runtime leaves a PR reference in place across a close, and a merged item
    says nothing about which commit merged it.

    `last_item_ts` is when each item was last touched by any event. It is what
    lets a ledger entry speak for the item's *current* position: the ledger
    records no outcome, so an item's status stands in for one, and it only
    stands in while that ledger entry is still the last thing that happened.
    """

    items: Mapping[str, ItemView]
    closures: Mapping[tuple[str, int], str]
    merged_shas: Mapping[str, str]
    last_item_ts: Mapping[str, str]

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


def _item_view(item_id: str, payload: Mapping[str, JsonValue]) -> ItemView:
    pr = payload.get("pr")
    parked = _parked(item_id, payload)
    return ItemView(
        id=item_id,
        status=_opt_str(payload, "status") or "",
        lane=_opt_str(payload, "lane"),
        work_id=_opt_str(payload, "work_id"),
        pr_number=_opt_int(pr, "number") if isinstance(pr, dict) else None,
        parked=parked is not None,
        park_reason=_opt_str(parked, "reason") if parked is not None else None,
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


def parse_state(payload: JsonValue) -> RunState:
    """`grind status --full`'s `state` object -> `RunState`.

    A reply that is not an object, or whose `items` is not an object, is an
    unparseable runtime envelope rather than an empty run: reporting "no items"
    for a garbled reply would let every verb refuse with the wrong reason.
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
    return RunState(
        items={
            item_id: _item_view(item_id, body)
            for item_id, body in items.items()
            if isinstance(body, dict)
        },
        closures=_closures(payload.get("closed_ledger")),
        merged_shas=_merged_shas(payload.get("merged_ledger")),
        last_item_ts=_timestamps(payload.get("last_item_ts")),
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
