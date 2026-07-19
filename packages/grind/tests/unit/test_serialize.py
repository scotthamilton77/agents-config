"""`grind.serialize`: State -> JsonValue for `state.json` and `status --full`,
plus the `status` default summary shape."""

from __future__ import annotations

from grind.fold import fold
from grind.serialize import full_state_json, summarize

from .builders import event, seed_event


def test_summarize_reports_header_lane_and_item_counts():
    events = [seed_event(), event("item_started", item="wgclw.1")]
    state = fold(events)

    summary = summarize(state)

    assert summary["title"] == "Widget grind"
    assert summary["repo"] == "acme/widgets"
    assert summary["paused"] is False
    assert summary["finished"] is False
    assert summary["items_by_status"] == {"in-progress": 1, "queued": 1}
    assert summary["attention_count"] == 0
    assert summary["anomaly_count"] == 0
    lanes = summary["lanes"]
    assert isinstance(lanes, list)
    assert lanes[0]["id"] == "lane-a"
    assert lanes[0]["status"] == "in-progress"


def test_summarize_counts_attention_and_anomalies():
    events = [seed_event(), event("item_waiting_human", item="does-not-exist", why="?")]
    state = fold(events)

    summary = summarize(state)

    assert summary["attention_count"] == 1
    assert summary["anomaly_count"] == 1


def test_full_state_json_round_trips_item_fields():
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=42, url="https://example/42"),
        event(
            "review_round",
            item="wgclw.1",
            kind="codex",
            round=1,
            head_sha="deadbeef",
            detail="looks fine",
        ),
    ]
    state = fold(events)

    full = full_state_json(state)

    assert full["title"] == "Widget grind"
    items = full["items"]
    assert isinstance(items, dict)
    item = items["wgclw.1"]
    assert isinstance(item, dict)
    assert item["status"] == "in-review"
    pr = item["pr"]
    assert isinstance(pr, dict)
    assert pr["number"] == 42
    assert pr["url"] == "https://example/42"
    review = item["review"]
    assert isinstance(review, dict)
    assert review["round"] == 1
    assert review["head_sha"] == "deadbeef"


def test_full_state_json_serializes_ledgers_and_parking_lot():
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("item_merged", item="wgclw.1", pr=1, sha="abc"),
        event("item_parked", item="wgclw.2", kind="deferred", note="later"),
    ]
    state = fold(events)

    full = full_state_json(state)

    merged = full["merged_ledger"]
    assert isinstance(merged, list)
    assert merged[0]["item"] == "wgclw.1"
    items = full["items"]
    assert isinstance(items, dict)
    parked_item = items["wgclw.2"]
    assert isinstance(parked_item, dict)
    parked = parked_item["parked"]
    assert isinstance(parked, dict)
    assert parked["kind"] == "deferred"


def test_full_state_json_serializes_observations_and_lessons():
    events = [
        seed_event(),
        event("observation", level="WARN", message="repo quirk", lane="lane-a"),
        event("observation", level="ERROR", message="CI is red", item="wgclw.1"),
        event("observation", level="LESSON", message="watch for flaky test X"),
    ]
    state = fold(events)

    full = full_state_json(state)

    observations = full["observations"]
    assert isinstance(observations, list)
    assert [o["level"] for o in observations] == ["WARN", "ERROR", "LESSON"]  # type: ignore[index]
    warn = observations[0]
    assert isinstance(warn, dict)
    assert warn["message"] == "repo quirk"
    assert warn["lane"] == "lane-a"

    lessons = full["lessons"]
    assert isinstance(lessons, list)
    assert len(lessons) == 1
    lesson = lessons[0]
    assert isinstance(lesson, dict)
    assert lesson["message"] == "watch for flaky test X"
    assert lesson["level"] == "LESSON"


def test_full_state_json_is_json_serializable():
    import json

    events = [seed_event()]
    state = fold(events)

    json.dumps(full_state_json(state))  # raises if any value isn't JSON-safe
