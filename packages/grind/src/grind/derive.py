"""Read-side projections computed from `State`, never stored on it.

Lane status is "otherwise fully derived from item statuses" (spec): all done
-> `done`; any in flight -> the most advanced active state. Unlike
`conditions(State, now)` (a sibling bead's time-dependent facts), lane status
needs no wall clock and is safe to compute inline wherever `State` is read.
"""

from __future__ import annotations

from grind.model import ItemStatus, Lane, LaneStatus, State

# Progression rank among in-flight statuses; `queued`/`blocked`/`waiting-human`
# share rank 0 (none of them represent forward progress on the mainline path).
_RANK: dict[ItemStatus, int] = {
    "queued": 0,
    "blocked": 0,
    "waiting-human": 0,
    "in-progress": 1,
    "pr-open": 2,
    "in-review": 3,
    "merged": 4,
    "done": 5,
}


def lane_status(state: State, lane: Lane) -> LaneStatus:
    active_items = [
        state.items[item_id]
        for item_id in lane.item_ids
        if item_id in state.items and state.items[item_id].parked is None
    ]

    if lane.standing_down and not active_items:
        return "standing-down"

    if not active_items:
        return "queued"

    in_flight = [item for item in active_items if item.status != "done"]
    if not in_flight:
        return "done"

    # `done` items don't count toward "most advanced ACTIVE state" once the
    # lane still has work left -- otherwise one finished item would flash a
    # `done` lane while its siblings haven't even started.
    return max(in_flight, key=lambda item: _RANK[item.status]).status
