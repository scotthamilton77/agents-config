"""S9T1-A7/A8: which side leads, what a failure leaves behind, and what a
retry does with a transition the runtime already records."""

from __future__ import annotations

import pytest

from executor.state import ItemView
from tests.unit.fakes import FakeRuntime, FakeTracker, invoke, item, run_state

# Every intent row, with the tracker verb it leads with and an item state the
# row is legal from.
_INTENTS = [
    (["start", "it-1"], "claim", item("it-1", work_id="w-1")),
    (
        ["park", "it-1", "--reason", "ci-failure"],
        "park",
        item("it-1", status="pr-open", pr=7, work_id="w-1"),
    ),
    (["redispatch", "it-1"], "redispatch", item("it-1", parked=True, work_id="w-1")),
    (
        ["abandon", "it-1", "--pr", "7"],
        "abandon",
        item("it-1", parked=True, work_id="w-1"),
    ),
]


@pytest.mark.parametrize(("argv", "tracker_verb", "view"), _INTENTS, ids=[i[1] for i in _INTENTS])
def test_an_intent_whose_tracker_call_fails_leaves_the_runtime_un_advanced(
    argv: list[str], tracker_verb: str, view: ItemView
) -> None:
    """
    Given a tracker that raises on the intent's verb
    When the command runs
    Then no runtime event is appended, no sync is issued, and the failure is
    reported as retryable.

    Tracker-first is what makes this safe: the operation stays retryable
    because neither side moved.
    """
    runtime = FakeRuntime(run_state(view))
    tracker = FakeTracker(fail_on=[tracker_verb])

    code, envelope = invoke(argv, runtime, tracker)

    assert code == 1
    assert envelope["error"]["retryable"] is True
    assert runtime.appended == []
    assert tracker.mutations == []
    assert tracker.syncs == 0


@pytest.mark.parametrize(("argv", "tracker_verb", "view"), _INTENTS, ids=[i[1] for i in _INTENTS])
def test_re_running_an_intent_after_the_tracker_recovers_converges(
    argv: list[str], tracker_verb: str, view: ItemView
) -> None:
    """
    Given an intent that failed on the tracker and a tracker that has since
    recovered
    When the command is re-run
    Then it succeeds with exactly one tracker mutation and one runtime event.

    Repeated invocation over an idempotent facade: the first attempt left
    nothing behind, so the retry is the whole operation, not half of it.
    """
    runtime = FakeRuntime(run_state(view))
    tracker = FakeTracker(fail_on=[tracker_verb])
    invoke(argv, runtime, tracker)

    tracker.recover()
    code, _ = invoke(argv, runtime, tracker)

    assert code == 0
    assert tracker.verbs == [tracker_verb]
    assert len(runtime.appended) == 1
    assert tracker.syncs == 1


@pytest.mark.parametrize(
    ("argv", "view", "tracker_verb"),
    [
        (["start", "it-1"], item("it-1", status="in-progress", work_id="w-1"), "claim"),
        (
            ["park", "it-1", "--reason", "ci-failure"],
            item("it-1", status="pr-open", pr=7, parked=True, work_id="w-1"),
            "park",
        ),
        (["redispatch", "it-1"], item("it-1", parked=False, work_id="w-1"), "redispatch"),
        (["abandon", "it-1", "--pr", "7"], item("it-1", parked=False, work_id="w-1"), "abandon"),
        (["done", "it-1"], item("it-1", status="done"), None),
    ],
    ids=["start", "park", "redispatch", "abandon", "done"],
)
def test_a_transition_the_runtime_already_records_appends_no_duplicate(
    argv: list[str], view: ItemView, tracker_verb: str | None
) -> None:
    """
    Given a response-lost retry — the runtime already records the transition
    When the command is re-run
    Then no second event is appended and success is still reported, with the
    tracker side re-issued so a half-landed pair converges.
    """
    runtime = FakeRuntime(run_state(view))
    tracker = FakeTracker()

    code, envelope = invoke(argv, runtime, tracker)

    assert code == 0
    assert runtime.appended == []
    assert envelope["data"]["event_appended"] is False
    assert tracker.verbs == ([] if tracker_verb is None else [tracker_verb])


