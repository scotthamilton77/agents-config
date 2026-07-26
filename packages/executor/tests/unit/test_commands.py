"""Every S9T1-D12 row driven end to end through the CLI with both ports faked:
the pairing it enacts, the handle it routes to, and the sync that follows."""

from __future__ import annotations

import pytest

from executor.enact import SYNC_REPAIR, TrackerSession
from executor.pairing import FAILURE_REASONS, SCHEDULING_REASONS, TrackerVerb
from tests.unit.fakes import FakeRuntime, FakeTracker, invoke, item, run_state


def test_start_claims_then_records_the_item_started() -> None:
    """
    Given a queued item
    When it is started
    Then the tracker is claimed, `item_started` is appended, and one sync
    follows.
    """
    runtime = FakeRuntime(run_state(item("it-1", work_id="w-1")))
    tracker = FakeTracker()

    code, envelope = invoke(["start", "it-1"], runtime, tracker)

    assert code == 0
    assert tracker.mutations == [("claim", "w-1")]
    assert runtime.appended == [("item_started", {"item": "it-1"})]
    assert tracker.syncs == 1
    assert envelope["data"]["event"] == "item_started"
    assert envelope["data"]["tracker_verb"] == "claim"


@pytest.mark.parametrize("reason", FAILURE_REASONS)
def test_a_failure_axis_park_crosses_untranslated(reason: str) -> None:
    """
    Given each failure-axis park reason
    When the item is parked
    Then the same code reaches `work park --reason` byte-identical.

    There is no mapping table anywhere in this package; the reason the
    runtime records and the reason the tracker records are one string.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="pr-open", pr=7, work_id="w-1")))
    tracker = FakeTracker()

    code, _ = invoke(["park", "it-1", "--reason", reason, "--note", "see PR"], runtime, tracker)

    assert code == 0
    assert tracker.mutations == [("park", "w-1", reason, "see PR")]
    assert runtime.appended == [
        ("item_parked", {"item": "it-1", "reason": reason, "note": "see PR"})
    ]


def test_a_park_without_a_note_defaults_to_its_reason_code() -> None:
    """
    Given a park with no note
    When it is enacted
    Then the reason code is the note on both sides.

    The runtime requires a note; a park whose note only repeats its typed
    reason says exactly as much as the reason does.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="pr-open", pr=7)))
    tracker = FakeTracker()

    invoke(["park", "it-1", "--reason", "ci-failure"], runtime, tracker)

    assert tracker.mutations == [("park", "it-1", "ci-failure", "ci-failure")]
    assert runtime.appended[0][1]["note"] == "ci-failure"


@pytest.mark.parametrize("reason", SCHEDULING_REASONS)
def test_a_scheduling_axis_park_issues_zero_tracker_calls(reason: str) -> None:
    """
    Given each scheduling-axis park reason
    When the item is parked
    Then the runtime records the park and the tracker hears nothing at all —
    not even a sync.

    The inverse of the failure-axis pair: these are sequencing decisions about
    work that never had a PR to fail, and the facade deliberately carries no
    vocabulary for them.
    """
    runtime = FakeRuntime(run_state(item("it-1", work_id="w-1")))
    tracker = FakeTracker()

    code, envelope = invoke(["park", "it-1", "--reason", reason], runtime, tracker)

    assert code == 0
    assert runtime.event_types == ["item_parked"]
    assert tracker.mutations == []
    assert tracker.syncs == 0
    assert envelope["data"]["tracker_verb"] is None


def test_redispatch_returns_a_parked_item_to_its_lane() -> None:
    """
    Given a parked item
    When it is redispatched
    Then the facade is told first and `item_enqueued` names the item's lane,
    with no closure attached.

    A redispatch resumes the same PR, so recording a closure would discard a
    PR that is still open.
    """
    runtime = FakeRuntime(run_state(item("it-1", parked=True, lane="lane-b", work_id="w-1")))
    tracker = FakeTracker()

    invoke(["redispatch", "it-1"], runtime, tracker)

    assert tracker.mutations == [("redispatch", "w-1")]
    assert runtime.appended == [("item_enqueued", {"item": "it-1", "lane": "lane-b"})]


def test_abandon_carries_the_closure_on_the_single_park_exit() -> None:
    """
    Given a parked item whose PR is being abandoned
    When it is abandoned
    Then `item_enqueued` carries `{pr, reason}` as its closure and the facade
    is told first.
    """
    runtime = FakeRuntime(run_state(item("it-1", parked=True, work_id="w-1")))
    tracker = FakeTracker()

    invoke(["abandon", "it-1", "--pr", "42", "--reason", "superseded"], runtime, tracker)

    assert tracker.mutations == [("abandon", "w-1")]
    assert runtime.appended == [
        (
            "item_enqueued",
            {
                "item": "it-1",
                "lane": "lane-a",
                "closure": {"pr": 42, "reason": "superseded"},
            },
        )
    ]


