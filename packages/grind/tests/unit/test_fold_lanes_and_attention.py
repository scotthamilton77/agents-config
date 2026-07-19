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


def test_warn_and_info_observations_are_recorded_with_no_side_routing() -> None:
    events = [
        seed_event(),
        event("observation", level="WARN", message="repo quirk: flaky runner"),
        event("observation", level="INFO", message="lieutenant rotated"),
    ]

    state = fold(events)

    levels = [o.level for o in state.observations]
    assert levels == ["WARN", "INFO"]
    assert state.lessons == []
    assert state.attention == []


def test_observation_with_no_item_or_lane_is_recorded_with_null_references() -> None:
    events = [seed_event(), event("observation", level="INFO", message="grind-wide note")]

    state = fold(events)

    obs = state.observations[0]
    assert obs.item is None
    assert obs.lane is None


def test_error_observation_on_unknown_item_is_accepted_and_flagged() -> None:
    # observation carries no existence check on `item` -- accept-and-flag means
    # the reference is tolerated and the ERROR still raises attention, rather
    # than the event being rejected as an anomaly.
    events = [
        seed_event(),
        event("observation", level="ERROR", message="CI is red", item="does-not-exist"),
    ]

    state = fold(events)

    assert state.anomalies == []
    assert state.observations[0].item == "does-not-exist"
    assert any(a.item == "does-not-exist" and a.text == "CI is red" for a in state.attention)


def test_attention_raised_and_cleared() -> None:
    events = [
        seed_event(),
        event("attention_raised", text="human, please review"),
        event("attention_cleared", text="human, please review"),
    ]

    state = fold(events)

    assert state.attention == []
