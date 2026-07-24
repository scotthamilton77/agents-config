"""item_parked / item_enqueued -- the parking lot's one exit -- and discovered_work."""

from __future__ import annotations

from grind.fold import fold
from tests.unit.builders import event, seed_event


def test_item_parked_removes_item_from_lanes_active_queue() -> None:
    events = [event("item_parked", item="wgclw.2", reason="later-wave", note="not yet")]
    state = fold([seed_event(), *events])

    item = state.items["wgclw.2"]
    assert item.parked is not None
    assert item.parked.reason == "later-wave"
    assert item.parked.note == "not yet"
    assert "wgclw.2" not in state.lanes["lane-a"].item_ids
    assert item.id in state.parking_lot()


def test_item_enqueued_returns_a_parked_item_to_queued_in_the_named_lane() -> None:
    events = [
        seed_event(),
        event("item_parked", item="wgclw.2", reason="discovered-work", note="scope cut"),
        event("item_enqueued", item="wgclw.2", lane="lane-a"),
    ]

    state = fold(events)

    item = state.items["wgclw.2"]
    assert item.parked is None
    assert item.status == "queued"
    assert "wgclw.2" in state.lanes["lane-a"].item_ids
    assert "wgclw.2" not in state.parking_lot()


def test_item_enqueued_with_unresolved_edges_folds_to_blocked_not_queued() -> None:
    events = [
        seed_event(),
        event("item_blocked", item="wgclw.2", on=["wgclw.1"]),
        event("item_parked", item="wgclw.2", reason="later-wave", note="hold"),
        event("item_enqueued", item="wgclw.2", lane="lane-a"),
    ]

    state = fold(events)

    item = state.items["wgclw.2"]
    assert item.parked is None
    assert item.status == "blocked"
    assert "wgclw.2" in state.lanes["lane-a"].item_ids


def test_reenqueued_blocked_item_unblocks_to_queued_when_its_edge_resolves() -> None:
    events = [
        seed_event(),
        event("item_blocked", item="wgclw.2", on=["wgclw.1"]),
        event("item_parked", item="wgclw.2", reason="later-wave", note="hold"),
        event("item_enqueued", item="wgclw.2", lane="lane-a"),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=101),
        event("item_merged", item="wgclw.1", pr=101),
    ]

    state = fold(events)

    assert state.items["wgclw.2"].status == "queued"


def test_events_other_than_enqueue_are_anomalies_while_item_is_parked() -> None:
    events = [
        seed_event(),
        event("item_parked", item="wgclw.2", reason="deferred", note="paused"),
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
    # Free-text closure prose does not name a park reason, so the park is untyped.
    assert item.parked.reason is None
    assert state.closed_ledger[0].reason == "superseded"


def test_pr_closed_types_the_park_when_its_reason_names_a_vocabulary_member() -> None:
    # `pr_closed.reason` shares a field name with the park vocabulary and not
    # its contract; when it does name a member, typing beats demoting it to prose.
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=5),
        event("pr_closed", item="wgclw.1", pr=5, reason="merge-conflict", next="parked"),
    ]

    state = fold(events)

    parked = state.items["wgclw.1"].parked
    assert parked is not None
    assert parked.reason == "merge-conflict"
    assert parked.category == "machine"


def test_an_item_with_an_open_pr_is_parkable() -> None:
    # Every failure-axis reason is reached with a PR open -- if `pr-open` and
    # `in-review` were not parkable the axis could never be recorded.
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=7),
        event("item_parked", item="wgclw.1", reason="ci-failure", note="budget spent"),
        event("item_started", item="wgclw.2"),
        event("pr_opened", item="wgclw.2", pr=8),
        event("review_round", item="wgclw.2", kind="codex", round=1, head_sha="abc"),
        event("item_parked", item="wgclw.2", reason="bot-declined", note="reviewer declined"),
    ]

    state = fold(events)

    assert state.anomalies == []
    assert "wgclw.1" in state.parking_lot()
    assert "wgclw.2" in state.parking_lot()


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


def test_discovered_work_enqueued_preserves_source_and_rationale() -> None:
    # spec: the created item "carries its triage rationale" and its source; state
    # is the renderer's only input, so dropping either loses the provenance.
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
    assert item.discovered is not None
    assert item.discovered.source == "lane-a PR review"
    assert item.discovered.rationale == "blocks the milestone"


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
            description="gap found mid-grind",
            source="lane-a",
            disposition="parked",
            reason="discovered-work",
            rationale="needs a triage decision",
        ),
    ]

    state = fold(events)

    item = state.items["disc-2"]
    assert item.parked is not None
    assert item.parked.reason == "discovered-work"
    # Work that never had a PR parks on the scheduling axis, not the failure one.
    assert item.parked.axis == "scheduling"
    assert "disc-2" not in state.lanes["lane-a"].item_ids


def test_discovered_work_parked_preserves_source_and_rationale() -> None:
    # Blast radius of the enqueued path: the parked path also carries provenance.
    events = [
        seed_event(),
        event(
            "discovered_work",
            item="disc-2",
            description="gap found mid-grind",
            source="lane-a",
            disposition="parked",
            reason="discovered-work",
            rationale="needs a triage decision",
        ),
    ]

    state = fold(events)

    item = state.items["disc-2"]
    assert item.discovered is not None
    assert item.discovered.source == "lane-a"
    assert item.discovered.rationale == "needs a triage decision"


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