def test_abandon_without_a_reason_records_a_default_closure_note() -> None:
    """
    Given an abandon with no reason
    When it is enacted
    Then the closure still carries a reason.
    """
    runtime = FakeRuntime(run_state(item("it-1", parked=True)))

    invoke(["abandon", "it-1", "--pr", "9"], runtime, FakeTracker())

    assert runtime.appended[0][1]["closure"] == {"pr": 9, "reason": "abandoned"}


@pytest.mark.parametrize(
    "argv",
    [
        ["redispatch", "it-1"],
        ["abandon", "it-1", "--pr", "3"],
    ],
    ids=["redispatch", "abandon"],
)
def test_leaving_the_parking_lot_needs_a_lane_and_refuses_without_one(argv: list[str]) -> None:
    """
    Given a parked item that was never on a lane
    When it is redispatched or abandoned
    Then the command refuses and appends nothing.

    `item_enqueued` names the lane the item re-enters, and this slice mints no
    lane of its own — discovered work parked before it was ever laned has
    nowhere to return to, which is a human's call.
    """
    runtime = FakeRuntime(run_state(item("it-1", parked=True, lane=None)))
    tracker = FakeTracker()

    code, envelope = invoke(argv, runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_USAGE"
    assert runtime.appended == []
    assert tracker.mutations == []


def test_pr_opened_is_a_world_fact_with_no_tracker_counterpart() -> None:
    """
    Given an in-progress item
    When a PR is recorded as opened
    Then `pr_opened` is appended and the tracker sees nothing — so, by the
    batching rule, no sync either.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="in-progress", work_id="w-1")))
    tracker = FakeTracker()

    code, _ = invoke(["pr-opened", "it-1", "--pr", "42"], runtime, tracker)

    assert code == 0
    assert runtime.appended == [("pr_opened", {"item": "it-1", "pr": 42})]
    assert tracker.mutations == []
    assert tracker.syncs == 0


def test_pr_closed_records_the_closure_and_tells_the_tracker_nothing() -> None:
    """
    Given an item with an open PR
    When the PR is recorded as closed
    Then `pr_closed` carries the next status and reason, and no tracker call
    is made.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="pr-open", pr=42)))
    tracker = FakeTracker()

    invoke(
        ["pr-closed", "it-1", "--pr", "42", "--next", "queued", "--reason", "stale"],
        runtime,
        tracker,
    )

    assert runtime.appended == [
        ("pr_closed", {"item": "it-1", "pr": 42, "next": "queued", "reason": "stale"})
    ]
    assert tracker.mutations == []


def test_merged_takes_its_pr_from_the_fold_and_closes_the_tracker_item() -> None:
    """
    Given an item whose fold holds an open PR
    When the merge is recorded
    Then `item_merged` carries that PR number and the tracker item is closed.

    The PR is read from the fold rather than taken as an argument: closed
    means merged, and the executor must not be able to close against a PR
    number the runtime never saw.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="in-review", pr=42, work_id="w-1")))
    tracker = FakeTracker()

    code, _ = invoke(["merged", "it-1", "--sha", "deadbee"], runtime, tracker)

    assert code == 0
    assert runtime.appended == [("item_merged", {"item": "it-1", "pr": 42, "sha": "deadbee"})]
    assert tracker.mutations == [("close", "w-1")]
    assert tracker.syncs == 1


def test_merged_on_an_item_holding_no_pr_is_refused_with_no_effect() -> None:
    """
    Given an item with no PR reference
    When a merge is recorded for it
    Then E_NO_OPEN_PR comes back, non-retryable, with nothing appended and
    nothing mutated.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="in-review")))
    tracker = FakeTracker()

    code, envelope = invoke(["merged", "it-1", "--sha", "deadbee"], runtime, tracker)

    assert code == 1
    assert envelope["error"] == {
        "code": "E_NO_OPEN_PR",
        "message": "item 'it-1' holds no PR reference to record as merged",
        "retryable": False,
    }
    assert runtime.appended == []
    assert tracker.mutations == []
    assert tracker.syncs == 0


