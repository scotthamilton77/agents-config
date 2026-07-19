"""lane_standing_down / lane_handover, and observation / attention_raised / attention_cleared."""

from __future__ import annotations

from grind.fold import fold
from tests.unit.builders import event, seed_event


def test_lane_standing_down_sets_flag() -> None:
    state = fold([seed_event(), event("lane_standing_down", lane="lane-a")])

    assert state.lanes["lane-a"].standing_down is True


def test_lane_handover_updates_agent_and_keeps_queue() -> None:
    events = [
        seed_event(),
        event(
            "lane_handover",
            lane="lane-a",
            from_agent="lieutenant-a",
            to_agent="lieutenant-b",
            to_model="opus",
            to_effort="high",
            reason="rotation",
        ),
    ]

    state = fold(events)

    lane = state.lanes["lane-a"]
    assert lane.agent == "lieutenant-b"
    assert lane.model == "opus"
    assert lane.effort == "high"
    assert lane.item_ids == ["wgclw.1", "wgclw.2"]


def test_lane_event_referencing_unknown_lane_is_an_anomaly() -> None:
    state = fold([seed_event(), event("lane_standing_down", lane="ghost-lane")])

    assert len(state.anomalies) == 1
    assert state.anomalies[0].type == "lane_standing_down"


def test_error_observation_auto_raises_attention() -> None:
    events = [
        seed_event(),
        event("observation", level="ERROR", message="CI is red", item="wgclw.1"),
    ]

    state = fold(events)

    assert state.observations[0].level == "ERROR"
    assert any(a.text == "CI is red" and a.item == "wgclw.1" for a in state.attention)


def test_lesson_observation_feeds_the_lessons_projection() -> None:
    events = [
        seed_event(),
        event("observation", level="LESSON", message="watch for flaky test X"),
    ]

    state = fold(events)

    assert len(state.lessons) == 1
    assert state.lessons[0].message == "watch for flaky test X"
    assert not any(a.text == "watch for flaky test X" for a in state.attention)


def test_attention_raised_and_cleared() -> None:
    events = [
        seed_event(),
        event("attention_raised", text="human, please review"),
        event("attention_cleared", text="human, please review"),
    ]

    state = fold(events)

    assert state.attention == []
