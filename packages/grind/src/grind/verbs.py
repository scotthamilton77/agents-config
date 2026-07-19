"""The five command bodies: `create`, `log`, `status`, `check`, `finish`.

Each takes the grind directory and an injected `now` clock (never a bare
`datetime.now()` call -- same seam precedent as workcli's `read_file`/`now`),
and returns a plain `dict[str, JsonValue]` shaped exactly per the spec's CLI
contract / emit-back envelope. `cli.py` owns argv parsing and stdout/exit-code
wiring; this module owns behavior only, so it's testable without a process.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from grind.derive import lane_status
from grind.envelope import GrindError
from grind.fold import fold
from grind.model import DEFAULT_CONFIG, AnomalyRecord, JsonValue, RawEvent, State
from grind.payloads import validate_payload
from grind.render import render_dashboard
from grind.serialize import anomaly_json, full_state_json, summarize
from grind.store import (
    TornTailRepair,
    append_event,
    dashboard_path,
    fold_dir,
    is_log_nonempty,
    load_events,
    write_dashboard,
    write_state,
)

Clock = Callable[[], datetime]

# `ts` and `type` are stamped by the CLI at append time (spec: "ts ... Never
# supplied by the caller"; `type` is the CLI-selected taxonomy). A payload/seed
# carrying either would overwrite the CLI-controlled envelope via the `**`
# spread below -- e.g. an `observation` smuggling `type=grind_finished` would
# persist and apply a terminal event while the envelope reports success. A
# caller supplying one is confused, so reject (command error, nothing appended)
# rather than silently merge-last.
_RESERVED_ENVELOPE_KEYS = ("ts", "type")


def _iso(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600}
_DURATION_RE = re.compile(r"^(\d+)([smh])$")


def _parse_duration(text: str) -> float:
    """`<int><unit>` where unit is `s`/`m`/`h` (spec examples: "45m", "30m", "1h")."""
    match = _DURATION_RE.match(text)
    if match is None:
        raise GrindError(
            f"invalid duration {text!r}: expected <int><unit> with unit s, m, or h (e.g. 30m)"
        )
    amount, unit = match.groups()
    return float(amount) * _DURATION_UNITS[unit]


def _default_max_age_seconds(config: dict[str, JsonValue]) -> float:
    """No dedicated grind-level threshold exists in `config` -- `grind check` probes
    whole-grind liveness, not a single item or lane. Default to the stricter (lower)
    of the two entity-level thresholds so the watchdog fires promptly; this also
    matches the spec's own example invocation, `grind check --max-age 30m`, which is
    `stale_lane_after`'s default."""
    item_after = config.get("stale_item_after", DEFAULT_CONFIG["stale_item_after"])
    lane_after = config.get("stale_lane_after", DEFAULT_CONFIG["stale_lane_after"])
    if not isinstance(item_after, str) or not isinstance(lane_after, str):
        raise GrindError(
            "config stale_item_after/stale_lane_after must be duration strings (e.g. 30m)"
        )
    return min(_parse_duration(item_after), _parse_duration(lane_after))


def _validate_or_raise(event_type: str, payload: RawEvent) -> None:
    reserved = [key for key in _RESERVED_ENVELOPE_KEYS if key in payload]
    if reserved:
        raise GrindError(
            f"payload for {event_type!r} may not carry CLI-controlled envelope "
            f"key(s) {', '.join(reserved)}: the CLI stamps ts and type"
        )
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


def _new_anomaly(before: State, after: State) -> AnomalyRecord | None:
    """The single anomaly (if any) the just-appended event produced, isolated
    by diffing the pre-append fold against the post-append fold -- `fold` is
    deterministic and never revisits earlier events, so any new tail entries
    are attributable to this event alone (at most one: every fold handler
    calls `_anomaly` at most once)."""
    new_anomalies = after.anomalies[len(before.anomalies) :]
    return new_anomalies[0] if new_anomalies else None


def _torn_tail_json(repair: TornTailRepair | None) -> JsonValue:
    """The write-path torn-tail repair (if any) as an emit-back field (spec
    "Torn tail": "records a torn_tail anomaly in the command's envelope").
    `None` when the log was intact. Deliberately distinct from the envelope's
    `anomaly` field, which is the fold-derived event-level anomaly: a torn-tail
    repair and an event anomaly can co-occur on one append, and neither may mask
    the other."""
    if repair is None:
        return None
    return {"quarantined": repair.quarantined, "reason": repair.reason}


