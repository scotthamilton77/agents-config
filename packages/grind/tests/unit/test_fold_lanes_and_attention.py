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


def test_observation_on_unknown_item_folds_as_anomaly() -> None:
    # accept-and-flag: an observation naming an unknown item is accepted into
    # the log but flagged -- the anomaly machinery replaces the normal effect
    # so a malformed reference surfaces in the anomaly/dashboard path instead of
    # attaching a phantom ERROR to a nonexistent item.
    events = [
        seed_event(),
        event("observation", level="ERROR", message="CI is red", item="does-not-exist"),
    ]

    state = fold(events)

    assert len(state.anomalies) == 1
    assert state.anomalies[0].type == "observation"
    assert state.anomalies[0].item == "does-not-exist"
    # the normal effect is replaced: the raw message is never recorded as its
    # own observation; only the anomaly helper's synthetic ERROR + attention
    # (which carry the phantom item so it shows up in reporting) remain.
    assert all(o.message != "CI is red" for o in state.observations)
    assert any(a.item == "does-not-exist" and a.auto for a in state.attention)


def test_observation_on_unknown_lane_folds_as_anomaly() -> None:
    events = [
        seed_event(),
        event("observation", level="WARN", message="lane hiccup", lane="ghost-lane"),
    ]

    state = fold(events)

    assert len(state.anomalies) == 1
    assert state.anomalies[0].type == "observation"
    assert state.anomalies[0].lane == "ghost-lane"
    assert all(o.message != "lane hiccup" for o in state.observations)


def test_attention_raised_and_cleared() -> None:
    events = [
        seed_event(),
        event("attention_raised", text="human, please review"),
        event("attention_cleared", text="human, please review"),
    ]

    state = fold(events)

    assert state.attention == []
