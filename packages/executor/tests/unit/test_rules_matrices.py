"""The two matrices, walked.

`test_pairing_table.py` walks S9T1-D12 — which verb pairs with which event and
which tracker call. This walks the two matrices D12 does not state: which item
states each row may fire from, and which arguments make a re-invocation the
same command.

Both walks are driven from `ROW_RULES` itself, so a row added to the table
without a cell here fails rather than passing untested. Where a case needs a
fixture the table cannot supply — a state in which a command is already
recorded — the fixture is declared per row and its key set is asserted against
the table.
"""

from __future__ import annotations

import pytest

from executor.envelope import ExecutorError
from executor.pairing import PAIRING_TABLE
from executor.rules import (
    ROW_RULES,
    Parked,
    Request,
    Requires,
    check_preconditions,
)
from tests.unit.fakes import FakeRuntime, FakeTracker, invoke, item, run_state

# Every status an item can hold. `parked` is deliberately not in here: it is a
# flag beside a status, not a member of the set, and it gets its own walk.
_STATUSES = (
    "queued",
    "in-progress",
    "pr-open",
    "in-review",
    "waiting-human",
    "blocked",
    "merged",
    "done",
)


def test_every_pairing_row_has_rules() -> None:
    """
    Given the S9T1-D12 pairing table
    When each row is looked up in the matrices
    Then every row has an entry and no entry is orphaned.

    The matrices are per-row, so a row added to D12 without cells here would
    otherwise reach the uniform pipeline and fail at runtime.
    """
    assert set(ROW_RULES) == {row.key for row in PAIRING_TABLE}


def test_every_identity_tuple_starts_with_the_item() -> None:
    """
    Given each row's command-identity tuple
    When its fields are read
    Then the item is the first of them.

    Identity is always per item: two commands naming different items are never
    the same command, whatever else they carry.
    """
    for rules in ROW_RULES.values():
        assert rules.identity_fields[0] == "item", rules.key


# -- Matrix A: the source-state matrix --


@pytest.mark.parametrize("status", _STATUSES)
@pytest.mark.parametrize("key", sorted(ROW_RULES), ids=sorted(ROW_RULES))
def test_matrix_a_admits_exactly_the_states_it_declares(key: str, status: str) -> None:
    """
    Given each row and every item status
    When the preconditions are applied
    Then the row admits exactly the states it declares and refuses the rest.

    The whole 8-by-9 grid, walked from the table rather than from a list of
    remembered cases — the enumeration this replaced was discovered one cell
    per review round.
    """
    rules = ROW_RULES[key]
    view = item(
        "it-1",
        status=status,
        pr=42,
        lane="lane-a",
        parked=rules.parked is Parked.REQUIRED,
    )
    request = Request(
        item=view,
        state=run_state(view),
        pr=42,
        sha="9fceb02",
        next_status="queued",
        reason="ci-failure",
    )

    admitted = not rules.legal_states or status in rules.legal_states
    if admitted:
        check_preconditions(rules, request)
    else:
        with pytest.raises(ExecutorError):
            check_preconditions(rules, request)


@pytest.mark.parametrize("key", sorted(ROW_RULES), ids=sorted(ROW_RULES))
def test_matrix_a_treats_parked_as_its_own_axis(key: str) -> None:
    """
    Given each row and an item whose parkedness is the wrong way round
    When the preconditions are applied
    Then the row refuses it.

    Parked is a flag beside a status: a scheduling park leaves an item
    `queued`, so a status set alone would wave it through. The fold treats a
    parked item as absent for every handler but `item_enqueued`, which is the
    one that requires it.
    """
    rules = ROW_RULES[key]
    legal_status = next(iter(sorted(rules.legal_states))) if rules.legal_states else "queued"
    wrong_way = item(
        "it-1",
        status=legal_status,
        pr=42,
        lane="lane-a",
        parked=rules.parked is Parked.FORBIDDEN,
    )

    with pytest.raises(ExecutorError):
        check_preconditions(rules, Request(item=wrong_way, state=run_state(wrong_way), pr=42))


