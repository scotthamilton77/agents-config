"""defer / undefer against real backend state.

The hermetic suite proves the verb layer's decisions against a fake. What it
cannot prove is the claim the whole design rests on: that the backend itself
drops a deferred item out of its ready set and takes it back on the return
trip. That is a property of the real thing, so it is asserted here.
"""

from __future__ import annotations

from tests.integration.conftest import ITEST_TRACK


def _ready_ids(driver) -> list[str]:
    return [item["id"] for item in driver(["ready"])["data"]["items"]]


def _new_leaf(driver, title: str) -> str:
    created = driver(
        ["create", "feat", "--title", title, "--priority", "2", "--orphan", "--track", ITEST_TRACK]
    )
    assert created["ok"] is True, created
    return created["data"]["id"]


def test_defer_drops_a_real_item_out_of_ready_and_undefer_brings_it_back(driver):
    item_id = _new_leaf(driver, "df-idea")
    assert item_id in _ready_ids(driver)

    deferred = driver(["defer", item_id, "--note", "nobody has picked this up"])
    assert deferred["ok"] is True
    assert deferred["data"] == {"id": item_id, "status": "deferred"}
    assert driver(["show", item_id])["data"]["status"] == "deferred"
    assert item_id not in _ready_ids(driver)

    returned = driver(["undefer", item_id])
    assert returned["ok"] is True
    assert returned["data"] == {"id": item_id, "status": "open"}
    assert driver(["show", item_id])["data"]["status"] == "open"
    assert item_id in _ready_ids(driver)

    # One marker per transition, and both survived the round trip.
    notes = driver(["show", item_id])["data"]["notes"]
    assert notes.count("[work] deferred") == 1
    assert notes.count("[work] undeferred") == 1


def test_a_deferred_item_raises_no_nag_and_refuses_a_claim(driver):
    item_id = _new_leaf(driver, "df-nag")
    driver(["defer", item_id])

    assert driver(["parked"])["data"]["items"] == []
    assert driver(["ready"])["data"]["parked_stale"] == []

    refused = driver(["claim", item_id])
    assert refused["ok"] is False
    assert refused["error"]["code"] == "E_NOT_CLAIMABLE"
    assert "undefer" in refused["error"]["message"]


def test_a_read_envelope_tells_a_deferred_item_from_a_parked_one(driver):
    idea = _new_leaf(driver, "df-idea-vs-obstruction")
    stuck = _new_leaf(driver, "df-obstruction")
    driver(["defer", idea])
    assert driver(["claim", stuck])["ok"] is True
    assert driver(["park", stuck, "--reason", "ci-failure"])["ok"] is True

    idea_item = driver(["show", idea])["data"]
    stuck_item = driver(["show", stuck])["data"]

    assert idea_item["status"] == "deferred"
    assert "parked" not in idea_item["labels"]
    assert stuck_item["status"] == "blocked"
    assert "parked" in stuck_item["labels"]


def test_the_transitions_replay_idempotently_against_real_state(driver):
    item_id = _new_leaf(driver, "df-replay")

    first = driver(["defer", item_id])
    second = driver(["defer", item_id])
    assert first["data"] == second["data"] == {"id": item_id, "status": "deferred"}
    assert driver(["show", item_id])["data"]["notes"].count("[work] deferred") == 1

    third = driver(["undefer", item_id])
    fourth = driver(["undefer", item_id])
    assert third["data"] == fourth["data"] == {"id": item_id, "status": "open"}
    assert driver(["show", item_id])["data"]["notes"].count("[work] undeferred") == 1
