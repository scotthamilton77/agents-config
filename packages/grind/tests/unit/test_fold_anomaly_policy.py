"""Cross-cutting anomaly-policy coverage: every item-scoped event type applies
the same "unknown item is an anomaly" rule, and each handler enforces its own
slice of the transition table (illegal-source-status anomalies not already
pinned by the happier-path test files).
"""

from __future__ import annotations

import pytest

from grind.fold import fold
from tests.unit.builders import event, seed_event

_ITEM_SCOPED_TYPES = [
    "item_started",
    "pr_opened",
    "review_round",
    "review_verdict",
    "pr_closed",
    "item_blocked",
    "item_waiting_human",
    "item_resumed",
    "item_merged",
    "item_done",
    "item_parked",
]


@pytest.mark.parametrize("evt_type", _ITEM_SCOPED_TYPES)
def test_every_item_scoped_event_anomalies_on_unknown_item(evt_type: str) -> None:
    state = fold([seed_event(), event(evt_type, item="ghost-item")])

    assert len(state.anomalies) == 1
    assert state.anomalies[0].type == evt_type
    assert "ghost-item" not in state.items


def test_pr_opened_illegal_when_already_pr_open() -> None:
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("pr_opened", item="wgclw.1", pr=2),
    ]

    state = fold(events)

    assert state.items["wgclw.1"].pr is not None
    assert state.items["wgclw.1"].pr.number == 1  # first PR wins; second call is an anomaly
    assert any(a.type == "pr_opened" for a in state.anomalies)


def test_review_verdict_illegal_before_a_pr_exists() -> None:
    state = fold(
        [seed_event(), event("review_verdict", item="wgclw.1", verdict="clean", findings=[])]
    )

    assert state.items["wgclw.1"].status == "queued"
    assert any(a.type == "review_verdict" for a in state.anomalies)


def test_pr_closed_illegal_before_a_pr_exists() -> None:
    state = fold(
        [seed_event(), event("pr_closed", item="wgclw.1", pr=1, reason="n/a", next="queued")]
    )

    assert not state.closed_ledger
    assert any(a.type == "pr_closed" for a in state.anomalies)


def test_pr_closed_with_invalid_next_is_an_anomaly_and_does_not_close() -> None:
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("pr_closed", item="wgclw.1", pr=1, reason="huh", next="not-a-real-status"),
    ]

    state = fold(events)

    assert not state.closed_ledger
    assert state.items["wgclw.1"].status == "pr-open"


def test_item_merged_illegal_from_queued() -> None:
    state = fold([seed_event(), event("item_merged", item="wgclw.1", pr=1, sha="a")])

    assert state.items["wgclw.1"].status == "queued"
    assert any(a.type == "item_merged" for a in state.anomalies)


def test_item_done_illegal_before_merged() -> None:
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("item_done", item="wgclw.1"),
    ]

    state = fold(events)

    assert state.items["wgclw.1"].status == "in-progress"
    assert any(a.type == "item_done" for a in state.anomalies)


def test_item_parked_illegal_from_merged() -> None:
    # `pr-open`/`in-review` became parkable with the failure axis (every one of
    # its reasons is reached with a PR open). Merged work has nothing left to
    # park -- that is the boundary the transition table still holds.
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("item_merged", item="wgclw.1", pr=1, sha="abc"),
        event("item_parked", item="wgclw.1", reason="deferred", note="nope"),
    ]

    state = fold(events)

    assert state.items["wgclw.1"].parked is None
    assert state.items["wgclw.1"].status == "merged"
    assert any(a.type == "item_parked" for a in state.anomalies)


def test_item_started_with_no_item_reference_is_an_anomaly() -> None:
    state = fold([seed_event(), event("item_started")])

    assert len(state.anomalies) == 1
    assert "item reference" in state.anomalies[0].reason


def test_item_enqueued_with_unknown_lane_is_an_anomaly_and_item_stays_parked() -> None:
    events = [
        seed_event(),
        event("item_parked", item="wgclw.1", reason="deferred", note="paused"),
        event("item_enqueued", item="wgclw.1", lane="ghost-lane"),
    ]

    state = fold(events)

    assert state.items["wgclw.1"].parked is not None
    assert any(a.type == "item_enqueued" for a in state.anomalies)


def test_discovered_work_with_unknown_lane_on_enqueue_is_an_anomaly() -> None:
    events = [
        seed_event(),
        event(
            "discovered_work",
            item="disc-1",
            description="x",
            source="lane-a",
            disposition="enqueued",
            lane="ghost-lane",
            rationale="r",
        ),
    ]

    state = fold(events)

    assert "disc-1" not in state.items
    assert any(a.type == "discovered_work" for a in state.anomalies)


def test_discovered_work_invalid_disposition_is_an_anomaly() -> None:
    events = [
        seed_event(),
        event(
            "discovered_work",
            item="disc-1",
            description="x",
            source="lane-a",
            disposition="not-a-real-disposition",
            rationale="r",
        ),
    ]

    state = fold(events)

    assert "disc-1" not in state.items
    assert any(a.type == "discovered_work" for a in state.anomalies)


def test_observation_with_invalid_level_is_an_anomaly() -> None:
    state = fold([seed_event(), event("observation", level="CRITICAL", message="huh")])

    # The rejected observation itself never lands -- only the anomaly's own
    # auto-raised ERROR observation does.
    assert len(state.observations) == 1
    assert state.observations[0].message != "huh"
    assert any(a.type == "observation" for a in state.anomalies)


