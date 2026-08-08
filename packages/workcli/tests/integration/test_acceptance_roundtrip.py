"""Acceptance criteria survive create -> read against a real backend.

The hermetic suite proves the facade reports what a captured payload holds.
This proves the payload holds it: the criteria are written by a real `work
create`, stored by a real backend, and read back through every verb that
returns an item. A backend that stopped reporting them on one of its read
commands would land here and nowhere else.
"""

from __future__ import annotations

from tests.integration.conftest import ITEST_TRACK

_CRITERIA = "AC1 the criteria come back through every read."


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
