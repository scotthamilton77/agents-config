"""S9T1-A4/A5: the pairing table is total over a closed universe, and the park
vocabulary is the shared contract's, not a transcription of it."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from executor.cli import CLI_VERBS
from executor.envelope import ErrorCode, ExecutorError
from executor.pairing import (
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

# The failure axis is not this package's to define. It lives in the shared
# park-reason contract that the runtime and the facade also implement; the
# packages are isolated uv projects with no cross-import, so a transcription
# here would only catch a *forgetful* one-sided edit. Reading the one contract
# file makes a vocabulary change a four-file change by construction, with each
# missing table failing its own gate. Deliberately not skip-guarded: a silent
# skip reopens the hole the file exists to close.
_CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "park-reasons.toml"

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
    Given each S9T1-D12 row except the two `attempt` rows (slice C)
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


def test_the_unwired_verbs_are_exactly_attempt_and_next() -> None:
    """
    Given the closed universe
    When the unwired verbs are listed
    Then they are `attempt` and `next`.

    `attempt` is the budget-enforcement surface (slice C) and `next` the
    open-new-work one (slice N). Each lands by deleting its name here, so this
    assertion is what a later slice updates rather than fights.
    """
    assert set(PENDING_VERBS) == {"attempt", "next"}


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


def _contract_reasons() -> dict[str, str]:
    with _CONTRACT.open("rb") as handle:
        return dict(tomllib.load(handle)["reasons"])


def test_the_failure_axis_is_the_shared_contracts_vocabulary() -> None:
    """
    Given the shared park-reason contract
    When this package's failure-axis table is compared to it
    Then they hold the same reasons.

    The executor is the contract's third reader. A failure reason crosses to
    `work park --reason` byte-identical, so this package having its own idea
    of the vocabulary is what would force a mapping table at the call site.
    """
    assert set(FAILURE_REASONS) == set(_contract_reasons())


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
