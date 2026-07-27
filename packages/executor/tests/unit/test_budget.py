"""S9T1-C1..C5: budget enforcement, driven through the CLI with both ports faked.

The split this suite exists to pin: the runtime counts and decides, the
executor enacts. Every case here states what the runtime reported and asserts
what the executor did with it -- never the arithmetic, which is the runtime's.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from executor.enact import SYNC_REPAIR
from executor.envelope import JsonValue
from executor.pairing import ATTEMPT_KINDS
from executor.state import ItemView
from tests.unit.fakes import (
    FakeRuntime,
    FakeTracker,
    FlaggingRuntime,
    invoke,
    item,
    run_state,
)

_KINDS = tuple(ATTEMPT_KINDS)


def _live(
    item_id: str = "it-1",
    *,
    status: str = "in-review",
    pr: int | None = 42,
    pr_closed: bool = False,
    work_id: str | None = "w-1",
    park_reason: str | None = None,
    attempts: Mapping[str, int] | None = None,
) -> ItemView:
    """An item mid-review with an open PR — where an attempt happens.

    The boring case for this suite, the way `item` is the boring case for the
    others: a test states only the fact it is about.
    """
    return item(
        item_id,
        status=status,
        pr=pr,
        pr_closed=pr_closed,
        work_id=work_id,
        park_reason=park_reason,
        attempts=attempts,
    )


# -- S9T1-C1: under budget, the append is a pre-charge --


@pytest.mark.parametrize("kind", _KINDS)
def test_an_attempt_under_budget_charges_the_ledger_and_reports_proceed(kind: str) -> None:
    """
    Given an item under its budget for a kind
    When an attempt of that kind is declared
    Then `fix_attempted` is appended and the envelope reports the counts with
    `proceed: true`.

    S9T1-C1. The append lands before any fix runs: a crash after this call has
    already spent the attempt, and a budget that counted only completed
    attempts would bound nothing.
    """
    runtime = FakeRuntime(run_state(_live()))
    tracker = FakeTracker()

    code, envelope = invoke(["attempt", "it-1", "--kind", kind], runtime, tracker)

    assert code == 0
    assert runtime.appended == [("fix_attempted", {"item": "it-1", "kind": kind})]
    assert envelope["data"]["proceed"] is True
    assert envelope["data"]["kind"] == kind
    assert envelope["data"]["item"] == "it-1"


def test_an_attempt_under_budget_touches_the_tracker_not_at_all() -> None:
    """
    Given an attempt that proceeds
    When the tracker is inspected
    Then it was neither mutated nor synced.

    S9T1-D12 gives this row an explicit none in its tracker column, and by
    S9T1-D9 a command that mutated nothing syncs nothing.
    """
    runtime = FakeRuntime(run_state(_live()))
    tracker = FakeTracker()

    code, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, tracker)

    assert code == 0
    assert tracker.mutations == []
    assert tracker.syncs == 0
    assert envelope["data"]["tracker_verb"] is None


def test_the_reported_counts_are_the_ledger_this_command_leaves_behind() -> None:
    """
    Given an item the runtime folded with one ci-fix attempt already spent
    When a second is declared against a budget of 2
    Then the envelope reports two attempts and none remaining.

    The append is a pre-charge, so by the time a caller reads this the attempt
    is spent -- reporting the count as the command *found* it would describe a
    ledger that no longer exists.
    """
    runtime = FakeRuntime(
        run_state(
            _live(attempts={"ci-fix": 1}),
            config={"ci_fix_budget": 2},
        )
    )

    _, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, FakeTracker())

    assert envelope["data"]["attempts"] == 2
    assert envelope["data"]["budget"] == 2
    assert envelope["data"]["remaining"] == 0


@pytest.mark.parametrize(
    ("kind", "expected"), [("ci-fix", 2), ("rebase", 1)], ids=["ci-fix", "rebase"]
)
def test_an_unseeded_budget_falls_back_to_this_packages_documented_number(
    kind: str, expected: int
) -> None:
    """
    Given a run whose config seeds no budget
    When an attempt proceeds
    Then the reported budget is the documented fallback for that kind.
    """
    runtime = FakeRuntime(run_state(_live()))

    _, envelope = invoke(["attempt", "it-1", "--kind", kind], runtime, FakeTracker())

    assert envelope["data"]["budget"] == expected


@pytest.mark.parametrize(
    "seeded", [None, "two", -1, True, 1.5], ids=["null", "string", "negative", "bool", "float"]
)
def test_a_seeded_budget_that_is_not_a_budget_falls_back(seeded: JsonValue) -> None:
    """
    Given a config whose budget value is not a usable count
    When an attempt proceeds
    Then the documented fallback is reported.

    The runtime's threshold reader falls back on exactly these, so falling back
    here too is what keeps both planes reporting one number for one config.
    """
    runtime = FakeRuntime(run_state(_live(), config={"ci_fix_budget": seeded}))

    _, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, FakeTracker())

    assert envelope["data"]["budget"] == 2


def test_a_seeded_budget_is_honored_over_the_fallback() -> None:
    """
    Given a caller-seeded budget
    When an attempt proceeds
    Then that number is reported, not the fallback.

    The `stalemate_risk_round` precedent: budgets are caller config, and this
    package's numbers are only what an unseeded run gets.
    """
    runtime = FakeRuntime(run_state(_live(), config={"ci_fix_budget": 5}))

    _, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, FakeTracker())

    assert envelope["data"]["budget"] == 5
    assert envelope["data"]["remaining"] == 4


def test_a_repeated_attempt_is_a_second_attempt_not_an_idempotent_retry() -> None:
    """
    Given an attempt that has already been declared
    When the identical command runs again
    Then it appends again.

    The one row whose append is deliberately not idempotent. `fix_attempted`
    folds into a count, so nothing in the state can tell a response-lost retry
    from a genuine second attempt -- and the pre-charge picks the safe side of
    that ambiguity: over-counting spends one more attempt inside a bound that
    exists for the purpose, where under-counting removes the bound.
    """
    runtime = FakeRuntime(run_state(_live()))
    tracker = FakeTracker()

    invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, tracker)
    code, _ = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, tracker)

    assert code == 0
    assert runtime.event_types == ["fix_attempted", "fix_attempted"]


def test_a_failed_append_never_reports_the_attempt_as_proceeding() -> None:
    """
    Given an attempt whose event the runtime wrote and then flagged
    When the error data is read
    Then it reports the event as appended and carries no `proceed` at all.

    The verb block is the command's *conclusion*, and a step that failed
    partway concluded nothing. `proceed` was computed before the append, so
    republishing it into the envelope reporting that append's failure would
    authorise exactly what did not happen — and the fold does not count a
    flagged attempt, so the budget was not charged either.
    """
    runtime = FlaggingRuntime(run_state(_live()))

    code, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, FakeTracker())

    assert code == 1
    assert envelope["error"]["data"]["event_appended"] is True
    assert "proceed" not in envelope["error"]["data"]
    assert "remaining" not in envelope["error"]["data"]


# -- S9T1-C2: at exhaustion, park first and refuse --


def test_at_exhaustion_the_tracker_is_parked_before_the_event_is_appended() -> None:
    """
    Given the runtime reporting the budget spent
    When an attempt is declared
    Then `work park --reason budget-exhausted` runs first, `item_parked` is
    appended second, no `fix_attempted` reaches the log, and one sync follows.

    S9T1-C2 and S9T1-D6's intent ordering: a tracker failure has to leave the
    runtime un-advanced and the command retryable.
    """
    runtime = FakeRuntime(run_state(_live(), spent=[("it-1", "ci-fix", 2, 2)]))
    tracker = FakeTracker()

    code, _ = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, tracker)

    assert code == 1
    assert tracker.mutations == [("park", "w-1", "budget-exhausted", "budget-exhausted")]
    assert runtime.appended == [
        (
            "item_parked",
            {"item": "it-1", "reason": "budget-exhausted", "note": "budget-exhausted"},
        )
    ]
    assert tracker.syncs == 1


def test_the_exhaustion_refusal_is_typed_and_carries_the_runtimes_numbers() -> None:
    """
    Given the runtime reporting the budget spent
    When an attempt is declared
    Then E_BUDGET_EXHAUSTED comes back, non-retryable, carrying the kind and
    both numbers.

    S9T1-D11. The numbers are the condition's, never recomputed: reporting a
    number this layer decided would let the report and the fact disagree.
    """
    runtime = FakeRuntime(run_state(_live(), spent=[("it-1", "ci-fix", 3, 2)]))

    code, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, FakeTracker())

    assert code == 1
    assert envelope["error"]["code"] == "E_BUDGET_EXHAUSTED"
    assert envelope["error"]["retryable"] is False
    assert envelope["error"]["data"]["kind"] == "ci-fix"
    assert envelope["error"]["data"]["attempts"] == 3
    assert envelope["error"]["data"]["budget"] == 2
    assert envelope["error"]["data"]["proceed"] is False


def test_the_exhaustion_refusal_reports_what_it_landed_on_both_planes() -> None:
    """
    Given an exhaustion that parked both planes
    When the refusal is read
    Then it reports the event as appended, the tracker as called, and the sync
    as issued.

    A refusal that mutated has to say what landed: without it a caller cannot
    tell this apart from a refusal that touched nothing, and would have no way
    to know whether the park needs repeating.
    """
    runtime = FakeRuntime(run_state(_live(), spent=[("it-1", "ci-fix", 2, 2)]))

    _, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, FakeTracker())

    assert envelope["error"]["data"]["event_appended"] is True
    assert envelope["error"]["data"]["tracker_called"] is True
    assert envelope["error"]["data"]["synced"] is True
    assert envelope["error"]["data"]["event"] == "item_parked"


def test_a_failed_park_leaves_the_runtime_un_advanced_and_the_command_retryable() -> None:
    """
    Given the facade failing on `park`
    When an exhausting attempt runs
    Then nothing is appended and a retryable transport failure comes back.

    S9T1-D6: the intent's tracker half leads, so its failure has to leave the
    runtime where it was.
    """
    runtime = FakeRuntime(run_state(_live(), spent=[("it-1", "ci-fix", 2, 2)]))
    tracker = FakeTracker(fail_on=["park"])

    code, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_TRACKER_SUBPROCESS"
    assert envelope["error"]["retryable"] is True
    assert runtime.appended == []
    assert tracker.syncs == 0


def test_a_retry_after_a_lost_append_converges_both_planes() -> None:
    """
    Given a first exhausting attempt whose park landed and whose append failed
    When the same command runs again against a recovered runtime
    Then the facade re-park is an idempotent no-op reporting the existing
    stint, and the missing `item_parked` is appended.

    S9T1-C2's dependency-failure case. The runtime is still unparked after the
    lost append, so the condition still fires and the exhaustion path re-runs
    -- which is the whole reason the tracker verb is re-issued on a retry
    rather than skipped.
    """
    state = run_state(_live(), spent=[("it-1", "ci-fix", 2, 2)])
    failing = FakeRuntime(state, fail_on=["item_parked"])
    tracker = FakeTracker()

    first, _ = invoke(["attempt", "it-1", "--kind", "ci-fix"], failing, tracker)

    assert first == 1
    assert failing.appended == []
    assert tracker.mutations == [("park", "w-1", "budget-exhausted", "budget-exhausted")]

    # The facade now holds the park; a replay reports the existing stint.
    recovered = FakeRuntime(state)
    replaying = FakeTracker(parked_as="budget-exhausted")

    second, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], recovered, replaying)

    assert second == 1
    assert envelope["error"]["code"] == "E_BUDGET_EXHAUSTED"
    assert recovered.event_types == ["item_parked"]
    assert replaying.mutations == [("park", "w-1", "budget-exhausted", "budget-exhausted")]
    assert replaying.syncs == 1


def test_a_landed_park_is_synced_even_when_the_append_then_fails() -> None:
    """
    Given an exhausting attempt whose park landed and whose append failed
    When the envelope is read
    Then the owed sync was issued and the append failure is the reported cause.

    The sync is owed by the mutation, not by the command succeeding.
    """
    runtime = FakeRuntime(
        run_state(_live(), spent=[("it-1", "ci-fix", 2, 2)]),
        fail_on=["item_parked"],
    )
    tracker = FakeTracker()

    code, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_RUNTIME_SUBPROCESS"
    assert tracker.syncs == 1
    assert envelope["error"]["data"]["synced"] is True


# -- S9T1-C2 boundary: exactly where the runtime says --


@pytest.mark.parametrize(
    ("attempts", "budget", "exhausted"),
    [
        (1, 2, False),
        (2, 2, True),
        (3, 2, True),
        (0, 0, True),
        (0, 1, False),
    ],
    ids=["one-below", "at-budget", "past-budget", "zero-budget", "fresh"],
)
def test_the_boundary_is_wherever_the_runtime_reported_it(
    attempts: int, budget: int, exhausted: bool
) -> None:
    """
    Given each side of the count-versus-budget boundary
    When an attempt is declared
    Then it proceeds exactly when the runtime reported no exhaustion.

    The boundary is `count == budget`, and a caller-seeded budget of `0` is
    legal -- "spend nothing on this kind" -- so it exhausts on a fresh item
    that has attempted nothing.
    """
    spent = [("it-1", "ci-fix", attempts, budget)] if exhausted else []
    runtime = FakeRuntime(
        run_state(
            _live(attempts={"ci-fix": attempts}),
            spent=spent,
            config={"ci_fix_budget": budget},
        )
    )

    code, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, FakeTracker())

    assert (code == 1) is exhausted
    if exhausted:
        assert envelope["error"]["code"] == "E_BUDGET_EXHAUSTED"
        assert runtime.event_types == ["item_parked"]
    else:
        assert runtime.event_types == ["fix_attempted"]


def test_a_budget_spent_for_one_kind_leaves_the_other_kind_alone() -> None:
    """
    Given a rebase budget the runtime reports as spent
    When a ci-fix attempt is declared
    Then it proceeds.

    The condition is per (item, kind); reading it per item would let one kind's
    exhaustion park work the other kind still has budget for.
    """
    runtime = FakeRuntime(run_state(_live(), spent=[("it-1", "rebase", 1, 1)]))

    code, _ = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, FakeTracker())

    assert code == 0
    assert runtime.event_types == ["fix_attempted"]


def test_a_budget_spent_for_another_item_leaves_this_one_alone() -> None:
    """
    Given another item's budget reported as spent
    When this item's attempt is declared
    Then it proceeds.

    The inverse on the other key: the condition is per item too.
    """
    runtime = FakeRuntime(
        run_state(
            _live(),
            _live("it-2"),
            spent=[("it-2", "ci-fix", 2, 2)],
        )
    )

    code, _ = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, FakeTracker())

    assert code == 0
    assert runtime.event_types == ["fix_attempted"]


# -- S9T1-C3: one definition of exhaustion --


def test_a_fresh_process_refuses_on_the_condition_alone() -> None:
    """
    Given a runtime reporting the budget spent, and an item whose folded
    ledger shows no attempts at all
    When an attempt is declared
    Then it is refused.

    S9T1-C3: the executor has observed nothing and counts nothing. If it kept
    its own counter, or recomputed exhaustion from the ledger, this state --
    which no consistent runtime produces, and which is exactly what a fresh
    process cannot distinguish -- would proceed.
    """
    runtime = FakeRuntime(
        run_state(
            _live(attempts={"ci-fix": 0}),
            spent=[("it-1", "ci-fix", 9, 2)],
            config={"ci_fix_budget": 99},
        )
    )

    code, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, FakeTracker())

    assert code == 1
    assert envelope["error"]["code"] == "E_BUDGET_EXHAUSTED"
    assert envelope["error"]["data"]["attempts"] == 9
    assert envelope["error"]["data"]["budget"] == 2


def test_a_ledger_past_the_budget_still_proceeds_when_no_condition_fires() -> None:
    """
    Given a folded ledger already past the configured budget and a runtime
    reporting no exhaustion
    When an attempt is declared
    Then it proceeds.

    The inverse of the case above, and the sharper half of S9T1-C3: the
    arithmetic is the runtime's, so the executor must not refuse on numbers it
    was not asked to decide on.
    """
    runtime = FakeRuntime(
        run_state(
            _live(attempts={"ci-fix": 7}),
            config={"ci_fix_budget": 2},
        )
    )

    code, _ = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, FakeTracker())

    assert code == 0
    assert runtime.event_types == ["fix_attempted"]


# -- S9T1-C4: the refusal edges --


@pytest.mark.parametrize(
    "spent",
    [[], [("it-1", "ci-fix", 2, 2)]],
    ids=["under-budget", "exhausted"],
)
def test_an_attempt_on_a_parked_item_is_refused_with_nothing_touched(
    spent: list[tuple[str, str, int, int]],
) -> None:
    """
    Given an item the runtime records as parked
    When an attempt is declared, on either side of the budget
    Then E_ITEM_PARKED comes back with zero events and zero tracker calls.

    S9T1-C4. The fold treats a parked item as absent for every handler but
    `item_enqueued`, so neither branch has anything it could legally enact.
    """
    runtime = FakeRuntime(run_state(_live(park_reason="ci-failure"), spent=spent))
    tracker = FakeTracker()

    code, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_ITEM_PARKED"
    assert runtime.appended == []
    assert tracker.mutations == []
    assert tracker.syncs == 0


@pytest.mark.parametrize(
    ("pr", "pr_closed"),
    [(None, False), (42, True)],
    ids=["no-reference", "closed-reference"],
)
def test_an_attempt_on_an_item_with_no_open_pr_is_refused_with_nothing_touched(
    pr: int | None, pr_closed: bool
) -> None:
    """
    Given an item holding no live PR — either none at all, or a reference a
    closure left behind
    When an attempt is declared
    Then E_NO_OPEN_PR comes back with zero events and zero tracker calls.

    S9T1-C4. An attempt exists only inside a PR cycle. The closed-reference
    case is the one a status check cannot catch: a closure leaves the
    reference in place deliberately, so "holds a PR" and "has an open PR" are
    different questions and only the second admits an attempt.
    """
    runtime = FakeRuntime(run_state(_live(pr=pr, pr_closed=pr_closed)))
    tracker = FakeTracker()

    code, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_NO_OPEN_PR"
    assert envelope["error"]["retryable"] is False
    assert runtime.appended == []
    assert tracker.mutations == []
    assert tracker.syncs == 0


@pytest.mark.parametrize("status", ["merged", "done"])
def test_an_attempt_on_a_terminal_item_is_refused(status: str) -> None:
    """
    Given an item the runtime records as finished
    When an attempt is declared
    Then it is refused with nothing appended.

    Finished work spends nothing, and the fold flags an attempt against it.
    """
    runtime = FakeRuntime(run_state(_live(status=status)))

    code, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, FakeTracker())

    assert code == 1
    assert status in envelope["error"]["message"]
    assert runtime.appended == []


def test_an_unknown_kind_is_refused_before_anything_is_enacted() -> None:
    """
    Given a `--kind` outside the vocabulary
    When an attempt is declared
    Then a usage envelope comes back and nothing is enacted.

    The parser's half of the check — the pairing layer's own is pinned
    alongside the other required-argument refusals, because argparse stands
    behind only one of this layer's callers.
    """
    runtime = FakeRuntime(run_state(_live()))
    tracker = FakeTracker()

    code, envelope = invoke(["attempt", "it-1", "--kind", "reroll"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_USAGE"
    assert runtime.appended == []
    assert tracker.mutations == []


# -- S9T1-C5: no double-park, and the sync repair --


def test_a_second_attempt_after_a_recorded_exhaustion_park_adds_nothing() -> None:
    """
    Given an exhaustion whose park is recorded on both planes
    When a second attempt is declared
    Then it is refused as parked, with no further event and no further tracker
    mutation.

    S9T1-C5's no-double-park. The runtime's condition is absent for a parked
    item, so the second call routes to the under-budget row and meets its
    parked refusal — which is why there is no path on which the park is
    enacted twice.
    """
    parked = FakeRuntime(run_state(_live(park_reason="budget-exhausted")))
    tracker = FakeTracker()

    code, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], parked, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_ITEM_PARKED"
    assert parked.appended == []
    assert tracker.mutations == []
    assert tracker.syncs == 0


def test_a_failed_sync_in_the_exhausting_invocation_names_its_own_repair() -> None:
    """
    Given an exhausting attempt whose park landed and whose sync failed
    When the envelope is read
    Then a retryable E_SYNC_FAILED names `work sync` as the repair.

    S9T1-C5 and S9T1-D9: the mutations landed, so re-running the command would
    repeat them. The sync is repaired on its own.
    """
    runtime = FakeRuntime(run_state(_live(), spent=[("it-1", "ci-fix", 2, 2)]))
    tracker = FakeTracker(fail_on=["sync"])

    code, envelope = invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_SYNC_FAILED"
    assert envelope["error"]["retryable"] is True
    assert envelope["error"]["data"]["repair"] == SYNC_REPAIR
    assert SYNC_REPAIR in envelope["error"]["message"]
    assert runtime.event_types == ["item_parked"]


def test_the_refusal_after_the_park_issues_no_sync_of_its_own() -> None:
    """
    Given a second attempt refused as parked
    When the tracker is inspected
    Then it was neither mutated nor synced.

    S9T1-C5's closing clause, and S9T1-D9's zero-mutation boundary: a refusal
    that wrote nothing has nothing to push.
    """
    runtime = FakeRuntime(run_state(_live(park_reason="budget-exhausted")))
    tracker = FakeTracker()

    invoke(["attempt", "it-1", "--kind", "ci-fix"], runtime, tracker)

    assert tracker.syncs == 0


# -- S9T1-D5 routing, over both attempt rows --


def test_an_unpromoted_item_under_budget_still_charges_its_ledger() -> None:
    """
    Given a run-local item with no tracker handle
    When an attempt proceeds
    Then the event is appended, the tracker hears nothing, and the item is
    surfaced as unpromoted.
    """
    runtime = FakeRuntime(run_state(_live("disc-4", work_id=None)))
    tracker = FakeTracker()

    code, envelope = invoke(["attempt", "disc-4", "--kind", "ci-fix"], runtime, tracker)

    assert code == 0
    assert runtime.event_types == ["fix_attempted"]
    assert tracker.mutations == []
    assert envelope["data"]["unpromoted"] == ["disc-4"]


def test_an_unpromoted_item_at_exhaustion_parks_the_runtime_and_no_tracker() -> None:
    """
    Given a run-local item at exhaustion
    When the attempt is refused
    Then the runtime park is recorded, no tracker mutation is issued, no sync
    follows, and the refusal surfaces the item as unpromoted.

    S9T1-D5 case (c) applies to the exhaustion row exactly as to every other
    row with a tracker action: the column reads none and the item is surfaced.
    Refusing it instead would make budget enforcement unavailable to precisely
    the work that has no tracker item yet.
    """
    runtime = FakeRuntime(
        run_state(_live("disc-4", work_id=None), spent=[("disc-4", "ci-fix", 2, 2)])
    )
    tracker = FakeTracker()

    code, envelope = invoke(["attempt", "disc-4", "--kind", "ci-fix"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_BUDGET_EXHAUSTED"
    assert runtime.event_types == ["item_parked"]
    assert tracker.mutations == []
    assert tracker.syncs == 0
    assert envelope["error"]["data"]["unpromoted"] == ["disc-4"]
    assert envelope["error"]["data"]["tracker_called"] is False
