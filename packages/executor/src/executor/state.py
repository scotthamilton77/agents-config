"""The runtime's folded state, narrowed to what a pairing decision reads.

`grind status --full` serializes the whole fold. Parsing it into a typed view
here keeps every decision above this module free of dict-shaped access, and
makes the executor's dependency on the runtime's serialization one explicit,
testable surface rather than a scatter of `.get()` calls.

Fields absent or of the wrong JSON type degrade to `None`/`False` rather than
raising: the runtime is a separate versioned program, and a decision that needs
a field it did not get refuses by name (`E_USAGE`, `E_NO_OPEN_PR`) instead of
crashing on a shape mismatch.
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
    """The folded run: its items, plus the closed-PR ledger.

    The ledger is carried because it is the only evidence that a `pr_closed`
    already applied -- the runtime leaves an item's PR reference in place
    across a close, so the item alone cannot answer "have I recorded this
    closure already?"
    """

    items: Mapping[str, ItemView]
    closed_prs: frozenset[tuple[str, int]]

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


def _item_view(item_id: str, payload: Mapping[str, JsonValue]) -> ItemView:
    pr = payload.get("pr")
    parked = payload.get("parked")
    return ItemView(
        id=item_id,
        status=_opt_str(payload, "status") or "",
        lane=_opt_str(payload, "lane"),
        work_id=_opt_str(payload, "work_id"),
        pr_number=_opt_int(pr, "number") if isinstance(pr, dict) else None,
        parked=parked is not None,
        park_reason=_opt_str(parked, "reason") if isinstance(parked, dict) else None,
    )


def _closed_prs(entries: JsonValue) -> frozenset[tuple[str, int]]:
    if not isinstance(entries, list):
        return frozenset()
    pairs: set[tuple[str, int]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        item_id = _opt_str(entry, "item")
        pr = _opt_int(entry, "pr")
        if item_id is not None and pr is not None:
            pairs.add((item_id, pr))
    return frozenset(pairs)


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
        closed_prs=_closed_prs(payload.get("closed_ledger")),
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