def test_a_world_fact_is_recorded_even_when_the_tracker_call_fails() -> None:
    """
    Given a merge whose tracker close fails
    When the command runs
    Then `item_merged` is appended anyway and the failure surfaces as
    retryable.

    The inverse of the intent rule: the merge happened in the outside world,
    so losing the record would be worse than a one-sided state.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="in-review", pr=42, work_id="w-1")))
    tracker = FakeTracker(fail_on=["close"])

    code, envelope = invoke(["merged", "it-1", "--sha", "deadbee"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["retryable"] is True
    assert runtime.appended == [("item_merged", {"item": "it-1", "pr": 42, "sha": "deadbee"})]
    assert tracker.mutations == []
    assert tracker.syncs == 0


def test_the_merge_retry_re_issues_only_the_tracker_close_and_sync() -> None:
    """
    Given a merge already recorded by the runtime, whose tracker close failed
    When the command is re-run against the advanced fold
    Then no second `item_merged` is appended, the close is issued, and one
    sync follows.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="merged", pr=42, work_id="w-1")))
    tracker = FakeTracker()

    code, _ = invoke(["merged", "it-1", "--sha", "deadbee"], runtime, tracker)

    assert code == 0
    assert runtime.appended == []
    assert tracker.mutations == [("close", "w-1")]
    assert tracker.syncs == 1


def test_a_merge_retry_does_not_demand_a_pr_the_fold_no_longer_needs() -> None:
    """
    Given an item the runtime records as merged but holding no PR reference
    When the merge is re-run
    Then it succeeds rather than refusing with E_NO_OPEN_PR.

    Refusing here would strand a converging retry on the one path where the
    PR number is not needed.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="merged", work_id="w-1")))

    code, _ = invoke(["merged", "it-1", "--sha", "deadbee"], runtime, FakeTracker())

    assert code == 0


def test_re_recording_an_open_pr_appends_no_duplicate() -> None:
    """
    Given an item already recorded as holding that PR open
    When `pr-opened` is re-run for the same number
    Then nothing is appended and success is reported.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="pr-open", pr=42)))

    code, envelope = invoke(["pr-opened", "it-1", "--pr", "42"], runtime, FakeTracker())

    assert code == 0
    assert runtime.appended == []
    assert envelope["data"]["event_appended"] is False


@pytest.mark.parametrize("status", ["pr-open", "in-review", "waiting-human", "blocked", "merged"])
def test_an_opened_pr_stays_recognized_after_the_item_moves_on(status: str) -> None:
    """
    Given an item whose PR opened and which has since advanced
    When `pr-opened` is re-run for that same PR
    Then nothing is appended.

    An opened PR outlives the `pr-open` status, and re-appending is wrong in a
    different way from each state it can reach. From `waiting-human` the fold
    *accepts* the event and drags the item back to `pr-open`, discarding a wait
    that only an explicit resume should end — a silent state regression, not a
    flagged one.
    """
    runtime = FakeRuntime(run_state(item("it-1", status=status, pr=42)))

    code, envelope = invoke(["pr-opened", "it-1", "--pr", "42"], runtime, FakeTracker())

    assert code == 0
    assert runtime.appended == []
    assert envelope["data"]["event_appended"] is False


def test_a_different_pr_number_is_always_a_new_opening() -> None:
    """
    Given an item holding one PR
    When a different PR is recorded as opened
    Then the event is appended.

    The reference has to match: a second PR on the same item is new work, not
    a retry of the first.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="pr-open", pr=42)))

    invoke(["pr-opened", "it-1", "--pr", "43"], runtime, FakeTracker())

    assert runtime.appended == [("pr_opened", {"item": "it-1", "pr": 43})]


@pytest.mark.parametrize("status", ["pr-open", "in-review", "waiting-human", "merged"])
def test_a_reopened_pr_stays_recognized_as_its_cycle_advances(status: str) -> None:
    """
    Given a PR closed, genuinely reopened, and since advanced
    When `pr-opened` is re-run
    Then nothing is appended.

    The closure stays in the ledger forever, so any rule that reads it as
    "this PR is closed" calls every retry of the *reopened* cycle new — and
    re-appending from `waiting-human` is the silent-revert case again. The
    reopened cycle has to stay recognizable for as long as the first one does.
    """
    runtime = FakeRuntime(run_state(item("it-1", status=status, pr=42), closed_prs=[("it-1", 42)]))

    code, _ = invoke(["pr-opened", "it-1", "--pr", "42"], runtime, FakeTracker())

    assert code == 0
    assert runtime.appended == []


def test_a_pr_opening_is_recorded_again_once_the_item_is_parked_out() -> None:
    """
    Given an item parked by its PR's closure
    When that PR is recorded as opened again
    Then the event is appended.

    Parked is where `pr_closed --next parked` leaves an item, so it counts as
    closed-out exactly like `in-progress` and `queued` do.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="pr-open", pr=42, parked=True)))

    invoke(["pr-opened", "it-1", "--pr", "42"], runtime, FakeTracker())

    assert runtime.event_types == ["pr_opened"]


