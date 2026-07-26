"""Parsing the runtime's fold, and S9T1-D5 tracker-handle routing."""

from __future__ import annotations

import pytest

from executor.envelope import ErrorCode, ExecutorError
from executor.state import ItemView, parse_state, tracker_handle
from tests.unit.fakes import item, run_state

_STATE = {
    "items": {
        "it-1": {
            "id": "it-1",
            "lane": "lane-a",
            "status": "pr-open",
            "work_id": "agents-config-9k9.1",
            "pr": {"number": 42, "url": "https://example.invalid/42"},
            "parked": None,
        },
        "it-2": {
            "id": "it-2",
            "lane": None,
            "status": "queued",
            "work_id": None,
            "pr": None,
            "parked": {"reason": "deferred", "note": "later"},
        },
    },
    "closed_ledger": [
        {"item": "it-1", "pr": 41, "reason": "superseded", "ts": "2026-07-25T00:00:00Z"},
        {"item": "it-1", "pr": None, "reason": "no number", "ts": "2026-07-25T00:00:00Z"},
        "not an object",
    ],
}


def test_parse_state_narrows_each_item_to_the_fields_a_pairing_reads() -> None:
    """
    Given the runtime's serialized fold
    When it is parsed
    Then each item carries its status, lane, work id, PR number and parked flag.
    """
    state = parse_state(_STATE)

    assert state.items["it-1"] == ItemView(
        id="it-1",
        status="pr-open",
        lane="lane-a",
        work_id="agents-config-9k9.1",
        pr_number=42,
        parked=False,
    )
    assert state.items["it-2"] == ItemView(
        id="it-2", status="queued", lane=None, work_id=None, pr_number=None, parked=True
    )


def test_closed_ledger_becomes_item_pr_pairs_skipping_unusable_entries() -> None:
    """
    Given a closed ledger holding one usable entry, one with a null PR, and
    one that is not an object
    When it is parsed
    Then only the usable entry becomes a pair.

    Pins that an entry that cannot answer "was this PR's closure recorded?"
    is dropped rather than guessed at — the resulting miss re-appends an
    event the runtime folds as an anomaly, which is recoverable; a false
    match silently loses the closure.
    """
    assert parse_state(_STATE).closed_prs == frozenset({("it-1", 41)})


@pytest.mark.parametrize(
    "payload",
    ["not an object", None, {"items": []}, {"no": "items"}],
    ids=["string", "null", "items-not-an-object", "items-absent"],
)
def test_a_reply_without_a_usable_items_object_is_an_envelope_fault(payload: object) -> None:
    """
    Given a runtime reply that is not a state object with items
    When it is parsed
    Then E_RUNTIME_ENVELOPE is raised.

    Pins that a garbled reply is never read as "the run has no items" — every
    verb would then refuse with the wrong reason.
    """
    with pytest.raises(ExecutorError) as raised:
        parse_state(payload)  # type: ignore[arg-type]

    assert raised.value.code is ErrorCode.RUNTIME_ENVELOPE


def test_a_boolean_pr_number_is_not_a_pr_number() -> None:
    """
    Given an item whose PR number decoded as `true`
    When it is parsed
    Then the PR number is None.

    `bool` is an `int` subclass, so a naive isinstance check would record
    `true` as PR 1.
    """
    state = parse_state({"items": {"it-1": {"pr": {"number": True}}}})

    assert state.items["it-1"].pr_number is None


def test_unknown_item_is_a_usage_refusal_naming_the_id() -> None:
    """
    Given a folded state without the requested item
    When it is looked up
    Then E_USAGE names the id.
    """
    with pytest.raises(ExecutorError) as raised:
        run_state(item("it-1")).item("it-9")

    assert raised.value.code is ErrorCode.USAGE
    assert "it-9" in raised.value.message


@pytest.mark.parametrize(
    ("view", "expected"),
    [
        (item("it-1", work_id="agents-config-9k9.4"), "agents-config-9k9.4"),
        (item("agents-config-9k9.4"), "agents-config-9k9.4"),
        (item("disc-3"), None),
        (item("disc-12"), None),
        (item("disc-x"), "disc-x"),
        (item("disc-"), "disc-"),
        (item("xdisc-3"), "xdisc-3"),
    ],
    ids=["case-a", "case-b", "case-c", "case-c-multidigit", "not-a-slug", "empty-n", "prefixed"],
)
def test_tracker_handle_routes_the_three_cases(view: ItemView, expected: str | None) -> None:
    """
    Given each of S9T1-D5's three cases and the grammar's near misses
    When the tracker handle is resolved
    Then a set work id wins, a plain id is its own handle, and only an exact
    `disc-<n>` has no handle at all.

    The near misses matter: over-matching the grammar would strand a real
    tracker item as unpromoted, which looks like success.
    """
    assert tracker_handle(view) == expected
