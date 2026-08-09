"""S9T1-A4/A5: the pairing table is total over a closed universe, and the park
vocabulary is the one the runtime and the facade emit, not a private dialect."""

from __future__ import annotations

import pytest

from executor.cli import _READ_ONLY_HANDLERS, CLI_VERBS
from executor.envelope import ErrorCode, ExecutorError
from executor.pairing import (
    BUDGET_EXHAUSTED,
    EXECUTOR_VERBS,
    FAILURE_REASONS,
    PAIRING_TABLE,
    PENDING_VERBS,
    READ_ONLY_VERBS,
    SCHEDULING_REASONS,
    WIRED_VERBS,
    Axis,
    Order,
    PairingRow,
    TrackerVerb,
    park_axis,
)
from tests.unit.fakes import FakeRuntime, FakeTracker, invoke, run_state

# The failure axis is not this package's to define: the runtime and the facade
# emit the same five codes, and a reason crosses to `work park --reason`
# byte-identical. Written out rather than derived from the table under test,
# which would alarm at nothing -- each side pins what it emits, so an edit to
# this package's `FAILURE_REASONS` fails here until this literal agrees.
_FAILURE_VOCABULARY = frozenset(
    {
        "ci-failure",
        "merge-conflict",
        "approval-required",
        "bot-declined",
        "budget-exhausted",
    }
)

# The expected tracker action per row, stated here independently of the table
# under test. Every walked row must appear: a row added without an expectation
# fails the key-set assertion below rather than passing untested.
_EXPECTED_TRACKER: dict[str, tuple[str, TrackerVerb | None, Order]] = {
    "start": ("item_started", TrackerVerb.CLAIM, Order.TRACKER_FIRST),
    "park:failure": ("item_parked", TrackerVerb.PARK, Order.TRACKER_FIRST),
    "park:scheduling": ("item_parked", None, Order.TRACKER_FIRST),
    "redispatch": ("item_enqueued", TrackerVerb.REDISPATCH, Order.TRACKER_FIRST),
    "abandon": ("item_enqueued", TrackerVerb.ABANDON, Order.TRACKER_FIRST),
    "pr-opened": ("pr_opened", None, Order.RUNTIME_FIRST),
    "pr-closed": ("pr_closed", None, Order.RUNTIME_FIRST),
    "merged": ("item_merged", TrackerVerb.CLOSE, Order.RUNTIME_FIRST),
    "done": ("item_done", None, Order.RUNTIME_FIRST),
    "attempt:under-budget": ("fix_attempted", None, Order.TRACKER_FIRST),
    "attempt:exhausted": ("item_parked", TrackerVerb.PARK, Order.TRACKER_FIRST),
}


def test_every_table_row_is_walked_by_a_test() -> None:
    """
    Given the pairing table
    When its rows are matched against this module's expectations
    Then the two key sets are identical.

    A walked row without a test fails the suite: adding a row to the table
    without stating what it pairs with is exactly the drift S9T1-A4 forbids.
    """
    assert {row.key for row in PAIRING_TABLE} == set(_EXPECTED_TRACKER)


@pytest.mark.parametrize("row", PAIRING_TABLE, ids=lambda row: row.key)
def test_each_row_pairs_its_event_with_exactly_its_tracker_action(row: PairingRow) -> None:
    """
    Given each S9T1-D12 row
    When its pairing is read
    Then it names that row's grind event, that row's tracker verb or the
    table's explicit none, and the side that leads.
    """
    assert (row.event, row.tracker, row.order) == _EXPECTED_TRACKER[row.key]


def test_the_cli_exposes_exactly_the_wired_part_of_the_closed_universe() -> None:
    """
    Given the executor's argument parser
    When its verbs are listed
    Then they are the closed universe minus the verbs no slice has wired yet.

    Pins both halves of S9T1-A4: no verb outside the D12-plus-`next`
    enumeration exists, and the gap is named rather than ignored.
    """
    assert set(CLI_VERBS) == set(EXECUTOR_VERBS) - PENDING_VERBS
    assert CLI_VERBS == WIRED_VERBS


def test_no_verb_in_the_closed_universe_is_left_unwired() -> None:
    """
    Given the closed universe
    When the unwired verbs are listed
    Then there are none, and the CLI exposes the universe entire.

    The gap `PENDING_VERBS` measures is now empty, which is the strongest
    reading of the test above rather than a weaker one: `CLI_VERBS ==
    EXECUTOR_VERBS - PENDING_VERBS` with nothing subtracted says the parser
    carries every verb the contract names and no other. The second assertion
    is what keeps this from being the same claim twice — it fails if a future
    slice re-declares a gap without wiring it.
    """
    assert set(PENDING_VERBS) == set()
    assert set(WIRED_VERBS) == set(EXECUTOR_VERBS)


