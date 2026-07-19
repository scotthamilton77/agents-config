"""`payloads.validate_payload` -- the malformed/illegal seam (spec: "malformation
is caught before the log, illegality is caught after"). These tests only cover
*shape* validation; transition legality is the fold's job (tested elsewhere)."""

from __future__ import annotations

from grind.payloads import validate_payload

# -- grind_created (also used by `grind create`'s seed validation) ----------


def test_grind_created_requires_title_repo_mission_protocols_lanes():
    errors = validate_payload("grind_created", {})
    assert any("title" in e for e in errors)
    assert any("repo" in e for e in errors)
    assert any("mission" in e for e in errors)
    assert any("protocols" in e for e in errors)
    assert any("lanes" in e for e in errors)


def test_grind_created_accepts_minimal_valid_seed():
    errors = validate_payload(
        "grind_created",
        {
            "title": "Widget grind",
            "repo": "acme/widgets",
            "mission": {"goal": "ship widgets"},
            "protocols": {},
            "lanes": [],
        },
    )
    assert errors == []


def test_grind_created_config_must_be_object_when_present():
    errors = validate_payload(
        "grind_created",
        {
            "title": "t",
            "repo": "r",
            "mission": {},
            "protocols": {},
            "lanes": [],
            "config": "not-an-object",
        },
    )
    assert any("config" in e for e in errors)


def test_grind_created_validates_lane_and_item_shapes():
    errors = validate_payload(
        "grind_created",
        {
            "title": "t",
            "repo": "r",
            "mission": {},
            "protocols": {},
            "lanes": [{"name": "no id"}, {"id": "lane-a", "queue": [{"title": "no id"}]}],
        },
    )
    assert any("lanes[0]" in e for e in errors)
    assert any("lanes[1].queue[0]" in e for e in errors)


def _seed_with_item(item: dict) -> dict:
    return {
        "title": "t",
        "repo": "r",
        "mission": {},
        "protocols": {},
        "lanes": [{"id": "lane-a", "queue": [{"id": "wgclw.1", **item}]}],
    }


def test_grind_created_validates_seeded_blocker_edges():
    # A seeded item's optional `on` (blocker edges) must be an array of strings;
    # the fold silently drops malformed values and folds the item as `queued`
    # instead of `blocked`, so dependent work could start despite the edge.
    assert validate_payload("grind_created", _seed_with_item({})) == []
    assert validate_payload("grind_created", _seed_with_item({"on": []})) == []
    assert validate_payload("grind_created", _seed_with_item({"on": ["wgclw.2"]})) == []
    # scalar string instead of an array
    errors = validate_payload("grind_created", _seed_with_item({"on": "wgclw.2"}))
    assert any("lanes[0].queue[0].on" in e for e in errors)
    # array containing non-strings
    errors = validate_payload("grind_created", _seed_with_item({"on": [42]}))
    assert any("lanes[0].queue[0].on" in e for e in errors)


def test_grind_created_validates_optional_seed_string_fields():
    # Item title and lane name/agent/model/effort are silently coerced to None
    # by the fold when malformed -- validate them at the boundary.
    errors = validate_payload("grind_created", _seed_with_item({"title": 42}))
    assert any("lanes[0].queue[0].title" in e for e in errors)
    errors = validate_payload(
        "grind_created",
        {
            "title": "t",
            "repo": "r",
            "mission": {},
            "protocols": {},
            "lanes": [{"id": "lane-a", "model": 7}],
        },
    )
    assert any("lanes[0].model" in e for e in errors)


# -- item lifecycle -----------------------------------------------------------


def test_item_started_requires_item():
    assert validate_payload("item_started", {}) != []
    assert validate_payload("item_started", {"item": "wgclw.1"}) == []


def test_pr_opened_requires_item_and_int_pr():
    assert validate_payload("pr_opened", {"item": "wgclw.1"}) != []
    assert validate_payload("pr_opened", {"item": "wgclw.1", "pr": "not-int"}) != []
    assert validate_payload("pr_opened", {"item": "wgclw.1", "pr": 42}) == []
    assert validate_payload("pr_opened", {"item": "wgclw.1", "pr": 42, "url": "https://x"}) == []


def test_review_round_requires_item_kind_round_head_sha():
    payload = {"item": "wgclw.1", "kind": "codex", "round": 1, "head_sha": "abc123"}
    assert validate_payload("review_round", payload) == []
    assert validate_payload("review_round", {**payload, "kind": "bogus"}) != []
    assert validate_payload("review_round", {**payload, "round": "one"}) != []


def test_review_verdict_requires_verdict_enum_and_validates_findings():
    base = {"item": "wgclw.1", "kind": "codex", "round": 1, "head_sha": "abc", "verdict": "clean"}
    assert validate_payload("review_verdict", base) == []
    assert validate_payload("review_verdict", {**base, "verdict": "bogus"}) != []
    good_finding = {"findings": [{"severity": "high", "summary": "x", "disposition": "fixed"}]}
    assert validate_payload("review_verdict", {**base, **good_finding}) == []
    bad_finding = {"findings": [{"severity": "high", "summary": "x", "disposition": "bogus"}]}
    assert validate_payload("review_verdict", {**base, **bad_finding}) != []