@pytest.mark.parametrize("key", sorted(ROW_RULES), ids=sorted(ROW_RULES))
def test_matrix_a_enforces_each_non_status_requirement(key: str) -> None:
    """
    Given each row's declared non-status requirements
    When an item violates one
    Then the row refuses it, and an item violating none is admitted.

    `PR_MATCHES_ITEM` is the one with no counterpart in the fold: the fold
    compares an event's PR against nothing, so only this check stops a delayed
    notification for a superseded PR being taken as fact.
    """
    rules = ROW_RULES[key]
    legal_status = next(iter(sorted(rules.legal_states))) if rules.legal_states else "queued"
    parked = rules.parked is Parked.REQUIRED

    def _request(**overrides: object) -> Request:
        view = item(
            "it-1",
            status=legal_status,
            pr=overrides.get("pr_number", 42),  # type: ignore[arg-type]
            lane=overrides.get("lane", "lane-a"),  # type: ignore[arg-type]
            parked=parked,
        )
        return Request(item=view, state=run_state(view), pr=42)

    check_preconditions(rules, _request())

    violations = {
        Requires.LANE: {"lane": None},
        Requires.PR_REFERENCE: {"pr_number": None},
        Requires.PR_MATCHES_ITEM: {"pr_number": 99},
    }
    for requirement in rules.requires:
        with pytest.raises(ExecutorError):
            check_preconditions(rules, _request(**violations[requirement]))


# -- Matrix B: the command-identity tuple --
#
# Per row: a state in which the command is already recorded, the command
# itself, and one variant per identity field that differs in exactly that
# field. The variant must never be silently skipped.
_RECORDED: dict[str, tuple[object, list[str], list[list[str]]]] = {
    "start": (
        (item("it-1", status="in-progress", work_id="w-1"), {}),
        ["start", "it-1"],
        [],
    ),
    "park:failure": (
        (item("it-1", status="pr-open", pr=7, park_reason="ci-failure", work_id="w-1"), {}),
        ["park", "it-1", "--reason", "ci-failure"],
        [["park", "it-1", "--reason", "merge-conflict"]],
    ),
    "park:scheduling": (
        (item("it-1", status="queued", park_reason="later-wave", work_id="w-1"), {}),
        ["park", "it-1", "--reason", "later-wave"],
        [["park", "it-1", "--reason", "deferred"]],
    ),
    "redispatch": (
        (item("it-1", status="queued", work_id="w-1"), {}),
        ["redispatch", "it-1"],
        [],
    ),
    "abandon": (
        (item("it-1", status="queued", work_id="w-1"), {"closures": [("it-1", 8)]}),
        ["abandon", "it-1", "--pr", "8"],
        [["abandon", "it-1", "--pr", "9"]],
    ),
    "pr-opened": (
        (item("it-1", status="pr-open", pr=42, work_id="w-1"), {}),
        ["pr-opened", "it-1", "--pr", "42"],
        [["pr-opened", "it-1", "--pr", "43"]],
    ),
    "pr-closed": (
        (item("it-1", status="queued", pr=42, work_id="w-1"), {"closures": [("it-1", 42)]}),
        ["pr-closed", "it-1", "--pr", "42", "--next", "queued", "--reason", "stale"],
        [
            ["pr-closed", "it-1", "--pr", "43", "--next", "queued", "--reason", "stale"],
            ["pr-closed", "it-1", "--pr", "42", "--next", "in-progress", "--reason", "stale"],
        ],
    ),
    "merged": (
        (
            item("it-1", status="merged", pr=42, work_id="w-1"),
            {"merged_shas": {"it-1": "9fceb02"}},
        ),
        ["merged", "it-1", "--sha", "9fceb02"],
        [["merged", "it-1", "--sha", "badc0de"]],
    ),
    "done": (
        (item("it-1", status="done", work_id="w-1"), {}),
        ["done", "it-1"],
        [],
    ),
}