def _append_and_persist(dir_: Path, event: RawEvent) -> tuple[State, TornTailRepair | None]:
    """The one write-then-refold sequence every appending verb shares: append,
    refold from the persisted log (never from memory -- state.json must
    reflect what disk actually holds), rewrite state.json.

    `append_event` may repair a torn tail left by a crashed prior writer; once
    repaired the tail is gone from disk, so the subsequent `fold_dir` cannot see
    it and the returned `State.anomalies` never carries it. The repair is
    returned separately for the verb to surface in its envelope -- the only place
    a caller learns prior log data was quarantined or a newline restored. It is
    deliberately NOT folded into `state.anomalies`: after repair a
    delete-and-refold yields a clean log, so persisting a non-reproducible
    anomaly would break the spec's byte-identical replay invariant."""
    repair = append_event(dir_, event)
    state = fold_dir(dir_)
    write_state(dir_, full_state_json(state))
    write_dashboard(dir_, render_dashboard(state))
    return state, repair


def cmd_create(dir_: Path, seed: RawEvent, *, now: Clock) -> dict[str, JsonValue]:
    """`grind create --file seed.json` (spec CLI contract table)."""
    if is_log_nonempty(dir_):
        raise GrindError(
            "refusing to create: events.jsonl already exists and is non-empty; "
            "creation goes through create only once, never grind log grind_created mid-run"
        )
    _validate_or_raise("grind_created", seed)

    event: RawEvent = {"ts": _iso(now()), "type": "grind_created", **seed}
    # `create` refuses a non-empty log (above), so a torn tail is unreachable
    # here -- the repair is always None; no `torn_tail` field to surface.
    state, _ = _append_and_persist(dir_, event)
    return {"ok": True, "state_summary": summarize(state)}


def cmd_log(dir_: Path, event_type: str, payload: RawEvent, *, now: Clock) -> dict[str, JsonValue]:
    """`grind log <type> --json '<payload>'` -- returns the emit-back envelope."""
    if event_type == "grind_created":
        # Creation goes through `create` only (spec CLI contract), and
        # `cmd_create`'s refusal message explicitly promises `grind log
        # grind_created` is never allowed. In a fresh dir the fold would
        # otherwise treat this as the first, valid creation event; reject it as
        # a command error regardless of directory state (nothing appended). The
        # reserved-key guard does not cover this -- the event type is the verb
        # argument, not a payload key.
        raise GrindError(
            "refusing to log 'grind_created': creation goes through create "
            "only, never grind log grind_created"
        )
    _validate_or_raise(event_type, payload)

    before_state = fold(load_events(dir_))
    event: RawEvent = {"ts": _iso(now()), "type": event_type, **payload}
    after_state, repair = _append_and_persist(dir_, event)

    anomaly = _new_anomaly(before_state, after_state)
    return {
        "ok": True,
        "applied": anomaly is None,
        "anomaly": anomaly_json(anomaly),
        "torn_tail": _torn_tail_json(repair),
        "delta": _entity_delta(before_state, after_state, event),
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


def cmd_check(dir_: Path, max_age: str | None, *, now: Clock) -> dict[str, JsonValue]:
    """`grind check [--max-age <dur>]` (spec "Staleness watchdog"): the external
    probe a fully-quiet grind can't self-report. Folds the log first -- `paused`
    and `finished` are always fold-derived, never read off the raw final line, so
    a trailing anomalous event can't hide either state. A paused or finished grind
    reports `stale: false` and exits 0 regardless of the last event's age; an
    unfinished, unpaused grind is stale once that age exceeds `max_age` (or, absent
    `--max-age`, the config's own stale thresholds)."""
    events = load_events(dir_)
    if not events:
        raise GrindError(
            "cannot check staleness: no events in log (grind not yet created via `grind create`)"
        )

    state = fold(events)
    last_ts = events[-1].get("ts")
    if not isinstance(last_ts, str):
        raise GrindError("cannot check staleness: last logged event has no ts")

    age_s = (now() - _parse_ts(last_ts)).total_seconds()
    max_age_s = (
        _parse_duration(max_age) if max_age is not None else _default_max_age_seconds(state.config)
    )
    stale = not state.paused and not state.finished and age_s > max_age_s

    return {
        "ok": True,
        "last_event_ts": last_ts,
        "age_s": age_s,
        "stale": stale,
        "paused": state.paused,
        "finished": state.finished,
    }


def cmd_render(dir_: Path) -> dict[str, JsonValue]:
    """`grind render` (spec CLI contract table): refolds and re-renders
    `dashboard.html` only -- no event is appended, `state.json` is untouched."""
    state = fold_dir(dir_)
    write_dashboard(dir_, render_dashboard(state))
    return {"ok": True, "path": str(dashboard_path(dir_))}


def cmd_finish(dir_: Path, summary: str, *, now: Clock) -> dict[str, JsonValue]:
    """`grind finish --summary <text>`."""
    _validate_or_raise("grind_finished", {"summary": summary})

    event: RawEvent = {"ts": _iso(now()), "type": "grind_finished", "summary": summary}
    state, repair = _append_and_persist(dir_, event)
    return {"ok": True, "state_summary": summarize(state), "torn_tail": _torn_tail_json(repair)}