def test_reopening_the_same_pr_after_a_recorded_close_is_not_a_duplicate() -> None:
    """
    Given an item back in progress after its PR closed, with that closure in
    the ledger and the PR reference left behind
    When that same PR is recorded as opened again
    Then the event is appended.

    The PR reference alone cannot answer this — it survives a close, so
    matching on the number would swallow a genuine reopen. The recorded
    closure is what makes the reopen legible.
    """
    runtime = FakeRuntime(
        run_state(item("it-1", status="in-progress", pr=42), closed_prs=[("it-1", 42)])
    )

    invoke(["pr-opened", "it-1", "--pr", "42"], runtime, FakeTracker())

    assert runtime.appended == [("pr_opened", {"item": "it-1", "pr": 42})]


def test_re_recording_a_closure_already_in_the_ledger_appends_no_duplicate() -> None:
    """
    Given a closure the ledger already holds, with the item sitting where that
    closure's `--next` put it
    When `pr-closed` is re-run for the same item and PR
    Then nothing is appended and success is reported.

    Both facts make the retry legible. A landed closure moves the item out of
    the reviewable statuses, so an item still sitting in one has an open PR
    whatever the ledger remembers of an earlier cycle.
    """
    runtime = FakeRuntime(
        run_state(item("it-1", status="queued", pr=42), closed_prs=[("it-1", 42)])
    )

    code, envelope = invoke(
        ["pr-closed", "it-1", "--pr", "42", "--next", "queued", "--reason", "stale"],
        runtime,
        FakeTracker(),
    )

    assert code == 0
    assert runtime.appended == []
    assert envelope["data"]["event_appended"] is False


def test_a_second_closure_of_a_reopened_pr_is_recorded() -> None:
    """
    Given a PR closed, reopened, and now closing again
    When `pr-closed` runs
    Then the event is appended.

    The ledger holds the first cycle's closure forever, so reading it alone
    would deduplicate every later closure of the same PR number — the runtime
    would stay `pr-open` and never learn the second closure's reason or next
    status.
    """
    runtime = FakeRuntime(
        run_state(item("it-1", status="pr-open", pr=42), closed_prs=[("it-1", 42)])
    )

    invoke(
        ["pr-closed", "it-1", "--pr", "42", "--next", "queued", "--reason", "second"],
        runtime,
        FakeTracker(),
    )

    assert runtime.appended == [
        ("pr_closed", {"item": "it-1", "pr": 42, "next": "queued", "reason": "second"})
    ]


def test_a_closure_is_recorded_for_an_item_resumed_with_its_pr_still_open() -> None:
    """
    Given an item resumed out of a human wait, back in progress with its PR
    still open and never closed
    When that PR is recorded as closed
    Then the event is appended.

    The item's position alone cannot answer this: a resume lands at the same
    status a closure does, having closed nothing. The ledger is what separates
    them.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="in-progress", pr=42)))

    invoke(
        ["pr-closed", "it-1", "--pr", "42", "--next", "queued", "--reason", "stale"],
        runtime,
        FakeTracker(),
    )

    assert runtime.event_types == ["pr_closed"]


def test_a_closure_for_a_different_pr_is_still_appended() -> None:
    """
    Given a ledger holding a closure for another PR on the same item
    When a new PR's closure is recorded
    Then it is appended.

    The ledger match is per (item, PR), not per item: a second PR cycle's
    closure must not be swallowed by the first's.
    """
    runtime = FakeRuntime(
        run_state(item("it-1", status="pr-open", pr=43), closed_prs=[("it-1", 42)])
    )

    invoke(
        ["pr-closed", "it-1", "--pr", "43", "--next", "queued", "--reason", "stale"],
        runtime,
        FakeTracker(),
    )

    assert runtime.event_types == ["pr_closed"]
