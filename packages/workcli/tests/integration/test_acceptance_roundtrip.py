"""Acceptance criteria survive create -> read -> correction against a real backend.

The hermetic suite proves the facade reports what a captured payload holds.
This proves the payload holds it: the criteria are written by a real `work
create`, stored by a real backend, and read back through every verb that
returns an item. A backend that stopped reporting them on one of its read
commands would land here and nowhere else.

The correction path is here for the same reason. `acceptance set` rests on two
properties of the real thing that no fake can establish — that the backend
replaces the criteria outright rather than appending to them, and that a
multi-line note carrying the superseded text survives the round trip intact.
"""

from __future__ import annotations

from tests.integration.conftest import ITEST_TRACK

_CRITERIA = "AC1 the criteria come back through every read."
_CORRECTED = "AC1 the criteria come back, and can be corrected."


def _create(driver, title: str, *argv: str) -> str:
    created = driver(
        [
            "create",
            "chore",
            "--title",
            title,
            "--priority",
            "2",
            "--orphan",
            "--track",
            ITEST_TRACK,
            *argv,
        ]
    )
    assert created["ok"] is True, created
    return created["data"]["id"]


def test_show_returns_the_acceptance_the_item_was_created_with(driver):
    item_id = _create(driver, "ac-roundtrip", "--acceptance", _CRITERIA)

    shown = driver(["show", item_id])["data"]  # single-id show → item directly

    assert shown["acceptance"] == _CRITERIA


def test_an_item_created_without_acceptance_reports_none_rather_than_omitting_it(driver):
    item_id = _create(driver, "ac-roundtrip-none")

    shown = driver(["show", item_id])["data"]

    assert "acceptance" in shown, "an absent key would say this read never fetched the criteria"
    assert shown["acceptance"] is None


def test_every_read_verb_reports_the_same_acceptance_show_does(driver):
    with_criteria = _create(driver, "ac-listed", "--acceptance", _CRITERIA)
    without_criteria = _create(driver, "ac-listed-none")
    expected = {with_criteria: _CRITERIA, without_criteria: None}

    reads = {
        "list": driver(["list"]),
        "ready": driver(["ready"]),
        "search": driver(["search", "ac-listed"]),
    }

    for verb, envelope in reads.items():
        assert envelope["ok"] is True, envelope
        reported = {item["id"]: item for item in envelope["data"]["items"]}
        for item_id, criteria in expected.items():
            assert item_id in reported, f"{verb} did not report {item_id}"
            assert "acceptance" in reported[item_id], f"{verb} omits acceptance for {item_id}"
            assert reported[item_id]["acceptance"] == criteria, verb


def test_a_correction_replaces_the_criteria_and_leaves_the_old_text_readable(driver):
    # Replaces, never appends: the item ends up carrying the new criteria and
    # nothing of the old ones, while the old ones stay readable in the notes.
    item_id = _create(driver, "ac-corrected", "--acceptance", _CRITERIA)

    corrected = driver(["acceptance", "set", item_id, _CORRECTED])

    assert corrected["ok"] is True, corrected
    assert corrected["data"]["previous"] == _CRITERIA
    shown = driver(["show", item_id])["data"]
    assert shown["acceptance"] == _CORRECTED
    assert _CRITERIA not in shown["acceptance"]
    assert f"> {_CRITERIA}" in shown["notes"]
    assert "[work] acceptance restated" in shown["notes"]


def test_multi_line_criteria_survive_the_round_trip_quoted_line_by_line(driver):
    # The trail is a multi-line note, which is the shape most likely to be
    # mangled somewhere between the facade and the stored item.
    previous = "AC1 the first thing.\nAC2 the second thing."
    item_id = _create(driver, "ac-multiline", "--acceptance", previous)

    driver(["acceptance", "set", item_id, _CORRECTED])

    notes = driver(["show", item_id])["data"]["notes"]
    assert "> AC1 the first thing." in notes
    assert "> AC2 the second thing." in notes


def test_a_claimed_item_refuses_a_silent_correction_and_records_a_stated_one(driver):
    item_id = _create(driver, "ac-claimed", "--acceptance", _CRITERIA)
    assert driver(["claim", item_id])["ok"] is True

    refused = driver(["acceptance", "set", item_id, _CORRECTED])

    assert refused["ok"] is False
    assert refused["error"]["code"] == "E_FIELD_CLOBBER_GUARD"
    assert driver(["show", item_id])["data"]["acceptance"] == _CRITERIA

    stated = driver(["acceptance", "set", item_id, _CORRECTED, "--why", "AC1 was ambiguous"])

    assert stated["ok"] is True, stated
    shown = driver(["show", item_id])["data"]
    assert shown["acceptance"] == _CORRECTED
    assert "while in_progress: AC1 was ambiguous" in shown["notes"]
