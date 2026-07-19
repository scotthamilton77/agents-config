"""`fold(events) -> State` -- the pure FSM transition function.

Status is derived by the fold, never asserted: there is no `status_changed`
event. Anomaly policy is accept-and-flag (spec "Anomaly policy"): an event
illegal from the entity's current status, or naming an unknown item/lane, or
of an unknown type, is still appended to the log upstream of this function --
the fold records it as an anomaly, leaves the entity's status unchanged, and
auto-raises an ERROR observation. It never raises or refuses.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import cast

from grind.model import (
    AnomalyRecord,
    AttentionEntry,
    ClosedEntry,
    Item,
    ItemReview,
    ItemStatus,
    JsonValue,
    Lane,
    MergedEntry,
    Observation,
    ParkingEntry,
    ParkKind,
    PrRef,
    RawEvent,
    State,
)

_PARK_KINDS = {"discovered-work", "human-gated", "later-wave", "deferred"}


def _park_kind(evt: RawEvent) -> ParkKind | None:
    """Cast a trusted-inward `kind` string to the closed vocabulary.

    Payload shape validation is the CLI boundary's job (spec: "parse once,
    trust inward"); an unrecognized value here is tolerated as `None` rather
    than raised, consistent with accept-and-flag.
    """
    kind = evt.get("kind")
    if isinstance(kind, str) and kind in _PARK_KINDS:
        return cast("ParkKind", kind)
    return None


# Statuses `merged`/`done` resolve any blocker edge pointing at that item
# (spec: "an edge resolves only when its target reaches merged/done").
_TERMINAL_RESOLVING = {"merged", "done"}

Handler = Callable[[State, RawEvent], None]

_HANDLERS: dict[str, Handler] = {}


def _handler(event_type: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        _HANDLERS[event_type] = fn
        return fn

    return register


def _str(evt: RawEvent, key: str) -> str | None:
    value = evt.get(key)
    return value if isinstance(value, str) else None


def _anomaly(state: State, evt: RawEvent, reason: str) -> None:
    etype = _str(evt, "type") or "<missing type>"
    item_id = _str(evt, "item")
    lane_id = _str(evt, "lane")
    state.anomalies.append(
        AnomalyRecord(ts=_str(evt, "ts"), type=etype, item=item_id, lane=lane_id, reason=reason)
    )
    message = f"anomaly: {etype} on {item_id or lane_id or 'grind'}: {reason}"
    state.observations.append(
        Observation(level="ERROR", message=message, item=item_id, lane=lane_id, ts=_str(evt, "ts"))
    )
    state.attention.append(AttentionEntry(text=message, item=item_id, lane=lane_id, auto=True))


@_handler("grind_created")
def _h_grind_created(state: State, evt: RawEvent) -> None:
    # The "legal only as the log's first event" invariant is enforced by `fold`
    # before dispatch (only the loop knows log position); this handler only ever
    # runs for a legal seeding event.
    state.seeded = True
    state.title = _str(evt, "title")
    state.repo = _str(evt, "repo")
    state.mission = evt.get("mission")
    state.protocols = evt.get("protocols")
    config = evt.get("config")
    if isinstance(config, dict):
        state.config = {**state.config, **config}

    lanes = evt.get("lanes")
    if not isinstance(lanes, list):
        return
    for lane_payload in lanes:
        if not isinstance(lane_payload, dict):
            continue
        lane_id = _str(lane_payload, "id")
        if lane_id is None:
            continue
        lane = Lane(
            id=lane_id,
            name=_str(lane_payload, "name"),
            agent=_str(lane_payload, "agent"),
            model=_str(lane_payload, "model"),
            effort=_str(lane_payload, "effort"),
        )
        state.lanes[lane_id] = lane
        queue = lane_payload.get("queue")
        if not isinstance(queue, list):
            continue
        for item_payload in queue:
            if not isinstance(item_payload, dict):
                continue
            item_id = _str(item_payload, "id")
            if item_id is None:
                continue
            on = item_payload.get("on")
            blocked_on = tuple(o for o in on if isinstance(o, str)) if isinstance(on, list) else ()
            status: ItemStatus = "blocked" if blocked_on else "queued"
            item = Item(
                id=item_id,
                lane=lane_id,
                title=_str(item_payload, "title"),
                status=status,
                blocked_on=blocked_on,
            )
            state.items[item_id] = item
            lane.item_ids.append(item_id)


@_handler("grind_paused")
def _h_grind_paused(state: State, evt: RawEvent) -> None:
    checklist = evt.get("resume_checklist")
    state.paused = True
    state.pause_reason = _str(evt, "reason")
    state.resume_checklist = (
        tuple(c for c in checklist if isinstance(c, str)) if isinstance(checklist, list) else ()
    )


@_handler("grind_resumed")
def _h_grind_resumed(state: State, evt: RawEvent) -> None:
    if not state.paused:
        _anomaly(state, evt, "grind_resumed illegal: grind is not paused")
        return
    state.paused = False
    state.pause_reason = None
    state.resume_checklist = ()


@_handler("grind_finished")
def _h_grind_finished(state: State, evt: RawEvent) -> None:
    state.finished = True
    state.finish_summary = _str(evt, "summary")


@_handler("lane_standing_down")
def _h_lane_standing_down(state: State, evt: RawEvent) -> None:
    lane = _resolve_lane(state, evt)
    if lane is None:
        return
    lane.standing_down = True


@_handler("lane_handover")
def _h_lane_handover(state: State, evt: RawEvent) -> None:
    lane = _resolve_lane(state, evt)
    if lane is None:
        return
    lane.agent = _str(evt, "to_agent")
    if "to_model" in evt:
        lane.model = _str(evt, "to_model")
    if "to_effort" in evt:
        lane.effort = _str(evt, "to_effort")


def _resolve_lane(state: State, evt: RawEvent) -> Lane | None:
    lane_id = _str(evt, "lane")
    lane = state.lanes.get(lane_id) if lane_id is not None else None
    if lane is None:
        _anomaly(state, evt, f"unknown lane {lane_id!r}")
        return None
    return lane


def _active_item(state: State, evt: RawEvent) -> Item | None:
    """The item referenced by `evt`, excluding parked items -- every handler but
    `item_enqueued` treats a parked item as absent (accept-and-flag anomaly)."""
    item_id = _str(evt, "item")
    if item_id is None:
        _anomaly(state, evt, "event has no item reference")
        return None
    item = state.items.get(item_id)
    if item is None:
        _anomaly(state, evt, f"unknown item {item_id!r}")
        return None
    if item.parked is not None:
        _anomaly(state, evt, f"item {item_id!r} is parked")
        return None
    return item


def _unresolved_edges(state: State, item: Item) -> tuple[str, ...]:
    return tuple(
        target
        for target in item.blocked_on
        if (target_item := state.items.get(target)) is None
        or target_item.status not in _TERMINAL_RESOLVING
    )


def _recompute_blocked(state: State, item: Item) -> None:
    if _unresolved_edges(state, item):
        item.status = "blocked"
    elif item.status == "blocked":
        # Unblocking is derived, never asserted -- the fold returns a fully
        # resolved item to `queued` (spec: "the fold returns the item to
        # queued"), regardless of what status it held before becoming blocked.
        item.status = "queued"


def _cascade_unblock(state: State) -> None:
    """Re-derive every currently-blocked item's status to a fixpoint.

    A single item reaching merged/done can resolve a chain of edges (A
    unblocks B which unblocks C), so this loops until one full pass makes no
    further change.
    """
    changed = True
    while changed:
        changed = False
        for item in state.items.values():
            if item.parked is not None or item.status != "blocked":
                continue
            if not _unresolved_edges(state, item):
                item.status = "queued"
                changed = True


def _park_item(state: State, item: Item, kind: ParkKind | None, note: str | None) -> None:
    item.parked = ParkingEntry(kind=kind, note=note)
    if item.lane is not None:
        lane = state.lanes.get(item.lane)
        if lane is not None and item.id in lane.item_ids:
            lane.item_ids.remove(item.id)


@_handler("item_started")
def _h_item_started(state: State, evt: RawEvent) -> None:
    item = _active_item(state, evt)
    if item is None:
        return
    if item.status != "queued":
        _anomaly(state, evt, f"item_started illegal from status {item.status!r}")
        return
    item.status = "in-progress"


@_handler("pr_opened")
def _h_pr_opened(state: State, evt: RawEvent) -> None:
    item = _active_item(state, evt)
    if item is None:
        return
    if item.status not in ("in-progress", "waiting-human"):
        _anomaly(state, evt, f"pr_opened illegal from status {item.status!r}")
        return
    pr = evt.get("pr")
    item.pr = PrRef(number=pr if isinstance(pr, int) else None, url=_str(evt, "url"))
    item.status = "pr-open"


_REVIEWABLE = {"pr-open", "in-review", "waiting-human"}


@_handler("review_round")
def _h_review_round(state: State, evt: RawEvent) -> None:
    item = _active_item(state, evt)
    if item is None:
        return
    if item.status not in _REVIEWABLE:
        _anomaly(state, evt, f"review_round illegal from status {item.status!r}")
        return
    round_ = evt.get("round")
    item.review.round = round_ if isinstance(round_, int) else item.review.round
    item.review.kind = _str(evt, "kind")
    item.review.head_sha = _str(evt, "head_sha")
    item.review.detail = _str(evt, "detail")
    item.status = "in-review"


_OPEN_DISPOSITIONS = {"deferred", "escalated"}


@_handler("review_verdict")
def _h_review_verdict(state: State, evt: RawEvent) -> None:
    item = _active_item(state, evt)
    if item is None:
        return
    if item.status not in _REVIEWABLE:
        _anomaly(state, evt, f"review_verdict illegal from status {item.status!r}")
        return
    round_ = evt.get("round")
    findings = evt.get("findings")
    findings_list = findings if isinstance(findings, list) else []
    open_threads = sum(
        1
        for f in findings_list
        if isinstance(f, dict) and f.get("disposition") in _OPEN_DISPOSITIONS
    )
    wont_fix_count = sum(
        1 for f in findings_list if isinstance(f, dict) and f.get("disposition") == "wont-fix"
    )
    new_round = round_ if isinstance(round_, int) else item.review.round
    new_head_sha = _str(evt, "head_sha")
    # Same round, both SHAs present and disagreeing: the verdict was rendered
    # against different code than review_round recorded. Accept-and-flag (spec
    # "review_round/review_verdict disagree on head_sha") -- surface the
    # mismatch but still count using the latest event's value.
    if (
        new_round == item.review.round
        and item.review.head_sha is not None
        and new_head_sha is not None
        and item.review.head_sha != new_head_sha
    ):
        _anomaly(
            state,
            evt,
            f"review_verdict head_sha {new_head_sha!r} disagrees with review_round "
            f"head_sha {item.review.head_sha!r} for round {new_round}",
        )
    item.review.round = new_round
    item.review.kind = _str(evt, "kind")
    item.review.head_sha = new_head_sha
    item.review.verdict = _str(evt, "verdict")
    item.review.open_threads = open_threads
    item.review.wont_fix_count = wont_fix_count
    item.review.stalemate = item.review.verdict == "stalemate"
    item.status = "in-review"


_PR_CLOSED_NEXT: set[ItemStatus] = {"in-progress", "queued"}


@_handler("pr_closed")
def _h_pr_closed(state: State, evt: RawEvent) -> None:
    item = _active_item(state, evt)
    if item is None:
        return
    if item.status not in _REVIEWABLE:
        _anomaly(state, evt, f"pr_closed illegal from status {item.status!r}")
        return
    next_status = _str(evt, "next")
    if next_status != "parked" and next_status not in _PR_CLOSED_NEXT:
        _anomaly(state, evt, f"pr_closed has invalid next {next_status!r}")
        return
    pr = evt.get("pr")
    reason = _str(evt, "reason")
    state.closed_ledger.append(
        ClosedEntry(
            item=item.id, pr=pr if isinstance(pr, int) else None, reason=reason, ts=_str(evt, "ts")
        )
    )
    if next_status == "parked":
        _park_item(state, item, kind=None, note=reason)
    else:
        item.status = next_status  # type: ignore[assignment]  # validated above


# Statuses from which recording/replacing blocker edges is legal. A currently
# `blocked` item accepts a later `item_blocked` too -- the spec's re-scoping
# text ("a later item_blocked ... replaces its full edge set -- how ROOT
# re-scopes or drops a dependency") is otherwise unreachable, since any item
# with an unresolved edge is already `blocked` by definition.
_BLOCKABLE: set[ItemStatus] = {"queued", "in-progress", "pr-open", "in-review", "blocked"}


@_handler("item_blocked")
def _h_item_blocked(state: State, evt: RawEvent) -> None:
    item = _active_item(state, evt)
    if item is None:
        return
    if item.status not in _BLOCKABLE:
        _anomaly(state, evt, f"item_blocked illegal from status {item.status!r}")
        return
    on = evt.get("on")
    item.blocked_on = tuple(o for o in on if isinstance(o, str)) if isinstance(on, list) else ()
    item.blocked_note = _str(evt, "note")
    _recompute_blocked(state, item)


_WAITABLE: set[ItemStatus] = _BLOCKABLE


@_handler("item_waiting_human")
def _h_item_waiting_human(state: State, evt: RawEvent) -> None:
    item = _active_item(state, evt)
    if item is None:
        return
    if item.status not in _WAITABLE:
        _anomaly(state, evt, f"item_waiting_human illegal from status {item.status!r}")
        return
    why = _str(evt, "why")
    item.status = "waiting-human"
    state.attention.append(
        AttentionEntry(
            text=why or f"{item.id} is waiting on a human",
            item=item.id,
            auto=True,
            kind="waiting-human",
        )
    )


@_handler("item_resumed")
def _h_item_resumed(state: State, evt: RawEvent) -> None:
    item = _active_item(state, evt)
    if item is None:
        return
    if item.status != "waiting-human":
        _anomaly(state, evt, f"item_resumed illegal from status {item.status!r}")
        return
    # Clear only the attention this item's item_waiting_human raised -- an
    # unrelated ERROR/anomaly alert on the same item survives resume (spec:
    # resume "clears the item's auto-raised attention entry", the waiting-human
    # one, not every auto alert sharing the item).
    state.attention = [
        a for a in state.attention if not (a.kind == "waiting-human" and a.item == item.id)
    ]
    # Derived-blocked takes precedence over resume.
    if _unresolved_edges(state, item):
        item.status = "blocked"
    else:
        item.status = "in-progress"


_MERGEABLE: set[ItemStatus] = {"pr-open", "in-review", "waiting-human"}


@_handler("item_merged")
def _h_item_merged(state: State, evt: RawEvent) -> None:
    item = _active_item(state, evt)
    if item is None:
        return
    if item.status not in _MERGEABLE:
        _anomaly(state, evt, f"item_merged illegal from status {item.status!r}")
        return
    pr = evt.get("pr")
    item.status = "merged"
    state.merged_ledger.append(
        MergedEntry(
            item=item.id,
            pr=pr if isinstance(pr, int) else None,
            sha=_str(evt, "sha"),
            ts=_str(evt, "ts"),
        )
    )
    _cascade_unblock(state)


@_handler("item_done")
def _h_item_done(state: State, evt: RawEvent) -> None:
    item = _active_item(state, evt)
    if item is None:
        return
    if item.status != "merged":
        _anomaly(state, evt, f"item_done illegal from status {item.status!r}")
        return
    item.status = "done"
    item.review = ItemReview()
    state.attention = [a for a in state.attention if a.item != item.id]
    _cascade_unblock(state)


_PARKABLE: set[ItemStatus] = {"queued", "in-progress", "waiting-human", "blocked"}


@_handler("item_parked")
def _h_item_parked(state: State, evt: RawEvent) -> None:
    item = _active_item(state, evt)
    if item is None:
        return
    if item.status not in _PARKABLE:
        _anomaly(state, evt, f"item_parked illegal from status {item.status!r}")
        return
    _park_item(state, item, kind=_park_kind(evt), note=_str(evt, "note"))


@_handler("item_enqueued")
def _h_item_enqueued(state: State, evt: RawEvent) -> None:
    item_id = _str(evt, "item")
    item = state.items.get(item_id) if item_id is not None else None
    if item is None or item.parked is None:
        _anomaly(state, evt, f"item {item_id!r} is not parked")
        return
    lane = _resolve_lane(state, evt)
    if lane is None:
        return
    item.parked = None
    item.lane = lane.id
    # Queued is the baseline; blocked is derived, never asserted -- an item
    # re-entering play with unresolved blocker edges surfaces as blocked.
    item.status = "queued"
    _recompute_blocked(state, item)
    position = evt.get("position")
    if isinstance(position, int) and 0 <= position <= len(lane.item_ids):
        lane.item_ids.insert(position, item.id)
    else:
        lane.item_ids.append(item.id)


@_handler("discovered_work")
def _h_discovered_work(state: State, evt: RawEvent) -> None:
    item_id = _str(evt, "item")
    if item_id is None:
        _anomaly(state, evt, "discovered_work has no item id")
        return
    if item_id in state.items:
        _anomaly(state, evt, f"item {item_id!r} already exists")
        return
    disposition = _str(evt, "disposition")
    description = _str(evt, "description")
    # `bead?` is "optional metadata, carried only when it differs from `item`"
    # (spec) -- a caller-supplied bead equal to the item id is redundant, so
    # it's normalized away rather than stored twice under two names.
    bead = _str(evt, "bead")
    if bead == item_id:
        bead = None
    if disposition == "parked":
        item = Item(id=item_id, lane=None, title=description, status="queued", bead=bead)
        item.parked = ParkingEntry(kind=_park_kind(evt), note=_str(evt, "rationale"))
        state.items[item_id] = item
    elif disposition == "enqueued":
        lane = _resolve_lane(state, evt)
        if lane is None:
            return
        item = Item(id=item_id, lane=lane.id, title=description, status="queued", bead=bead)
        state.items[item_id] = item
        lane.item_ids.append(item_id)
    else:
        _anomaly(state, evt, f"discovered_work has invalid disposition {disposition!r}")


_OBSERVATION_LEVELS = {"INFO", "WARN", "ERROR", "LESSON"}


@_handler("observation")
def _h_observation(state: State, evt: RawEvent) -> None:
    level = _str(evt, "level")
    if level not in _OBSERVATION_LEVELS:
        _anomaly(state, evt, f"observation has invalid level {level!r}")
        return
    message = _str(evt, "message") or ""
    item_id = _str(evt, "item")
    lane_id = _str(evt, "lane")
    obs = Observation(
        level=level,  # type: ignore[arg-type]  # validated above
        message=message,
        item=item_id,
        lane=lane_id,
        ts=_str(evt, "ts"),
    )
    state.observations.append(obs)
    if level == "ERROR":
        state.attention.append(AttentionEntry(text=message, item=item_id, lane=lane_id, auto=True))
    elif level == "LESSON":
        state.lessons.append(obs)


@_handler("attention_raised")
def _h_attention_raised(state: State, evt: RawEvent) -> None:
    text = _str(evt, "text")
    if text is None:
        _anomaly(state, evt, "attention_raised has no text")
        return
    state.attention.append(AttentionEntry(text=text, item=_str(evt, "item")))


@_handler("attention_cleared")
def _h_attention_cleared(state: State, evt: RawEvent) -> None:
    text = _str(evt, "text")
    item_id = _str(evt, "item")
    if text is None and item_id is None:
        _anomaly(state, evt, "attention_cleared needs a text or item to match")
        return
    state.attention = [
        a
        for a in state.attention
        if not (
            (text is not None and a.text == text) or (item_id is not None and a.item == item_id)
        )
    ]


def fold(events: Sequence[Mapping[str, JsonValue]]) -> State:
    """Refold from zero every time -- grind logs are hundreds of events, not millions."""
    state = State()
    for index, raw in enumerate(events):
        evt: RawEvent = dict(raw)
        etype = _str(evt, "type")
        if etype == "grind_created" and index != 0:
            # Legal only as the log's first event -- a later creation (even after
            # a leading anomaly left the board unseeded) folds as an anomaly and
            # never seeds the board.
            _anomaly(state, evt, "grind_created is legal only as the log's first event")
            continue
        if not state.seeded and etype != "grind_created":
            _anomaly(state, evt, "log must begin with grind_created")
            continue
        if state.finished:
            _anomaly(state, evt, "grind_finished is terminal; further events are anomalies")
            continue
        if etype is None:
            _anomaly(state, evt, "event has no type")
            continue
        handler = _HANDLERS.get(etype)
        if handler is None:
            _anomaly(state, evt, f"unknown event type {etype!r}")
            continue
        handler(state, evt)
    return state
