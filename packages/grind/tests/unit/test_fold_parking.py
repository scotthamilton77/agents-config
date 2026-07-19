"""item_parked / item_enqueued -- the parking lot's one exit -- and discovered_work."""

from __future__ import annotations

from grind.fold import fold
from tests.unit.builders import event, seed_event


def test_item_parked_removes_item_from_lanes_active_queue() -> None:
    events = [event("item_parked", item="wgclw.2", kind="later-wave", note="not yet")]
    state = fold([seed_event(), *events])

    item = state.items["wgclw.2"]
    assert item.parked is not None
    assert item.parked.kind == "later-wave"
    assert item.parked.note == "not yet"
    assert "wgclw.2" not in state.lanes["lane-a"].item_ids
    assert item.id in state.parking_lot()


def test_item_enqueued_returns_a_parked_item_to_queued_in_the_named_lane() -> None:
    events = [
        seed_event(),
        event("item_parked", item="wgclw.2", kind="discovered-work", note="scope cut"),
        event("item_enqueued", item="wgclw.2", lane="lane-a"),
    ]

    state = fold(events)

    item = state.items["wgclw.2"]
    assert item.parked is None
    assert item.status == "queued"
    assert "wgclw.2" in state.lanes["lane-a"].item_ids
    assert "wgclw.2" not in state.parking_lot()


def test_events_other_than_enqueue_are_anomalies_while_item_is_parked() -> None:
    events = [
        seed_event(),
        event("item_parked", item="wgclw.2", kind="deferred", note="paused"),
        event("item_started", item="wgclw.2"),
    ]

    state = fold(events)

    assert state.items["wgclw.2"].parked is not None
    assert any(a.type == "item_started" and a.item == "wgclw.2" for a in state.anomalies)


def test_pr_closed_with_next_parked_moves_item_into_parking_lot() -> None:
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=5),
        event("pr_closed", item="wgclw.1", pr=5, reason="superseded", next="parked"),
    ]

    state = fold(events)

    item = state.items["wgclw.1"]
    assert item.parked is not None
    assert item.parked.note == "superseded"
    assert state.closed_ledger[0].reason == "superseded"


def test_discovered_work_enqueued_creates_a_new_queued_item() -> None:
    events = [
        seed_event(),
        event(
            "discovered_work",
            item="disc-1",
            description="found a gap",
            source="lane-a PR review",
            disposition="enqueued",
            lane="lane-a",
            rationale="blocks the milestone",
        ),
    ]

    state = fold(events)

    item = state.items["disc-1"]
    assert item.status == "queued"
    assert item.lane == "lane-a"
    assert "disc-1" in state.lanes["lane-a"].item_ids


def test_discovered_work_bead_is_normalized_away_when_equal_to_item_id() -> None:
    # spec: bead? is "optional metadata, carried only when it differs from item".
    events = [
        seed_event(),
        event(
            "discovered_work",
            item="disc-1",
            bead="disc-1",
            description="dup bead id",
            source="lane-a",
            disposition="enqueued",
            lane="lane-a",
            rationale="r",
        ),
    ]

    state = fold(events)

    assert state.items["disc-1"].bead is None


def test_discovered_work_keeps_bead_when_it_differs_from_item_id() -> None:
    events = [
        seed_event(),
        event(
            "discovered_work",
            item="disc-1",
            bead="wgclw.99",
            description="real bead id",
            source="lane-a",
            disposition="enqueued",
            lane="lane-a",
            rationale="r",
        ),
    ]

    state = fold(events)

    assert state.items["disc-1"].bead == "wgclw.99"


def test_discovered_work_parked_creates_a_new_parked_item() -> None:
    events = [
        seed_event(),
        event(
            "discovered_work",
            item="disc-2",
            description="human call needed",
            source="lane-a",
            disposition="parked",
            kind="human-gated",
            rationale="needs a decision",
        ),
    ]

    state = fold(events)

    item = state.items["disc-2"]
    assert item.parked is not None
    assert item.parked.kind == "human-gated"
    assert "disc-2" not in state.lanes["lane-a"].item_ids


def test_discovered_work_with_duplicate_item_id_is_an_anomaly() -> None:
    events = [
        seed_event(),
        event(
            "discovered_work",
            item="wgclw.1",  # already exists from the seed
            description="dup",
            source="lane-a",
            disposition="enqueued",
            lane="lane-a",
            rationale="oops",
        ),
    ]

    state = fold(events)

    assert len(state.anomalies) == 1
    assert state.anomalies[0].type == "discovered_work"
