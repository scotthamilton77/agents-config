"""State -> JsonValue: `state.json`, `status --full`, and `status`'s default summary.

Explicit field-by-field serializers rather than `dataclasses.asdict` -- the
house typed-boundary discipline (no untyped dict/any at a module boundary)
applies to output shape too, not just input parsing.
"""

from __future__ import annotations

from typing import cast

from grind.derive import lane_status
from grind.model import (
    AnomalyRecord,
    AttentionEntry,
    ClosedEntry,
    DiscoveredWork,
    Item,
    ItemReview,
    JsonValue,
    Lane,
    MergedEntry,
    Observation,
    ParkingEntry,
    PrRef,
    State,
)


def _pr_ref_json(pr: PrRef | None) -> JsonValue:
    if pr is None:
        return None
    return {"number": pr.number, "url": pr.url}


def _item_review_json(review: ItemReview) -> JsonValue:
    return {
        "round": review.round,
        "kind": review.kind,
        "head_sha": review.head_sha,
        "detail": review.detail,
        "verdict": review.verdict,
        "open_threads": review.open_threads,
        "wont_fix_count": review.wont_fix_count,
        "stalemate": review.stalemate,
    }


def _parking_entry_json(parked: ParkingEntry | None) -> JsonValue:
    if parked is None:
        return None
    return {"kind": parked.kind, "note": parked.note}


def _discovered_work_json(discovered: DiscoveredWork | None) -> JsonValue:
    if discovered is None:
        return None
    return {"source": discovered.source, "rationale": discovered.rationale}


def _item_json(item: Item) -> JsonValue:
    return {
        "id": item.id,
        "lane": item.lane,
        "title": item.title,
        "status": item.status,
        "bead": item.bead,
        "blocked_on": list(item.blocked_on),
        "blocked_note": item.blocked_note,
        "pr": _pr_ref_json(item.pr),
        "review": _item_review_json(item.review),
        "parked": _parking_entry_json(item.parked),
        "discovered": _discovered_work_json(item.discovered),
        "round_history": [
            {"round": r, "head_sha": sha, "ts": ts} for r, sha, ts in item.round_history
        ],
    }


def _lane_json(state: State, lane: Lane) -> JsonValue:
    return {
        "id": lane.id,
        "name": lane.name,
        "agent": lane.agent,
        "model": lane.model,
        "effort": lane.effort,
        "item_ids": list(lane.item_ids),
        "standing_down": lane.standing_down,
        "status": lane_status(state, lane),
    }


def _attention_json(entry: AttentionEntry) -> JsonValue:
    return {
        "text": entry.text,
        "item": entry.item,
        "lane": entry.lane,
        "auto": entry.auto,
        "kind": entry.kind,
        "ts": entry.ts,
    }


def _observation_json(obs: Observation) -> JsonValue:
    return {
        "level": obs.level,
        "message": obs.message,
        "item": obs.item,
        "lane": obs.lane,
        "ts": obs.ts,
    }


def _merged_entry_json(entry: MergedEntry) -> JsonValue:
    return {"item": entry.item, "pr": entry.pr, "sha": entry.sha, "ts": entry.ts}


def _closed_entry_json(entry: ClosedEntry) -> JsonValue:
    return {"item": entry.item, "pr": entry.pr, "reason": entry.reason, "ts": entry.ts}


def anomaly_json(anomaly: AnomalyRecord | None) -> JsonValue:
    if anomaly is None:
        return None
    return {
        "ts": anomaly.ts,
        "type": anomaly.type,
        "item": anomaly.item,
        "lane": anomaly.lane,
        "reason": anomaly.reason,
    }


def full_state_json(state: State) -> dict[str, JsonValue]:
    """The entire fold output (spec: `status --full`'s "entire state serialized")."""
    return {
        "seeded": state.seeded,
        "title": state.title,
        "repo": state.repo,
        "mission": state.mission,
        "protocols": state.protocols,
        "config": dict(state.config),
        "paused": state.paused,
        "pause_reason": state.pause_reason,
        "resume_checklist": list(state.resume_checklist),
        "finished": state.finished,
        "finish_summary": state.finish_summary,
        "lanes": {lane_id: _lane_json(state, lane) for lane_id, lane in state.lanes.items()},
        "items": {item_id: _item_json(item) for item_id, item in state.items.items()},
        "attention": [_attention_json(a) for a in state.attention],
        "observations": [_observation_json(o) for o in state.observations],
        "merged_ledger": [_merged_entry_json(m) for m in state.merged_ledger],
        "closed_ledger": [_closed_entry_json(c) for c in state.closed_ledger],
        "lessons": [_observation_json(o) for o in state.lessons],
        "anomalies": [anomaly_json(a) for a in state.anomalies],
    }


def summarize(state: State) -> dict[str, JsonValue]:
    """The default `status` / `create` / `finish` report: header + counts, not
    the full item-by-item state (spec: `status`'s "Default: summary")."""
    items_by_status: dict[str, int] = {}
    for item in state.items.values():
        if item.parked is not None:
            continue
        items_by_status[item.status] = items_by_status.get(item.status, 0) + 1

    return {
        "title": state.title,
        "repo": state.repo,
        "paused": state.paused,
        "pause_reason": state.pause_reason,
        "finished": state.finished,
        "lanes": [
            {"id": lane.id, "name": lane.name, "status": lane_status(state, lane)}
            for lane in state.lanes.values()
        ],
        "items_by_status": cast("dict[str, JsonValue]", items_by_status),
        "parked_count": len(state.parking_lot()),
        "attention_count": len(state.attention),
        "anomaly_count": len(state.anomalies),
    }
