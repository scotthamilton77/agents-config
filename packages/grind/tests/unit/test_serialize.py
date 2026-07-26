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


def test_item_projection_publishes_work_id_and_never_the_backends_noun():
    # Name lock (D11): `state.json` is grind's public JSON, so the tracker
    # backend's noun must not appear as a key any consumer could come to
    # depend on. The tracker id rides as `work_id` or not at all.
    events = [
        seed_event(),
        event(
            "discovered_work",
            item="disc-1",
            work_id="wgclw.99",
            description="found in review",
            source="lane-a",
            disposition="enqueued",
            lane="lane-a",
            rationale="r",
        ),
    ]
    state = fold(events)

    items = full_state_json(state)["items"]
    assert isinstance(items, dict)
    for item in items.values():
        assert isinstance(item, dict)
        assert "work_id" in item
        assert "bead" not in item
    assert items["disc-1"]["work_id"] == "wgclw.99"


def test_full_state_json_serializes_ledgers_and_parking_lot():
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("item_merged", item="wgclw.1", pr=1, sha="abc"),
        event("item_parked", item="wgclw.2", reason="deferred", note="later"),
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
    assert parked["reason"] == "deferred"
    # axis/category ride the snapshot so a consumer never re-implements the table
    assert parked["axis"] == "scheduling"
    assert parked["category"] == "human"


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


def test_full_state_serializes_attention_ts():
    events = [
        seed_event(),
        event("attention_raised", text="look here"),
    ]
    state = fold(events)

    payload = full_state_json(state)

    attention = payload["attention"]
    assert isinstance(attention, list)
    assert attention[0]["ts"] == "2026-07-19T00:05:00Z"


def test_full_state_serializes_round_history():
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
    ]
    state = fold(events)

    payload = full_state_json(state)

    items = payload["items"]
    assert isinstance(items, dict)
    assert items["wgclw.1"]["round_history"] == [
        {"round": 1, "head_sha": "a1", "ts": "2026-07-19T00:05:00Z"}
    ]


def test_full_state_reports_whether_a_retained_pr_ref_is_closed():
    # The ref outlives its PR (the failure-park rule needs it), so the snapshot
    # has to say which of the two questions -- "has a ref" and "has an open PR"
    # -- a consumer is getting an answer to.
    open_pr = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
    ]
    closed = [
        *open_pr,
        event("pr_closed", item="wgclw.1", pr=1, reason="superseded", next="in-progress"),
    ]

    def pr_of(events):
        items = full_state_json(fold(events))["items"]
        assert isinstance(items, dict)
        return items["wgclw.1"]["pr"]

    merged = [*open_pr, event("item_merged", item="wgclw.1", pr=1, sha="abc")]

    assert pr_of(open_pr)["closed"] is False
    assert pr_of(closed)["closed"] is True
    assert pr_of(closed)["number"] == 1
    # a merge ends the PR's life too -- reporting it as open would tell a
    # consumer that finished work still has something to fix
    assert pr_of(merged)["closed"] is True


def test_full_state_serializes_the_attempt_ledger():
    # The decision layer reads its attempt evidence off this surface rather
    # than counting for itself, so every kind is present with its count.
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("fix_attempted", item="wgclw.1", kind="ci-fix"),
    ]
    state = fold(events)

    items = full_state_json(state)["items"]
    assert isinstance(items, dict)
    assert items["wgclw.1"]["attempts"] == {"ci-fix": 1, "rebase": 0}
    assert items["wgclw.2"]["attempts"] == {"ci-fix": 0, "rebase": 0}


def test_full_state_serializes_staleness_ts_maps():
    events = [seed_event(), event("item_started", item="wgclw.1")]
    state = fold(events)

    payload = full_state_json(state)

    assert payload["last_item_ts"]["wgclw.1"] == "2026-07-19T00:05:00Z"
    assert "last_lane_ts" in payload


def test_full_state_json_is_a_faithful_materialization_of_state():
    # Reflection lock: every State field must appear in the snapshot (spec:
    # "entire state serialized"). A new fold fact that skips the serializer
    # fails here at the moment it is added, not in a later review round.
    import dataclasses

    from grind.model import State

    payload = full_state_json(fold([seed_event()]))

    missing = [f.name for f in dataclasses.fields(State) if f.name not in payload]
    assert missing == []