def test_done_is_internal_teardown_and_produces_zero_tracker_calls() -> None:
    """
    Given a merged item
    When teardown is recorded as done
    Then `item_done` is appended and the tracker is untouched.

    Closed means merged; the runtime's `merged -> done` advance has no
    tracker counterpart.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="merged", pr=42, work_id="w-1")))
    tracker = FakeTracker()

    invoke(["done", "it-1"], runtime, tracker)

    assert runtime.appended == [("item_done", {"item": "it-1"})]
    assert tracker.mutations == []
    assert tracker.syncs == 0


# -- S9T1-A6: tracker-handle routing --


def test_a_set_work_id_is_the_handle_the_tracker_sees() -> None:
    """
    Given an item whose work id differs from its runtime id
    When a tracker action is enacted
    Then the tracker sees the work id.
    """
    runtime = FakeRuntime(run_state(item("it-1", work_id="agents-config-9k9.4")))
    tracker = FakeTracker()

    _, envelope = invoke(["start", "it-1"], runtime, tracker)

    assert tracker.handles == ["agents-config-9k9.4"]
    assert envelope["data"]["tracker_id"] == "agents-config-9k9.4"


def test_an_id_outside_the_run_local_grammar_is_its_own_handle() -> None:
    """
    Given an item with no work id whose id is not a run-local slug
    When a tracker action is enacted
    Then the tracker sees the item id.
    """
    runtime = FakeRuntime(run_state(item("agents-config-9k9.4")))
    tracker = FakeTracker()

    invoke(["start", "agents-config-9k9.4"], runtime, tracker)

    assert tracker.handles == ["agents-config-9k9.4"]


def test_a_run_local_slug_has_no_handle_and_surfaces_as_unpromoted() -> None:
    """
    Given an item whose id is a run-local slug and which carries no work id
    When a tracker action would be enacted
    Then the runtime event is still appended, no tracker mutation is issued,
    no sync follows, and the envelope reports success with the item listed
    under `unpromoted`.

    This is the first-class success path, not an error path: the item has no
    tracker handle yet, and minting one takes placement judgment this slice
    does not have.
    """
    runtime = FakeRuntime(run_state(item("disc-1")))
    tracker = FakeTracker()

    code, envelope = invoke(["start", "disc-1"], runtime, tracker)

    assert code == 0
    assert envelope["ok"] is True
    assert envelope["error"] is None
    assert runtime.appended == [("item_started", {"item": "disc-1"})]
    assert tracker.mutations == []
    assert tracker.syncs == 0
    assert envelope["data"]["unpromoted"] == ["disc-1"]
    assert envelope["data"]["tracker_id"] is None


def test_a_run_local_slug_with_a_work_id_does_reach_the_tracker() -> None:
    """
    Given discovered work that has since been promoted, so its run-local id
    carries a work id
    When a tracker action is enacted
    Then the work id is used and nothing is reported unpromoted.

    Pins that the slug grammar is only consulted when there is no handle:
    routing on the id shape alone would strand promoted work forever.
    """
    runtime = FakeRuntime(run_state(item("disc-1", work_id="agents-config-9k9.7")))
    tracker = FakeTracker()

    _, envelope = invoke(["start", "disc-1"], runtime, tracker)

    assert tracker.handles == ["agents-config-9k9.7"]
    assert envelope["data"]["unpromoted"] == []


def test_a_handle_bearing_item_reports_an_empty_unpromoted_list() -> None:
    """
    Given an item with a tracker handle
    When any command touches it
    Then `unpromoted` is present and empty.

    Always present, never absent: the absence of unpromoted work is a
    reported fact, and an omitted key reads as an older protocol.
    """
    runtime = FakeRuntime(run_state(item("it-1", work_id="w-1")))

    _, envelope = invoke(["start", "it-1"], runtime, FakeTracker())

    assert envelope["data"]["unpromoted"] == []


# -- S9T1-A9: sync batching --


def test_one_tracker_mutation_produces_exactly_one_sync() -> None:
    """
    Given a command that makes one tracker mutation
    When it runs
    Then exactly one sync follows it.
    """
    tracker = FakeTracker()

    invoke(["start", "it-1"], FakeRuntime(run_state(item("it-1"))), tracker)

    assert tracker.syncs == 1


def test_several_mutations_in_one_invocation_produce_one_trailing_sync() -> None:
    """
    Given a session that made several tracker mutations
    When it is flushed
    Then exactly one sync is issued, after the last mutation.

    The unit of batching is one invocation, not one mutation: N writes cost
    one sync, never N.
    """
    tracker = FakeTracker()
    session = TrackerSession(tracker)

    session.apply(TrackerVerb.CLAIM, "w-1")
    session.apply(TrackerVerb.CLOSE, "w-2")
    synced = session.flush()

    assert synced is True
    assert tracker.syncs == 1
    assert tracker.verbs == ["claim", "close"]


def test_an_invocation_with_no_mutations_issues_no_sync() -> None:
    """
    Given a session that wrote nothing
    When it is flushed
    Then no sync is issued and the flush reports so.

    The empty boundary: a read-only or tracker-free command must not push a
    sync nobody needs.
    """
    tracker = FakeTracker()

    synced = TrackerSession(tracker).flush()

    assert synced is False
    assert tracker.syncs == 0


def test_a_failed_sync_reports_a_retryable_degradation_naming_its_repair() -> None:
    """
    Given a command whose tracker mutation landed and whose sync then failed
    When the envelope is read
    Then it is a retryable E_SYNC_FAILED naming the repair, and its data
    shows the mutation as applied.

    The command must not be re-run to fix this — that would repeat the
    mutation. The sync is repaired on its own.
    """
    runtime = FakeRuntime(run_state(item("it-1", work_id="w-1")))
    tracker = FakeTracker(fail_on=["sync"])

    code, envelope = invoke(["start", "it-1"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_SYNC_FAILED"
    assert envelope["error"]["retryable"] is True
    assert SYNC_REPAIR in envelope["error"]["message"]
    assert envelope["error"]["data"]["repair"] == SYNC_REPAIR
    assert envelope["error"]["data"]["tracker_called"] is True
    assert envelope["error"]["data"]["synced"] is False
    assert tracker.mutations == [("claim", "w-1")]