def test_each_verb_is_reached_by_exactly_one_of_the_two_dispatches() -> None:
    """
    Given the CLI's two dispatch paths
    When each wired verb is looked for in them
    Then the read-only handlers are exactly the read-only verbs, and no verb
    is both read-only and a pairing row.

    Completes the totality claim the test above starts. With `PENDING_VERBS`
    empty, "every verb is wired" only means every verb has a parser; a verb
    could still parse and then reach neither a plan nor a handler. The
    mutating half is covered by the row/verb test below, so pinning the
    read-only half and the disjointness closes the partition.
    """
    row_verbs = {row.verb for row in PAIRING_TABLE}

    assert set(_READ_ONLY_HANDLERS) == set(READ_ONLY_VERBS)
    assert row_verbs & set(READ_ONLY_VERBS) == set()
    assert row_verbs | set(READ_ONLY_VERBS) == set(CLI_VERBS)


def test_the_table_covers_every_wired_verb_that_mutates_anything() -> None:
    """
    Given the pairing table and the wired CLI surface
    When the two are compared
    Then every mutating wired verb has a row and every row has a wired verb.

    The table closes the *mutation* surface, so a read-only verb has no row
    and must not be looked for in one. A wired verb without a row would be a
    mutation nothing pairs; a row without a wired verb would be a pairing
    nothing can invoke.
    """
    assert {row.verb for row in PAIRING_TABLE} == set(WIRED_VERBS) - READ_ONLY_VERBS


def test_a_verb_outside_the_enumeration_is_refused_not_dispatched() -> None:
    """
    Given an executor verb that is not in the closed universe
    When it is invoked
    Then a typed usage envelope comes back and nothing is enacted.
    """
    runtime, tracker = FakeRuntime(run_state()), FakeTracker()

    code, envelope = invoke(["promote", "it-1"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_USAGE"
    assert runtime.appended == []
    assert tracker.mutations == []


def test_the_failure_axis_is_the_shared_contracts_vocabulary() -> None:
    """
    Given the park-reason vocabulary the runtime and the facade emit
    When this package's failure-axis table is compared to it
    Then they hold the same reasons.

    A failure reason crosses to `work park --reason` byte-identical, so this
    package having its own idea of the vocabulary is what would force a
    mapping table at the call site.
    """
    assert set(FAILURE_REASONS) == _FAILURE_VOCABULARY


def test_the_scheduling_axis_holds_the_runtime_native_reasons() -> None:
    """
    Given the scheduling axis
    When its members are listed
    Then they are the three sequencing reasons the facade has no verb for.

    Deliberately absent from the shared contract: these describe work that
    never had a PR to fail, so the tracker has nothing to record.
    """
    assert set(SCHEDULING_REASONS) == {"discovered-work", "later-wave", "deferred"}


@pytest.mark.parametrize("reason", FAILURE_REASONS)
def test_every_failure_reason_resolves_to_the_failure_axis(reason: str) -> None:
    assert park_axis(reason) is Axis.FAILURE


@pytest.mark.parametrize("reason", SCHEDULING_REASONS)
def test_every_scheduling_reason_resolves_to_the_scheduling_axis(reason: str) -> None:
    assert park_axis(reason) is Axis.SCHEDULING


def test_the_exhaustion_reason_is_on_the_axis_its_row_declares_a_tracker_verb_for() -> None:
    """
    Given the reason an exhausted budget parks under
    When its axis is resolved
    Then it is the failure axis.

    S9T1-D12 gives the exhaustion row a `work park --reason` rather than the
    scheduling axis's none, and that is only correct while the reason it uses
    is a failure-axis member. Moving it to the other axis would leave the row
    writing to a facade with no vocabulary for it.
    """
    assert park_axis(BUDGET_EXHAUSTED) is Axis.FAILURE
    assert BUDGET_EXHAUSTED in _FAILURE_VOCABULARY


def test_an_unknown_park_reason_is_refused_rather_than_defaulted() -> None:
    """
    Given a reason on neither axis
    When its axis is resolved
    Then E_USAGE is raised listing the legal codes.

    Defaulting would either invent a tracker write or swallow one that was
    owed — the axis decides whether the tracker hears about the park at all.
    """
    with pytest.raises(ExecutorError) as raised:
        park_axis("human-gated")

    assert raised.value.code is ErrorCode.USAGE
    assert "ci-failure" in raised.value.message