def _recorded_runtime(key: str) -> FakeRuntime:
    view, state_kwargs = _RECORDED[key][0]  # type: ignore[misc]
    return FakeRuntime(run_state(view, **state_kwargs))  # type: ignore[arg-type]


def test_every_row_has_a_recorded_fixture() -> None:
    """
    Given the matrices
    When the identity fixtures are matched against them
    Then every row has one.

    A row added without a fixture would leave its idempotency untested, which
    is the gap that produced eight of this PR's review findings.
    """
    assert set(_RECORDED) == set(ROW_RULES)


@pytest.mark.parametrize("key", sorted(_RECORDED), ids=sorted(_RECORDED))
def test_a_full_identity_match_is_the_idempotent_skip(key: str) -> None:
    """
    Given a command the fold already records in full
    When it is re-invoked unchanged
    Then it appends nothing and reports success.

    S9T1-D6's state-checked idempotence, walked per row.
    """
    runtime = _recorded_runtime(key)

    code, envelope = invoke(_RECORDED[key][1], runtime, FakeTracker())  # type: ignore[arg-type]

    assert code == 0
    assert runtime.appended == []
    assert envelope["data"]["event_appended"] is False


@pytest.mark.parametrize(
    ("key", "variant"),
    [(key, variant) for key, entry in _RECORDED.items() for variant in entry[2]],  # type: ignore[union-attr]
    ids=[
        f"{key}-{index}"
        for key, entry in _RECORDED.items()
        for index, _ in enumerate(entry[2])  # type: ignore[arg-type]
    ],
)
def test_a_partial_identity_match_is_never_silently_skipped(key: str, variant: list[str]) -> None:
    """
    Given a command the fold records, re-invoked with one identity field
    changed
    When it runs
    Then it is enacted or refused on the merits, never reported as already
    done.

    A partial match is a *different* command. Answering "already done" to one
    claims a transition neither plane made — the single rule behind eight of
    this PR's review findings, each of which was one argument's worth of it.
    """
    runtime = _recorded_runtime(key)

    code, envelope = invoke(variant, runtime, FakeTracker())

    skipped = code == 0 and not runtime.appended
    assert not skipped, f"{variant} was skipped as a retry of {_RECORDED[key][1]}"
    if code == 0:
        assert envelope["data"]["event_appended"] is True


# -- The axis that is never a refusal --


@pytest.mark.parametrize("key", sorted(ROW_RULES), ids=sorted(ROW_RULES))
def test_a_run_local_item_is_never_refused_for_its_id(key: str) -> None:
    """
    Given a run-local item in a state its row admits
    When the preconditions are applied
    Then they pass.

    S9T1-A6: an id with no tracker handle is a success path, not a refusal.
    Handle routing happens in `enact`, and the matrices must never grow a cell
    for it — this walk is what stops a later cleanup folding the id shape into
    the state matrix.
    """
    rules = ROW_RULES[key]
    legal_status = next(iter(sorted(rules.legal_states))) if rules.legal_states else "queued"
    view = item(
        "disc-1",
        status=legal_status,
        pr=42,
        lane="lane-a",
        parked=rules.parked is Parked.REQUIRED,
    )

    check_preconditions(rules, Request(item=view, state=run_state(view), pr=42))


def test_a_run_local_item_still_enacts_with_no_tracker_call() -> None:
    """
    Given a run-local item
    When a command touches it
    Then the runtime event is appended, the tracker hears nothing, and the
    item is surfaced as unpromoted.

    The end-to-end half of the guard above.
    """
    runtime = FakeRuntime(run_state(item("disc-1")))
    tracker = FakeTracker()

    code, envelope = invoke(["start", "disc-1"], runtime, tracker)

    assert code == 0
    assert runtime.event_types == ["item_started"]
    assert tracker.mutations == []
    assert envelope["data"]["unpromoted"] == ["disc-1"]
