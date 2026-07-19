"""`conditions(state, now)` -- pure level-condition facts recomputed from
`State`, plus `item_unblocked_conditions(before, after)`, the one transition
condition derived from a fold delta.

HARD SEAM: a condition is a fact with evidence, never orchestration policy --
its name states what is true and its fields carry the evidence, never an
instruction ("nudge the lane", "escalate the review"). `IMPERATIVE_VERBS` is
the convention lock a test asserts every condition name against; growing the
vocabulary means adding a name here, never a verb.

Conditions are never part of the fold and never persisted in `state.json`
(spec: "not part of the fold ... a separate pure function"). `now` always
arrives as an explicit argument -- no bare `datetime.now()` call in this
module, same seam precedent as `verbs.Clock`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import cast

from grind.derive import lane_status
from grind.model import Item, JsonValue, State

Condition = dict[str, JsonValue]

# Terminal per `stale_item`'s table row ("item not terminal/parked") -- an
# item that reached its endpoint is not "going quiet", it's finished.
_TERMINAL_ITEM_STATUSES = {"merged", "done"}

# A blocker this advanced or further is itself stuck, not merely pending --
# what makes a chain of blocked items worth flagging as `blocked_chain`.
_CHAIN_BLOCKING_STATUSES = {"blocked", "waiting-human"}

_DURATION_RE = re.compile(r"^(\d+)([smhd])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

IMPERATIVE_VERBS = {
    "nudge",
    "escalate",
    "notify",
    "alert",
    "retry",
    "resume",
    "pause",
    "abort",
    "cancel",
    "block",
    "unblock",
    "merge",
    "close",
    "reopen",
    "assign",
    "reassign",
    "fix",
    "resolve",
}


def _duration(value: JsonValue, default_seconds: int) -> timedelta:
    """Parse a `config` threshold like `"45m"`; an unparsable/missing value
    falls back to `default_seconds` rather than raising -- thresholds are
    advisory config, not validated payload."""
    if isinstance(value, str):
        match = _DURATION_RE.match(value)
        if match is not None:
            amount, unit = match.groups()
            return timedelta(seconds=int(amount) * _UNIT_SECONDS[unit])
    return timedelta(seconds=default_seconds)


def _round_threshold(value: JsonValue, default: int) -> int:
    return value if isinstance(value, int) and value > 0 else default


def _parse_ts(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _age_seconds(ts: str | None, now: datetime) -> float | None:
    parsed = _parse_ts(ts)
    if parsed is None:
        return None
    return (now - parsed).total_seconds()


def _lane_and_grind_complete(state: State) -> list[Condition]:
    out: list[Condition] = []
    complete_count = 0
    for lane in state.lanes.values():
        if lane_status(state, lane) == "done":
            out.append({"condition": "lane_complete", "lane": lane.id})
            complete_count += 1
    if state.lanes and complete_count == len(state.lanes):
        out.append({"condition": "grind_complete"})
    return out


def _stale_items(state: State, now: datetime) -> list[Condition]:
    threshold = _duration(state.config.get("stale_item_after"), 45 * 60)
    out: list[Condition] = []
    for item in state.items.values():
        if item.parked is not None or item.status in _TERMINAL_ITEM_STATUSES:
            continue
        last_ts = state.last_item_ts.get(item.id)
        age = _age_seconds(last_ts, now)
        if age is None or age <= threshold.total_seconds():
            continue
        out.append(
            {"condition": "stale_item", "item": item.id, "age_seconds": age, "since": last_ts}
        )
    return out


def _stale_lanes(state: State, now: datetime) -> list[Condition]:
    threshold = _duration(state.config.get("stale_lane_after"), 30 * 60)
    out: list[Condition] = []
    for lane in state.lanes.values():
        candidates = [ts for ts in (state.last_lane_ts.get(lane.id),) if ts is not None]
        candidates.extend(
            ts for item_id in lane.item_ids if (ts := state.last_item_ts.get(item_id)) is not None
        )
        if not candidates:
            continue
        # Fixed-format "YYYY-MM-DDTHH:MM:SSZ" timestamps sort lexicographically
        # in chronological order, so max() finds the latest reference cheaply.
        latest = max(candidates)
        age = _age_seconds(latest, now)
        if age is None or age <= threshold.total_seconds():
            continue
        out.append(
            {"condition": "stale_lane", "lane": lane.id, "age_seconds": age, "since": latest}
        )
    return out


def _attention_pending(state: State, now: datetime) -> list[Condition]:
    if not state.attention:
        return []
    timestamps = [a.ts for a in state.attention if a.ts is not None]
    oldest_ts = min(timestamps) if timestamps else None
    return [
        {
            "condition": "attention_pending",
            "count": len(state.attention),
            "since": oldest_ts,
            "oldest_age_seconds": _age_seconds(oldest_ts, now),
        }
    ]


def _blocked_chain(item: Item, state: State) -> list[str]:
    """The ordered chain of ids starting at `item`, following blocker edges
    while each next target is itself stuck (blocked/waiting-human/parked).
    `visited` guards a malformed cyclic edge set from looping forever."""
    chain = [item.id]
    visited = {item.id}
    current = item
    while True:
        next_target: Item | None = None
        for target_id in current.blocked_on:
            if target_id in visited:
                continue
            target = state.items.get(target_id)
            if target is not None and (
                target.status in _CHAIN_BLOCKING_STATUSES or target.parked is not None
            ):
                next_target = target
                break
        if next_target is None:
            return chain
        chain.append(next_target.id)
        visited.add(next_target.id)
        current = next_target


def _blocked_chains(state: State) -> list[Condition]:
    out: list[Condition] = []
    for item in state.items.values():
        if item.status != "blocked":
            continue
        chain = _blocked_chain(item, state)
        if len(chain) > 1:
            out.append(
                {
                    "condition": "blocked_chain",
                    "item": item.id,
                    "chain": cast("list[JsonValue]", chain),
                }
            )
    return out


def _review_stalemate_risk(state: State) -> list[Condition]:
    n = _round_threshold(state.config.get("stalemate_risk_round"), 3)
    out: list[Condition] = []
    for item in state.items.values():
        history = item.round_history
        if len(history) < n:
            continue
        window = history[-n:]
        shas = {sha for _, sha in window}
        if len(shas) != 1:
            continue
        head_sha = next(iter(shas))
        if head_sha is None:
            continue
        out.append(
            {
                "condition": "review_stalemate_risk",
                "item": item.id,
                "round": window[-1][0],
                "head_sha": head_sha,
            }
        )
    return out


def conditions(state: State, now: datetime) -> list[Condition]:
    """Every currently-true level condition (spec table, all rows but
    `item_unblocked`). Returned by both the `grind log` emit-back envelope and
    `grind status`, so a level condition is never missed by not watching the
    right call."""
    return [
        *_lane_and_grind_complete(state),
        *_stale_items(state, now),
        *_stale_lanes(state, now),
        *_attention_pending(state, now),
        *_blocked_chains(state),
        *_review_stalemate_risk(state),
    ]


def item_unblocked_conditions(before: State, after: State) -> list[Condition]:
    """The transition condition: every item that was `blocked` before this
    append and isn't after it -- i.e. its final blocker edge just resolved.
    Derived from the delta between two folds, never recomputed from `after`
    alone (spec: immediately after the unblock the state is indistinguishable
    from an item queued with no edges, so this must ride the delta to reach
    ROOT exactly once)."""
    out: list[Condition] = []
    for item_id, after_item in after.items.items():
        before_item = before.items.get(item_id)
        if before_item is None:
            continue
        if before_item.status == "blocked" and after_item.status != "blocked":
            out.append({"condition": "item_unblocked", "item": item_id})
    return out
