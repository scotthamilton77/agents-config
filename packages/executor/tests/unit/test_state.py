"""Parsing the runtime's fold, and S9T1-D5 tracker-handle routing."""

from __future__ import annotations

import pytest

from executor.envelope import ErrorCode, ExecutorError
from executor.state import BudgetSpent, ItemView, parse_state, tracker_handle
from tests.unit.fakes import item, run_state

_STATE = {
    "config": {"ci_fix_budget": 2, "rebase_budget": 1},
    "items": {
        "it-1": {
            "id": "it-1",
            "lane": "lane-a",
            "status": "pr-open",
            "work_id": "agents-config-9k9.1",
            "pr": {"number": 42, "url": "https://example.invalid/42", "closed": False},
            "attempts": {"ci-fix": 1, "rebase": 0, "bogus": "two"},
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
        {"item": "it-1", "pr": 40, "reason": "no timestamp"},
        "not an object",
    ],
    "merged_ledger": [
        {"item": "it-1", "pr": 39, "sha": "9fceb02", "ts": "2026-07-25T00:00:00Z"},
        {"item": "it-2", "pr": 38, "sha": None, "ts": "2026-07-25T00:00:00Z"},
    ],
    "last_item_ts": {"it-1": "2026-07-25T00:00:00Z", "it-2": 17},
}


def test_parse_state_narrows_each_item_to_the_fields_a_pairing_reads() -> None:
    """
    Given the runtime's serialized fold
    When it is parsed
    Then each item carries its status, lane, work id, PR reference and
    openness, attempt counts and parked flag.

    The `bogus` attempt entry is dropped: a count that is not a number cannot
    be reported as one.
    """
    state = parse_state(_STATE)

    assert state.items["it-1"] == ItemView(
        id="it-1",
        status="pr-open",
        lane="lane-a",
        work_id="agents-config-9k9.1",
        pr_number=42,
        parked=False,
        park_reason=None,
        pr_open=True,
        attempts={"ci-fix": 1, "rebase": 0},
    )
    assert state.items["it-2"] == ItemView(
        id="it-2",
        status="queued",
        lane=None,
        work_id=None,
        pr_number=None,
        parked=True,
        park_reason="deferred",
        pr_open=False,
        attempts={},
    )


def test_the_config_the_conditions_were_computed_from_rides_the_same_parse() -> None:
    """
    Given a reply carrying the runtime's config
    When it is parsed
    Then the config reaches the state.

    The budget a proceeding attempt reports is read from here, so it has to
    come from the same snapshot as the condition that let it proceed.
    """
    assert parse_state(_STATE).config == {"ci_fix_budget": 2, "rebase_budget": 1}


@pytest.mark.parametrize(
    "config", ["not an object", None, 7, []], ids=["string", "null", "number", "list"]
)
def test_a_config_that_is_not_an_object_degrades_to_an_empty_one(config: object) -> None:
    """
    Given a reply whose config is not an object
    When it is parsed
    Then the config is empty rather than a fault.

    Nothing decides on the config: an unreadable one costs the documented
    fallback budget in a report, and the decision stays the condition's.
    """
    state = parse_state({"items": {}, "config": config})

    assert state.config == {}


@pytest.mark.parametrize(
    ("pr", "expected"),
    [
        ({"number": 42, "closed": False}, True),
        ({"number": 42, "closed": True}, False),
        ({"number": 42}, False),
        ({"number": 42, "closed": None}, False),
        ({"number": 42, "closed": "false"}, False),
        ({"number": 42, "closed": 0}, False),
        ({"closed": False}, False),
        (None, False),
        ("not an object", False),
    ],
    ids=[
        "open",
        "closed",
        "flag-absent",
        "flag-null",
        "flag-a-string",
        "flag-zero",
        "no-number",
        "no-ref",
        "not-an-object",
    ],
)
def test_only_an_explicit_closed_false_on_a_numbered_ref_reads_as_an_open_pr(
    pr: object, expected: bool
) -> None:
    """
    Given each shape a PR reference can arrive in
    When it is parsed
    Then only a numbered reference explicitly flagged not-closed is open.

    The flag is the field whose degraded reading authorises: an attempt claims
    to be fixing a live PR, so anything short of an explicit `false` — absent,
    null, mistyped — is not evidence of one. `0` is called out because it is
    falsey without being `false`.
    """
    state = parse_state({"items": {"it-1": {"pr": pr}}})

    assert state.items["it-1"].pr_open is expected


def test_the_ledgers_keep_only_entries_that_can_answer_a_retry() -> None:
    """
    Given ledgers holding one usable entry each, plus entries with a null PR,
    no timestamp, a null commit, and one that is not an object
    When they are parsed
    Then only the usable entries survive, and a non-string timestamp is dropped.

    Every dropped field is one a retry decision needs. An entry that cannot
    answer "is this already recorded?" must not be read as one answering yes:
    the resulting miss surfaces as a refusal or a flagged append, both
    recoverable, where a false match loses the transition silently.
    """
    state = parse_state(_STATE)

    assert state.closures == {("it-1", 41): "2026-07-25T00:00:00Z"}
    assert state.merged_shas == {"it-1": "9fceb02"}
    assert state.last_item_ts == {"it-1": "2026-07-25T00:00:00Z"}


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


@pytest.mark.parametrize("parked", [False, True, 0, "", "parked", []], ids=repr)
def test_a_malformed_parked_value_is_an_envelope_fault(parked: object) -> None:
    """
    Given an item whose `parked` is neither null nor an object
    When it is parsed
    Then E_RUNTIME_ENVELOPE is raised.

    The one field that may not degrade. Read as a bare "not null", a
    malformed `parked: false` would make an unparked item look parked —
    refusing legal commands, and waving `redispatch`/`abandon` past their
    precondition into a tracker-first mutation. A degraded value that
    authorises is a corrupt reply, not a degraded value.
    """
    with pytest.raises(ExecutorError) as raised:
        parse_state({"items": {"it-1": {"parked": parked}}})

    assert raised.value.code is ErrorCode.RUNTIME_ENVELOPE


@pytest.mark.parametrize("work_id", [42, True, "", [], {}], ids=repr)
def test_a_malformed_work_id_is_an_envelope_fault(work_id: object) -> None:
    """
    Given an item whose `work_id` is neither null nor a non-empty string
    When it is parsed
    Then E_RUNTIME_ENVELOPE is raised.

    The other field whose degraded reading authorises rather than refuses:
    falling back to `None` makes the handle resolve to the runtime's item id,
    so the executor would claim, park or close a tracker item named by that
    fallback on the strength of a reply that named no trustworthy handle.
    """
    with pytest.raises(ExecutorError) as raised:
        parse_state({"items": {"it-1": {"work_id": work_id}}})

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


def test_the_budget_conditions_are_keyed_by_item_and_kind() -> None:
    """
    Given a conditions list carrying budget facts and conditions of other names
    When it is parsed
    Then only the budget facts survive, keyed by (item, kind), with the
    runtime's own numbers.

    A condition of another name is read past rather than rejected: the
    runtime's vocabulary is free to grow, and a decision layer that parsed all
    of it would break on every addition.
    """
    state = parse_state(
        {"items": {}},
        [
            {"condition": "stale_item", "item": "it-1", "age_seconds": 4000.0},
            {
                "condition": "attempt_budget_spent",
                "item": "it-1",
                "kind": "ci-fix",
                "attempts": 2,
                "budget": 2,
            },
            {
                "condition": "attempt_budget_spent",
                "item": "it-1",
                "kind": "rebase",
                "attempts": 3,
                "budget": 1,
            },
            "not an object",
        ],
    )

    assert state.budget_spent == {
        ("it-1", "ci-fix"): BudgetSpent("it-1", "ci-fix", 2, 2),
        ("it-1", "rebase"): BudgetSpent("it-1", "rebase", 3, 1),
    }


@pytest.mark.parametrize(
    "entry",
    [
        {"condition": "attempt_budget_spent", "kind": "ci-fix", "attempts": 2, "budget": 2},
        {"condition": "attempt_budget_spent", "item": "it-1", "attempts": 2, "budget": 2},
        {"condition": "attempt_budget_spent", "item": "it-1", "kind": "ci-fix", "budget": 2},
        {"condition": "attempt_budget_spent", "item": "it-1", "kind": "ci-fix", "attempts": 2},
        {
            "condition": "attempt_budget_spent",
            "item": "it-1",
            "kind": "ci-fix",
            "attempts": True,
            "budget": 2,
        },
    ],
    ids=["no-item", "no-kind", "no-attempts", "no-budget", "attempts-a-bool"],
)
def test_an_unreadable_budget_condition_is_a_fault_not_a_dropped_entry(entry: object) -> None:
    """
    Given a conditions list holding a budget fact whose fields cannot be read
    When it is parsed
    Then E_RUNTIME_ENVELOPE is raised.

    Dropping it would read a reply that claims a budget is spent as one saying
    it is not — a degraded value authorising exactly the attempt the condition
    exists to refuse.
    """
    with pytest.raises(ExecutorError) as raised:
        parse_state({"items": {}}, [entry])  # type: ignore[list-item]

    assert raised.value.code is ErrorCode.RUNTIME_ENVELOPE


@pytest.mark.parametrize("conditions", ["[]", 7, {}], ids=["string", "number", "object"])
def test_a_conditions_block_that_is_not_a_list_is_a_fault(conditions: object) -> None:
    """
    Given a reply whose conditions block is present and not a list
    When it is parsed
    Then E_RUNTIME_ENVELOPE is raised.

    A reply claiming to carry conditions in a shape nothing can read says
    nothing about whether a budget is spent, and reading that as "not spent"
    is the same degraded authorisation one entry down.
    """
    with pytest.raises(ExecutorError) as raised:
        parse_state({"items": {}}, conditions)  # type: ignore[arg-type]

    assert raised.value.code is ErrorCode.RUNTIME_ENVELOPE


def test_a_reply_reporting_no_conditions_reports_no_exhaustion() -> None:
    """
    Given a reply with no conditions block at all
    When it is parsed
    Then no budget is spent.

    The empty boundary, and the inverse of the fault above: the runtime is the
    one source of this fact, so a reply reporting none reports no exhaustion.
    """
    assert parse_state({"items": {}}).budget_spent == {}
    assert parse_state({"items": {}}, []).budget_spent == {}


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
