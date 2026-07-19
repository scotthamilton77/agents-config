"""Core item transitions: started -> pr_opened -> merged -> done, and the
anomaly policy for events illegal from the item's current status.
"""

from __future__ import annotations

from grind.fold import fold
from tests.unit.builders import event, seed_event


def test_item_started_moves_queued_to_in_progress() -> None:
    state = fold([seed_event(), event("item_started", item="wgclw.1")])

    assert state.items["wgclw.1"].status == "in-progress"


def test_pr_opened_moves_in_progress_to_pr_open_and_records_pr_ref() -> None:
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=42, url="https://example.com/pr/42"),
    ]

    state = fold(events)

    item = state.items["wgclw.1"]
    assert item.status == "pr-open"
    assert item.pr is not None
    assert item.pr.number == 42
    assert item.pr.url == "https://example.com/pr/42"


def test_item_merged_then_item_done_reaches_terminal_status() -> None:
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=42),
        event("item_merged", item="wgclw.1", pr=42, sha="abc123"),
        event("item_done", item="wgclw.1"),
    ]

    state = fold(events)

    item = state.items["wgclw.1"]
    assert item.status == "done"
    assert state.merged_ledger[0].item == "wgclw.1"
    assert state.merged_ledger[0].sha == "abc123"


def test_illegal_transition_is_an_anomaly_leaving_status_unchanged() -> None:
    # pr_opened is illegal from `queued` (item never started) per the transition table.
    events = [seed_event(), event("pr_opened", item="wgclw.1", pr=42)]

    state = fold(events)

    item = state.items["wgclw.1"]
    assert item.status == "queued"
    assert item.pr is None
    assert len(state.anomalies) == 1
    assert state.anomalies[0].type == "pr_opened"
    assert state.anomalies[0].item == "wgclw.1"
    error_observations = [o for o in state.observations if o.level == "ERROR"]
    assert len(error_observations) == 1
    assert any(a.item == "wgclw.1" for a in state.attention)


def test_event_referencing_unknown_item_is_an_anomaly() -> None:
    state = fold([seed_event(), event("item_started", item="does-not-exist")])

    assert len(state.anomalies) == 1
    assert state.anomalies[0].reason
    assert "does-not-exist" not in state.items


def test_unknown_event_type_is_tolerated_as_an_anomaly() -> None:
    state = fold([seed_event(), event("some_future_event", item="wgclw.1")])

    assert state.items["wgclw.1"].status == "queued"
    assert len(state.anomalies) == 1
    assert "unknown event type" in state.anomalies[0].reason
