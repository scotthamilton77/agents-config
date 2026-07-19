"""grind_paused / grind_resumed / grind_finished, and post-finish rejection."""

from __future__ import annotations

from grind.fold import fold
from tests.unit.builders import event, seed_event


def test_grind_paused_sets_pause_state_and_resume_checklist() -> None:
    events = [
        seed_event(),
        event(
            "grind_paused", reason="waiting on human", resume_checklist=["check CI", "ping human"]
        ),
    ]

    state = fold(events)

    assert state.paused is True
    assert state.pause_reason == "waiting on human"
    assert state.resume_checklist == ("check CI", "ping human")


def test_grind_resumed_clears_pause() -> None:
    events = [
        seed_event(),
        event("grind_paused", reason="waiting", resume_checklist=[]),
        event("grind_resumed"),
    ]

    state = fold(events)

    assert state.paused is False
    assert state.pause_reason is None


def test_grind_resumed_without_pause_is_an_anomaly() -> None:
    state = fold([seed_event(), event("grind_resumed")])

    assert state.paused is False
    assert len(state.anomalies) == 1
    assert state.anomalies[0].type == "grind_resumed"


def test_grind_finished_is_terminal_and_further_events_are_anomalies() -> None:
    events = [
        seed_event(),
        event("grind_finished", summary="shipped it"),
        event("item_started", item="wgclw.1"),
    ]

    state = fold(events)

    assert state.finished is True
    assert state.finish_summary == "shipped it"
    assert state.items["wgclw.1"].status == "queued"
    assert len(state.anomalies) == 1
    assert state.anomalies[0].type == "item_started"
    assert "terminal" in state.anomalies[0].reason


def test_second_grind_finished_is_also_rejected() -> None:
    events = [
        seed_event(),
        event("grind_finished", summary="done"),
        event("grind_finished", summary="done again"),
    ]

    state = fold(events)

    assert state.finish_summary == "done"
    assert len(state.anomalies) == 1


def test_ts_less_tail_event_clears_last_event_ts() -> None:
    # A JSON-valid tail event with no usable ts must clear the freshness
    # field: the board shows no timestamp rather than the previous event's,
    # which would misdate a state that includes the newer tail event.
    events = [
        seed_event(),
        event("observation", level="INFO", message="stamped"),
        {"type": "observation", "level": "INFO", "message": "no ts at all"},
    ]

    state = fold(events)

    assert state.last_event_ts is None