def test_pr_closed_requires_item_pr_reason_and_valid_next():
    base = {"item": "wgclw.1", "pr": 1, "reason": "superseded"}
    assert validate_payload("pr_closed", {**base, "next": "queued"}) == []
    assert validate_payload("pr_closed", {**base, "next": "parked"}) == []
    assert validate_payload("pr_closed", {**base, "next": "bogus"}) != []
    assert validate_payload("pr_closed", base) != []  # next is required


def test_item_blocked_requires_item_and_list_of_str_on():
    assert validate_payload("item_blocked", {"item": "a", "on": ["b", "c"]}) == []
    assert validate_payload("item_blocked", {"item": "a", "on": "b"}) != []
    assert validate_payload("item_blocked", {"item": "a"}) != []


def test_item_waiting_human_requires_item_and_why():
    assert validate_payload("item_waiting_human", {"item": "a", "why": "needs a call"}) == []
    assert validate_payload("item_waiting_human", {"item": "a"}) != []


def test_item_resumed_requires_item_and_ruling():
    assert validate_payload("item_resumed", {"item": "a", "ruling": "proceed"}) == []
    assert validate_payload("item_resumed", {"item": "a"}) != []


def test_item_merged_requires_item_pr_sha():
    assert validate_payload("item_merged", {"item": "a", "pr": 1, "sha": "deadbeef"}) == []
    assert validate_payload("item_merged", {"item": "a", "pr": 1}) != []


def test_item_done_requires_item():
    assert validate_payload("item_done", {"item": "a"}) == []
    assert validate_payload("item_done", {}) != []


def test_item_parked_requires_item_kind_note():
    assert validate_payload("item_parked", {"item": "a", "kind": "deferred", "note": "n"}) == []
    assert validate_payload("item_parked", {"item": "a", "kind": "bogus", "note": "n"}) != []
    assert validate_payload("item_parked", {"item": "a", "kind": "deferred"}) != []


def test_item_enqueued_requires_item_and_lane():
    assert validate_payload("item_enqueued", {"item": "a", "lane": "lane-a"}) == []
    assert validate_payload("item_enqueued", {"item": "a", "lane": "lane-a", "position": 0}) == []
    assert validate_payload("item_enqueued", {"item": "a", "lane": "lane-a", "position": "x"}) != []
    assert validate_payload("item_enqueued", {"item": "a"}) != []


def test_discovered_work_requires_disposition_specific_fields():
    parked = {
        "item": "disc-1",
        "description": "found a thing",
        "source": "lane-a",
        "disposition": "parked",
        "rationale": "why",
        "kind": "discovered-work",
    }
    assert validate_payload("discovered_work", parked) == []
    # kind is required when parked
    assert validate_payload("discovered_work", {**parked, "kind": None}) != []

    enqueued = {
        "item": "disc-2",
        "description": "found a thing",
        "source": "lane-a",
        "disposition": "enqueued",
        "rationale": "why",
        "lane": "lane-a",
    }
    assert validate_payload("discovered_work", enqueued) == []
    without_lane = {k: v for k, v in enqueued.items() if k != "lane"}
    assert validate_payload("discovered_work", without_lane) != []


# -- lane / grind lifecycle / cross-cutting -----------------------------------


def test_lane_standing_down_requires_lane():
    assert validate_payload("lane_standing_down", {"lane": "lane-a"}) == []
    assert validate_payload("lane_standing_down", {}) != []


def test_lane_handover_requires_core_fields():
    payload = {"lane": "lane-a", "from_agent": "x", "to_agent": "y", "reason": "rotation"}
    assert validate_payload("lane_handover", payload) == []
    assert validate_payload("lane_handover", {**payload, "to_model": "sonnet"}) == []


def test_grind_paused_requires_reason():
    assert validate_payload("grind_paused", {"reason": "eod"}) == []
    assert validate_payload("grind_paused", {"reason": "eod", "resume_checklist": ["a"]}) == []
    assert validate_payload("grind_paused", {}) != []


def test_grind_resumed_has_no_required_fields():
    assert validate_payload("grind_resumed", {}) == []


def test_grind_finished_requires_summary():
    assert validate_payload("grind_finished", {"summary": "done"}) == []
    assert validate_payload("grind_finished", {}) != []


def test_observation_requires_level_and_message():
    assert validate_payload("observation", {"level": "INFO", "message": "hi"}) == []
    assert validate_payload("observation", {"level": "BOGUS", "message": "hi"}) != []
    assert validate_payload("observation", {"level": "INFO"}) != []


def test_attention_raised_requires_text():
    assert validate_payload("attention_raised", {"text": "look"}) == []
    assert validate_payload("attention_raised", {}) != []


def test_attention_cleared_requires_text_or_item():
    assert validate_payload("attention_cleared", {"text": "look"}) == []
    assert validate_payload("attention_cleared", {"item": "a"}) == []
    assert validate_payload("attention_cleared", {}) != []


# -- unknown types: forward-compatibility, no shape validation ---------------


def test_unknown_type_has_no_validator_and_is_always_shape_valid():
    assert validate_payload("some_future_event", {"anything": "goes"}) == []
