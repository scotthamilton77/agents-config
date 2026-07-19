"""The four command bodies: `create`, `log`, `status`, `finish`.

Each takes the grind directory and an injected `now` clock (never a bare
`datetime.now()` call -- same seam precedent as workcli's `read_file`/`now`),
and returns a plain `dict[str, JsonValue]` shaped exactly per the spec's CLI
contract / emit-back envelope. `cli.py` owns argv parsing and stdout/exit-code
wiring; this module owns behavior only, so it's testable without a process.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from grind.derive import lane_status
from grind.envelope import GrindError
from grind.fold import fold
from grind.model import AnomalyRecord, JsonValue, RawEvent, State
from grind.payloads import validate_payload
from grind.serialize import anomaly_json, full_state_json, summarize
from grind.store import append_event, fold_dir, is_log_nonempty, load_events, write_state

Clock = Callable[[], datetime]


def _iso(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_or_raise(event_type: str, payload: RawEvent) -> None:
    errors = validate_payload(event_type, payload)
    if errors:
        raise GrindError(f"invalid payload for {event_type!r}: " + "; ".join(errors))


def _entity_delta(before: State, after: State, event: RawEvent) -> JsonValue:
    """The fold delta of one appended event: the entity's old/new status, or
    `None` when nothing changed (spec: "entity + old_status/new_status when an
    item/lane status changed, else null"). `item` takes precedence over `lane`
    when an event carries both (only `item_enqueued` does, and it's item-scoped)."""
    item_id = event.get("item")
    if isinstance(item_id, str):
        old_item = before.items.get(item_id)
        new_item = after.items.get(item_id)
        old_status = old_item.status if old_item is not None else None
        new_status = new_item.status if new_item is not None else None
        if old_status == new_status:
            return None
        return {"entity": item_id, "old_status": old_status, "new_status": new_status}

    lane_id = event.get("lane")
    if isinstance(lane_id, str):
        old_lane = before.lanes.get(lane_id)
        new_lane = after.lanes.get(lane_id)
        if old_lane is None or new_lane is None:
            return None
        old_lane_status = lane_status(before, old_lane)
        new_lane_status = lane_status(after, new_lane)
        if old_lane_status == new_lane_status:
            return None
        return {"entity": lane_id, "old_status": old_lane_status, "new_status": new_lane_status}

    return None


def _new_anomaly(before: State, after_check: State) -> AnomalyRecord | None:
    """The single anomaly (if any) the just-appended event produced, isolated
    by diffing two pure in-memory folds over `existing_events` vs.
    `existing_events + [event]` -- `fold` is deterministic and never revisits
    earlier events, so any new tail entries are attributable to this event
    alone (at most one: every fold handler calls `_anomaly` at most once)."""
    new_anomalies = after_check.anomalies[len(before.anomalies) :]
    return new_anomalies[0] if new_anomalies else None


def cmd_create(dir_: Path, seed: RawEvent, *, now: Clock) -> dict[str, JsonValue]:
    """`grind create --file seed.json` (spec CLI contract table)."""
    if is_log_nonempty(dir_):
        raise GrindError(
            "refusing to create: events.jsonl already exists and is non-empty; "
            "creation goes through create only once, never grind log grind_created mid-run"
        )
    _validate_or_raise("grind_created", seed)

    event: RawEvent = {"ts": _iso(now()), "type": "grind_created", **seed}
    append_event(dir_, event)
    state = fold_dir(dir_)
    write_state(dir_, full_state_json(state))
    return {"ok": True, "state_summary": summarize(state)}


def cmd_log(dir_: Path, event_type: str, payload: RawEvent, *, now: Clock) -> dict[str, JsonValue]:
    """`grind log <type> --json '<payload>'` -- returns the emit-back envelope."""
    _validate_or_raise(event_type, payload)

    existing_events = load_events(dir_)
    before_state = fold(existing_events)
    event: RawEvent = {"ts": _iso(now()), "type": event_type, **payload}
    check_state = fold([*existing_events, event])

    append_event(dir_, event)
    after_state = fold_dir(dir_)
    write_state(dir_, full_state_json(after_state))

    anomaly = _new_anomaly(before_state, check_state)
    return {
        "ok": True,
        "applied": anomaly is None,
        "anomaly": anomaly_json(anomaly),
        "delta": _entity_delta(before_state, check_state, event),
        # The conditions engine is a sibling bead (spec §"Emit-back"); this
        # verb never computes orchestration facts itself.
        "conditions": [],
    }


def cmd_status(dir_: Path, *, full: bool) -> dict[str, JsonValue]:
    """`grind status [--full]`."""
    state = fold_dir(dir_)
    if full:
        return {"ok": True, "state": full_state_json(state), "conditions": []}
    return {"ok": True, "state_summary": summarize(state), "conditions": []}


def cmd_finish(dir_: Path, summary: str, *, now: Clock) -> dict[str, JsonValue]:
    """`grind finish --summary <text>`."""
    _validate_or_raise("grind_finished", {"summary": summary})

    event: RawEvent = {"ts": _iso(now()), "type": "grind_finished", "summary": summary}
    append_event(dir_, event)
    state = fold_dir(dir_)
    write_state(dir_, full_state_json(state))
    return {"ok": True, "state_summary": summarize(state)}
