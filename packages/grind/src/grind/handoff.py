"""`grind status --handoff` -- the re-orientation projection.

The reader this is shaped for is an agent session with no context: freshly
started, or just compacted. It needs, in one call and without asking a human,
what this run is, where it got to, what is stuck and on what, where each lane
picks up, and which anomalies were accepted-and-flagged along the way. That
is the whole point -- a session that has to ask is a babysitting intervention.

It replaces the hand-maintained handoff file, so it carries exactly that
file's anatomy (spec "Compaction handoff"), sourced from the fold:

| handoff key | source |
|---|---|
| `mission` | `grind_created.mission` |
| `paused` / `pause_reason` / `resume_checklist` | `grind_paused`, while unresumed |
| `lanes` / `frontier` | seeded lanes + `lane_handover` + derived item statuses |
| `merged_ledger` / `closed_ledger` | `item_merged` / `pr_closed` |
| `human_docket` | the attention list (`item_waiting_human.why` lands there) |
| `protocols` | `grind_created.protocols` |
| `quirks` / `lessons` | `WARN` / `LESSON` observations |

**It is a projection over already-folded state and nothing more.** No event
type is introduced, no wall clock is read (the caller's `conditions` ride the
same envelope, as they do for every other `status` mode), and no orchestration
policy is expressed: like a condition, every field states what is true and
carries its evidence. Every key this projection *coins* is held to
`conditions.IMPERATIVE_VERBS` by test; keys it reuses from `State`'s own
serialized vocabulary (`pause_reason`, `resume_checklist`, ...) are that
vocabulary's business, and re-spelling them here to dodge the lock would buy a
green test with a synonym.

`frontier` is where that seam is easiest to cross and deliberately isn't:
it reports, per lane, the frontmost item in the lane's own queue order that is
neither terminal nor parked, and the `basis` on which that position was
picked. Which lane's frontier to act on next is a priority decision, and
priority is policy -- it belongs to the layer above this one, which is why no
field here ranks lanes against each other.
"""

from __future__ import annotations

from grind.derive import lane_status
from grind.model import Item, JsonValue, Lane, State
from grind.serialize import (
    anomaly_json,
    attention_json,
    closed_entry_json,
    merged_entry_json,
    observation_json,
    park_fields,
    summarize,
)

# An item at or past these has left the queue; it can't be where a lane picks
# up. Same two statuses `conditions` calls terminal.
_TERMINAL_ITEM_STATUSES = {"merged", "done"}

_FRONTIER_FOUND = "frontmost item in the lane's queue order that is neither terminal nor parked"
_FRONTIER_EMPTY = "every item in the lane's queue order is terminal or parked"


def _item_row(item: Item) -> dict[str, JsonValue]:
    """One item as the handoff reports it: identity, position, and the handles
    a cold reader needs to pick the work back up (`work_id` to cross-reference
    the external work tracker, `pr` to find the open change). Narrower than
    `status --full`'s item -- round history and discovery provenance are audit
    material, not re-orientation."""
    return {
        "id": item.id,
        "lane": item.lane,
        "title": item.title,
        "status": item.status,
        "work_id": item.work_id,
        "pr": {"number": item.pr.number, "url": item.pr.url} if item.pr is not None else None,
        "blocked_on": list(item.blocked_on),
        "parked": park_fields(item.parked) if item.parked is not None else None,
        "review": {
            "round": item.review.round,
            "kind": item.review.kind,
            "verdict": item.review.verdict,
            "open_threads": item.review.open_threads,
            "stalemate": item.review.stalemate,
        },
    }


def _lane_items(state: State, lane: Lane) -> list[Item]:
    return [state.items[item_id] for item_id in lane.item_ids if item_id in state.items]


def _lane_row(state: State, lane: Lane) -> dict[str, JsonValue]:
    """A lane and the exact position of every item on it -- the roster half of
    the handoff. `agent`/`model`/`effort` are post-`lane_handover` values, so
    the roster names who is actually on the lane now, not who was seeded onto
    it."""
    return {
        "id": lane.id,
        "name": lane.name,
        "agent": lane.agent,
        "model": lane.model,
        "effort": lane.effort,
        "status": lane_status(state, lane),
        "standing_down": lane.standing_down,
        "items": [_item_row(item) for item in _lane_items(state, lane)],
    }


def _frontier_row(state: State, lane: Lane) -> dict[str, JsonValue]:
    for item in _lane_items(state, lane):
        if item.parked is None and item.status not in _TERMINAL_ITEM_STATUSES:
            return {
                "lane": lane.id,
                "item": item.id,
                "title": item.title,
                "status": item.status,
                "blocked_on": list(item.blocked_on),
                "basis": _FRONTIER_FOUND,
            }
    return {
        "lane": lane.id,
        "item": None,
        "title": None,
        "status": None,
        "blocked_on": [],
        "basis": _FRONTIER_EMPTY,
    }


def _blocked_row(state: State, item: Item) -> dict[str, JsonValue]:
    """A stuck item and what it is stuck on, each blocker carrying its own
    current status -- the evidence that says whether the block is about to
    clear or is itself stuck. A blocker absent from `items` reports a `null`
    status rather than being dropped: an edge naming an unknown item is
    exactly the kind of thing a re-orienting reader must see."""
    return {
        "item": item.id,
        "lane": item.lane,
        "status": item.status,
        "note": item.blocked_note,
        "blocked_on": [
            {
                "item": blocker_id,
                "status": state.items[blocker_id].status if blocker_id in state.items else None,
            }
            for blocker_id in item.blocked_on
        ],
    }


def handoff_json(state: State) -> dict[str, JsonValue]:
    """The whole projection, in reading order: what this run is, whether it is
    running, where it got to, what is stuck, what a human owes it, what shipped,
    and what surprised it."""
    blocked = [
        item
        for item in state.items.values()
        if item.status == "blocked" or (item.blocked_on and item.parked is None)
    ]
    return {
        "summary": summarize(state),
        "mission": state.mission,
        "protocols": state.protocols,
        "last_event_ts": state.last_event_ts,
        # Pause state under `State`'s own field names rather than a nested
        # block of synonyms: one name per fact across the package, and the
        # imperative-verb lock stays strict on the vocabulary this projection
        # actually coins.
        "paused": state.paused,
        "pause_reason": state.pause_reason,
        "resume_checklist": list(state.resume_checklist),
        "finish_summary": state.finish_summary,
        "lanes": [_lane_row(state, lane) for lane in state.lanes.values()],
        "frontier": [_frontier_row(state, lane) for lane in state.lanes.values()],
        "blocked": [_blocked_row(state, item) for item in blocked],
        "human_docket": [attention_json(entry) for entry in state.attention],
        "merged_ledger": [merged_entry_json(entry) for entry in state.merged_ledger],
        "closed_ledger": [closed_entry_json(entry) for entry in state.closed_ledger],
        "parking_lot": [_item_row(item) for item in state.parking_lot().values()],
        "quirks": [observation_json(obs) for obs in state.observations if obs.level == "WARN"],
        "lessons": [observation_json(obs) for obs in state.lessons],
        "anomalies": [anomaly_json(record) for record in state.anomalies],
    }