def test_attention_raised_without_text_is_an_anomaly() -> None:
    state = fold([seed_event(), event("attention_raised")])

    # No real entry was added -- only the anomaly's own auto-raised one.
    assert len(state.attention) == 1
    assert state.attention[0].auto is True
    assert any(a.type == "attention_raised" for a in state.anomalies)


def test_attention_cleared_without_text_or_item_is_an_anomaly() -> None:
    state = fold([seed_event(), event("attention_raised", text="x"), event("attention_cleared")])

    # The earlier real entry ("x") is untouched; the anomaly adds its own auto entry.
    assert len(state.attention) == 2
    assert any(a.text == "x" and not a.auto for a in state.attention)
    assert any(a.type == "attention_cleared" for a in state.anomalies)


def test_event_missing_type_after_seeding_is_an_anomaly() -> None:
    malformed = {"ts": "t"}  # no "type" key at all
    state = fold([seed_event(), malformed])

    assert any(a.reason == "event has no type" for a in state.anomalies)


def test_lane_handover_to_unknown_lane_is_an_anomaly() -> None:
    state = fold(
        [seed_event(), event("lane_handover", lane="ghost-lane", to_agent="someone", reason="r")]
    )

    assert any(a.type == "lane_handover" for a in state.anomalies)


def test_lane_handover_without_model_or_effort_leaves_them_unchanged() -> None:
    events = [
        seed_event(
            lanes=[
                {
                    "id": "lane-a",
                    "name": "Lane A",
                    "agent": "lieutenant-a",
                    "model": "sonnet",
                    "effort": "medium",
                    "queue": [{"id": "wgclw.1"}],
                }
            ]
        ),
        event("lane_handover", lane="lane-a", to_agent="lieutenant-b", reason="rotation"),
    ]

    state = fold(events)

    lane = state.lanes["lane-a"]
    assert lane.agent == "lieutenant-b"
    assert lane.model == "sonnet"
    assert lane.effort == "medium"


def test_item_blocked_on_an_already_blocked_item_can_immediately_resolve() -> None:
    # Replacing edges with an already-resolved target skips straight back to
    # queued, without needing a merge/done event to trigger the recompute.
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("item_merged", item="wgclw.1", pr=1, sha="a"),
        event("item_blocked", item="wgclw.2", on=["does-not-exist"]),
        event("item_blocked", item="wgclw.2", on=["wgclw.1"]),  # wgclw.1 already merged
    ]

    state = fold(events)

    assert state.items["wgclw.2"].status == "queued"


def test_park_reason_missing_becomes_none_not_a_crash() -> None:
    state = fold([seed_event(), event("item_parked", item="wgclw.1", note="no reason given")])

    parked = state.items["wgclw.1"].parked
    assert parked is not None
    assert parked.reason is None
    # An untyped park is absent from both axes, never ambiguously on one.
    assert parked.axis is None
    assert parked.category is None
    # Nothing arrived to be discarded, so nothing is flagged.
    assert state.anomalies == []


def test_an_unrecognized_park_reason_is_flagged_not_silently_dropped() -> None:
    # Accept-and-flag: the park still lands (untyped), but throwing away a
    # value the payload contract required is exactly what must not be quiet.
    state = fold(
        [seed_event(), event("item_parked", item="wgclw.1", reason="ci_failure", note="typo")]
    )

    parked = state.items["wgclw.1"].parked
    assert parked is not None
    assert parked.reason is None
    assert any(
        a.type == "item_parked" and "unrecognized park reason" in a.reason for a in state.anomalies
    )


def test_a_pre_charter_log_replays_with_its_parks_still_typed() -> None:
    # The old writer emitted the field `kind`, never `reason`. Delete-and-refold
    # is the whole recovery story, so an upgrade must not grey out history.
    state = fold(
        [
            seed_event(),
            event("item_parked", item="wgclw.1", kind="later-wave", note="wave 2"),
            event("item_parked", item="wgclw.2", kind="human-gated", note="needs a ruling"),
        ]
    )

    survived = state.items["wgclw.1"].parked
    assert survived is not None
    assert survived.reason == "later-wave"
    assert survived.axis == "scheduling"
    # `human-gated` was retired into the reason that names the same state.
    retired = state.items["wgclw.2"].parked
    assert retired is not None
    assert retired.reason == "approval-required"
    assert retired.axis == "failure"
    assert state.anomalies == []


def test_grind_created_tolerates_a_lanes_payload_that_is_not_a_list() -> None:
    state = fold([seed_event(lanes="not-a-list")])

    assert state.seeded is True
    assert state.lanes == {}


def test_grind_created_tolerates_malformed_lane_and_item_entries() -> None:
    seed = seed_event(
        lanes=[
            "not-a-dict",
            {"name": "no id here"},
            {"id": "lane-a", "queue": "not-a-list"},
        ]
    )

    state = fold([seed])

    assert "lane-a" in state.lanes
    assert state.lanes["lane-a"].item_ids == []


def test_grind_created_tolerates_malformed_queue_items() -> None:
    seed = seed_event(
        lanes=[
            {
                "id": "lane-a",
                "queue": ["not-a-dict", {"title": "no id here"}, {"id": "wgclw.1"}],
            }
        ]
    )

    state = fold([seed])

    assert state.lanes["lane-a"].item_ids == ["wgclw.1"]
