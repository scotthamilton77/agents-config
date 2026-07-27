"""Every S9T1-D12 row driven end to end through the CLI with both ports faked:
the pairing it enacts, the handle it routes to, and the sync that follows."""

from __future__ import annotations

import pytest

from executor.enact import SYNC_REPAIR, TrackerSession
from executor.pairing import FAILURE_REASONS, SCHEDULING_REASONS, TrackerVerb
from tests.unit.fakes import FakeRuntime, FakeTracker, FlaggingRuntime, invoke, item, run_state


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


def test_an_empty_park_note_takes_the_default_rather_than_being_passed_through() -> None:
    """
    Given a park whose note is the empty string
    When it is enacted
    Then the reason code is the note on both sides.

    The fold rejects an empty note, and this row is tracker-first — passing
    one through would park the tracker, have the append refused, and leave
    every retry repeating that rather than converging.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="pr-open", pr=7, work_id="w-1")))
    tracker = FakeTracker()

    code, _ = invoke(["park", "it-1", "--reason", "ci-failure", "--note", ""], runtime, tracker)

    assert code == 0
    assert tracker.mutations == [("park", "w-1", "ci-failure", "ci-failure")]
    assert runtime.appended == [
        ("item_parked", {"item": "it-1", "reason": "ci-failure", "note": "ci-failure"})
    ]


def test_a_flagged_append_on_a_tracker_free_row_still_reports_it_as_appended() -> None:
    """
    Given a row that calls no tracker verb, whose event the runtime wrote and
    then flagged
    When the envelope is read
    Then it reports the event as appended and carries no private marker.

    The no-sync path is the one the tracker-free rows always take, so a marker
    consumed only on the owed-sync path would leak into the public contract
    for exactly those rows.
    """
    runtime = FlaggingRuntime(run_state(item("it-1", status="in-progress", work_id="w-1")))
    tracker = FakeTracker()

    code, envelope = invoke(["pr-opened", "it-1", "--pr", "42"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["data"]["event_appended"] is True
    assert envelope["error"]["data"]["tracker_called"] is False
    assert "_event_was_written" not in envelope["error"]["data"]
    assert tracker.mutations == []


def test_a_refusal_that_touched_neither_plane_carries_no_report() -> None:
    """
    Given a refusal reached before either plane moved
    When the envelope is read
    Then the error carries no data block.

    A report describes what happened; nothing did. Attaching one to every
    refusal would make an empty report indistinguishable from a real one.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="in-review")))

    _, envelope = invoke(["done", "it-1"], runtime, FakeTracker())

    assert "data" not in envelope["error"]


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


@pytest.mark.parametrize("reason", FAILURE_REASONS)
def test_a_failure_axis_park_on_an_item_with_no_pr_is_refused(reason: str) -> None:
    """
    Given an item holding no PR reference
    When a failure-axis park is requested for it
    Then E_NO_OPEN_PR comes back with zero tracker calls and zero events.

    The runtime's fold refuses this park, so enacting the tracker half would
    leave the two planes permanently disagreeing: the tracker parked, the
    runtime holding an anomaly and an unparked item, and every retry
    reproducing exactly that.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="in-progress", work_id="w-1")))
    tracker = FakeTracker()

    code, envelope = invoke(["park", "it-1", "--reason", reason], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_NO_OPEN_PR"
    assert envelope["error"]["retryable"] is False
    assert runtime.appended == []
    assert tracker.mutations == []
    assert tracker.syncs == 0


def test_a_park_the_tracker_already_holds_under_another_reason_is_refused() -> None:
    """
    Given a tracker already parked as `ci-failure` while the runtime park is
    missing — what a tracker-first invocation leaves when its append failed
    When the park is retried naming a different reason
    Then it is refused and nothing is appended.

    `work park` on an already-parked item reports the *existing* stint and
    mints nothing. Taking that reply as the requested mutation would append
    `merge-conflict` to the runtime while the tracker kept `ci-failure` —
    and neither plane could detect it, since each is internally consistent.
    No retry converges that, which is exactly what S9T1-A7's "status, label
    and grind agreement" and S9T1-D6's single-failed-call bound rule out.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="pr-open", pr=7, work_id="w-1")))
    tracker = FakeTracker(parked_as="ci-failure")

    code, envelope = invoke(["park", "it-1", "--reason", "merge-conflict"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_ITEM_PARKED"
    assert "ci-failure" in envelope["error"]["message"]
    assert runtime.appended == []
    # The facade was asked and answered; it minted nothing, so nothing is owed
    # a sync either.
    assert tracker.verbs == ["park"]
    assert tracker.syncs == 0


def test_a_park_the_tracker_already_holds_under_the_same_reason_proceeds() -> None:
    """
    Given a tracker parked as `ci-failure` and a runtime park still missing
    When the park is retried with that same reason
    Then the runtime append lands, converging the two planes.

    The inverse, and the reason this is a comparison rather than a blanket
    refusal: re-running the *same* command is exactly how a half-landed
    tracker-first pair is meant to converge.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="pr-open", pr=7, work_id="w-1")))
    tracker = FakeTracker(parked_as="ci-failure")

    code, _ = invoke(["park", "it-1", "--reason", "ci-failure"], runtime, tracker)

    assert code == 0
    assert runtime.event_types == ["item_parked"]
    assert tracker.syncs == 1


def test_re_parking_under_a_different_reason_is_refused() -> None:
    """
    Given an item already parked for one reason
    When a park is requested naming a different one
    Then it is refused with nothing appended and nothing mutated.

    There is no re-park transition — the parking lot's one exit is an enqueue
    — so this cannot be enacted on either plane: the append would flag, and
    the facade's park is a no-op that keeps the reason it already has.
    Treating it as a retry would report success for a transition neither
    plane made, and leave no way to notice the planes disagree.
    """
    runtime = FakeRuntime(
        run_state(item("it-1", status="pr-open", pr=7, park_reason="ci-failure", work_id="w-1"))
    )
    tracker = FakeTracker()

    code, envelope = invoke(["park", "it-1", "--reason", "merge-conflict"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_ITEM_PARKED"
    assert "ci-failure" in envelope["error"]["message"]
    assert runtime.appended == []
    assert tracker.mutations == []


def test_re_parking_under_the_same_reason_with_a_new_note_is_still_a_retry() -> None:
    """
    Given an item parked for a reason, re-parked for that same reason with
    differently worded text
    When the command runs
    Then it is the idempotent retry, not a refusal.

    The reason is the typed fact both planes record; the note is free text a
    retry may legitimately word differently, so matching on it would refuse
    real retries.
    """
    runtime = FakeRuntime(
        run_state(item("it-1", status="pr-open", pr=7, park_reason="ci-failure", work_id="w-1"))
    )
    tracker = FakeTracker()

    code, envelope = invoke(
        ["park", "it-1", "--reason", "ci-failure", "--note", "reworded"], runtime, tracker
    )

    assert code == 0
    assert envelope["data"]["event_appended"] is False
    assert tracker.mutations == [("park", "w-1", "ci-failure", "reworded")]


def test_parking_an_untyped_park_under_a_typed_reason_is_refused() -> None:
    """
    Given an item parked without a typed reason, as a closure whose text named
    no vocabulary member leaves it
    When a typed park is requested
    Then it is refused.

    An untyped park is still a park, and typing it after the fact is not a
    transition either plane has.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="pr-open", pr=7, parked=True)))

    code, envelope = invoke(["park", "it-1", "--reason", "ci-failure"], runtime, FakeTracker())

    assert code == 1
    assert "already recorded" in envelope["error"]["message"]
    assert "ci-failure" in envelope["error"]["message"]


@pytest.mark.parametrize("status", ["merged", "done"])
def test_a_park_on_a_terminal_item_is_refused_before_the_tracker_is_touched(
    status: str,
) -> None:
    """
    Given a merge whose tracker close has not landed — the runtime terminal,
    the tracker item still open
    When a failure-axis park is requested
    Then it is refused with nothing mutated.

    That partial state is legitimate: world-facts lead with the runtime, so a
    failed close leaves exactly this. The item still holds its PR, so the
    no-PR check does not catch it — and a terminal item is not parkable, so
    enacting would park the tracker against a runtime that stays merged, with
    a non-retryable failure and no path back.
    """
    runtime = FakeRuntime(run_state(item("it-1", status=status, pr=42, work_id="w-1")))
    tracker = FakeTracker()

    code, envelope = invoke(["park", "it-1", "--reason", "ci-failure"], runtime, tracker)

    assert code == 1
    assert status in envelope["error"]["message"]
    assert runtime.appended == []
    assert tracker.mutations == []
    assert tracker.syncs == 0


def test_start_on_a_parked_item_is_refused_before_the_claim() -> None:
    """
    Given a queued item that a scheduling-axis park took out of play
    When it is started
    Then E_ITEM_PARKED comes back with nothing claimed.

    Parked is a flag beside a status, not a status: a scheduling park leaves
    the item `queued`, so the startable-status check waves it straight
    through. The fold treats a parked item as absent, so claiming first would
    put the tracker in progress against a runtime that stays parked.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="queued", parked=True, work_id="w-1")))
    tracker = FakeTracker()

    code, envelope = invoke(["start", "it-1"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_ITEM_PARKED"
    assert envelope["error"]["retryable"] is False
    assert runtime.appended == []
    assert tracker.mutations == []
    assert tracker.syncs == 0


def test_start_on_a_parked_in_progress_item_is_refused_not_called_idempotent() -> None:
    """
    Given a parked item whose status is still `in-progress`
    When it is started
    Then it is refused rather than reported as already started.

    The idempotency skip would otherwise claim the tracker item for work the
    runtime has taken out of play.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="in-progress", parked=True, work_id="w-1")))
    tracker = FakeTracker()

    code, envelope = invoke(["start", "it-1"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_ITEM_PARKED"
    assert tracker.mutations == []


@pytest.mark.parametrize("status", ["merged", "done", "pr-open"])
def test_start_is_refused_from_any_status_the_runtime_would_flag(status: str) -> None:
    """
    Given an item past the queue
    When it is started
    Then the claim is refused rather than issued.

    The other tracker-first row: the runtime accepts `item_started` only from
    `queued`, so claiming first and appending second would move the tracker
    against a runtime that does not follow.
    """
    runtime = FakeRuntime(run_state(item("it-1", status=status, work_id="w-1")))
    tracker = FakeTracker()

    code, _ = invoke(["start", "it-1"], runtime, tracker)

    assert code == 1
    assert runtime.appended == []
    assert tracker.mutations == []


@pytest.mark.parametrize("status", ["queued", "in-progress", "pr-open", "in-review", "blocked"])
def test_park_is_allowed_from_every_status_the_runtime_accepts(status: str) -> None:
    """
    Given each non-terminal status
    When a failure-axis park is requested
    Then it proceeds.

    The inverse of the terminal refusal, and the guard against over-refusing:
    `blocked` and `waiting-human` both legally hold an open PR, and those are
    exactly where an `approval-required` or `ci-failure` park lands.
    """
    runtime = FakeRuntime(run_state(item("it-1", status=status, pr=42, work_id="w-1")))

    code, _ = invoke(["park", "it-1", "--reason", "ci-failure"], runtime, FakeTracker())

    assert code == 0
    assert runtime.event_types == ["item_parked"]


@pytest.mark.parametrize("reason", SCHEDULING_REASONS)
def test_a_scheduling_axis_park_needs_no_pr(reason: str) -> None:
    """
    Given an item that never had a PR
    When a scheduling-axis park is requested
    Then it proceeds.

    The inverse of the refusal above, and the reason the check is keyed on the
    axis: a sequencing decision makes no claim about a PR, so demanding one
    would make the whole axis unusable for the work it exists to describe.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="queued")))

    code, _ = invoke(["park", "it-1", "--reason", reason], runtime, FakeTracker())

    assert code == 0
    assert runtime.event_types == ["item_parked"]


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


def test_a_redispatch_is_refused_once_the_item_has_moved_on() -> None:
    """
    Given an item redispatched and then started
    When a delayed duplicate redispatch arrives
    Then it is refused rather than treated as a retry.

    "Not parked" is also true of every state the item reaches afterwards. Read
    as a retry, the append is suppressed but the tracker verb is still
    re-issued — and the facade refuses an item it has already moved on from,
    turning a completed command into a transport failure plus a needless sync.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="in-progress", work_id="w-1")))
    tracker = FakeTracker()

    code, envelope = invoke(["redispatch", "it-1"], runtime, tracker)

    assert code == 1
    assert "is not parked" in envelope["error"]["message"]
    assert runtime.appended == []
    assert tracker.mutations == []
    assert tracker.syncs == 0


@pytest.mark.parametrize("status", ["queued", "blocked"])
def test_a_redispatch_retry_is_still_recognized_where_the_enqueue_left_it(status: str) -> None:
    """
    Given an item sitting where an enqueue leaves it
    When the redispatch is re-run
    Then it is the idempotent retry.

    The inverse, and the reason this is a narrowing rather than a removal: a
    response-lost redispatch has to converge, and `item_enqueued` leaves the
    item `queued`, or `blocked` when it re-enters with unresolved edges.
    """
    runtime = FakeRuntime(run_state(item("it-1", status=status, work_id="w-1")))
    tracker = FakeTracker()

    code, envelope = invoke(["redispatch", "it-1"], runtime, tracker)

    assert code == 0
    assert envelope["data"]["event_appended"] is False
    assert tracker.verbs == ["redispatch"]


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
    runtime = FakeRuntime(run_state(item("it-1", parked=True, pr=42, work_id="w-1")))
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


def test_abandon_naming_a_pr_the_item_is_not_on_is_refused() -> None:
    """
    Given a parked item on PR 7
    When it is abandoned naming PR 8
    Then it is refused before the facade is called.

    The closure this writes goes into the log as the record, and the fold
    compares it against nothing — so a typo or a delayed notification for a
    superseded PR would be recorded as fact while the command reported
    success. Tracker-first makes the ordering matter: the refusal has to
    precede the facade call.
    """
    runtime = FakeRuntime(run_state(item("it-1", parked=True, pr=7, work_id="w-1")))
    tracker = FakeTracker()

    code, envelope = invoke(["abandon", "it-1", "--pr", "8"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_USAGE"
    assert "7" in envelope["error"]["message"]
    assert runtime.appended == []
    assert tracker.mutations == []


def test_abandoning_an_item_that_never_had_a_pr_is_refused() -> None:
    """
    Given parked work holding no PR reference
    When it is abandoned
    Then E_NO_OPEN_PR comes back.

    An abandon records a PR's closure, and there is no PR to close. Getting
    such an item back in play is a redispatch, which records no closure.
    """
    runtime = FakeRuntime(run_state(item("it-1", parked=True, work_id="w-1")))

    code, envelope = invoke(["abandon", "it-1", "--pr", "8"], runtime, FakeTracker())

    assert code == 1
    assert envelope["error"]["code"] == "E_NO_OPEN_PR"


def test_an_abandon_retry_is_recognized_once_the_fold_clears_the_reference() -> None:
    """
    Given the state S9T1-B7 produces for a completed abandon — the item back
    on its lane, its PR reference cleared by the closure, and that closure on
    record
    When the abandon is re-run
    Then it succeeds, re-issuing only the facade call.

    A cleared reference plus a closure for that PR is unique to an abandon:
    B7 has the fold clear the reference when it interprets an
    `item_enqueued` closure, where an ordinary `pr_closed` records its
    closure and leaves the reference in place.

    This pins the B7 contract, not today's fold — today the reference
    survives an abandon, so this path is unreachable and the command refuses
    instead (below). The gap closes when B7 lands, with no change here.
    """
    runtime = FakeRuntime(
        run_state(item("it-1", status="queued", work_id="w-1"), closures=[("it-1", 8)])
    )
    tracker = FakeTracker()

    code, envelope = invoke(["abandon", "it-1", "--pr", "8"], runtime, tracker)

    assert code == 0
    assert runtime.appended == []
    assert envelope["data"]["event_appended"] is False
    assert tracker.mutations == [("abandon", "w-1")]


def test_abandon_has_no_idempotent_retry_path_before_that_fold_change() -> None:
    """
    Given an ordinary closure that left the item queued with its PR closed —
    a state that looks exactly like a completed abandon
    When abandon is invoked
    Then it is refused rather than reported as already done.

    Today's fold records an abandon's closure without interpreting it, so
    the PR reference survives and this state is exactly what an ordinary
    closure leaves behind. Every weaker proxy — position, surviving PR
    reference, ledger membership — matches it, so accepting one would claim a
    closure that exists nowhere and issue a tracker write for a transition
    that never happened.
    """
    runtime = FakeRuntime(
        run_state(item("it-1", status="queued", pr=8, work_id="w-1"), closures=[("it-1", 8)])
    )
    tracker = FakeTracker()

    code, envelope = invoke(["abandon", "it-1", "--pr", "8"], runtime, tracker)

    assert code == 1
    assert "is not parked" in envelope["error"]["message"]
    assert runtime.appended == []
    assert tracker.mutations == []
    assert tracker.syncs == 0


def test_abandoning_an_item_that_was_never_parked_is_refused() -> None:
    """
    Given an ordinary queued item that was never parked and holds no PR
    When it is abandoned
    Then it is refused rather than reported as already done.

    Being out of the parking lot is not evidence of an abandon — an item that
    was never in it is out of it too, and answering "already abandoned"
    claims a closure that exists nowhere.
    """
    runtime = FakeRuntime(run_state(item("it-1", work_id="w-1")))
    tracker = FakeTracker()

    code, envelope = invoke(["abandon", "it-1", "--pr", "8"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_USAGE"
    assert "is not parked" in envelope["error"]["message"]
    assert runtime.appended == []
    assert tracker.mutations == []


def test_abandoning_an_unparked_item_with_a_live_pr_is_refused() -> None:
    """
    Given an item with an open PR, not parked
    When it is abandoned naming that PR
    Then it is refused.

    The PR reference matches, but the item is not where an enqueue leaves it
    — it is mid-review, with the PR still open. Nothing has been abandoned.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="pr-open", pr=8, work_id="w-1")))

    code, envelope = invoke(["abandon", "it-1", "--pr", "8"], runtime, FakeTracker())

    assert code == 1
    assert "is not parked" in envelope["error"]["message"]


def test_a_merge_retry_naming_a_different_commit_is_refused() -> None:
    """
    Given an item recorded as merged at one commit
    When the merge is re-run naming another
    Then it is refused rather than reported as already applied.

    "Already merged" is not the same claim as "already merged at this
    commit": answering a different commit with success reports a fact no
    event holds, and re-issues the tracker close behind it.
    """
    runtime = FakeRuntime(
        run_state(
            item("it-1", status="merged", pr=42, work_id="w-1"), merged_shas={"it-1": "9fceb02"}
        )
    )
    tracker = FakeTracker()

    code, envelope = invoke(["merged", "it-1", "--sha", "badc0de"], runtime, tracker)

    assert code == 1
    assert "9fceb02" in envelope["error"]["message"]
    assert tracker.mutations == []


def test_a_merge_retry_naming_the_recorded_commit_still_converges() -> None:
    """
    Given an item recorded as merged at a commit
    When the merge is re-run naming that same commit
    Then it succeeds and the tracker close is re-issued.
    """
    runtime = FakeRuntime(
        run_state(
            item("it-1", status="merged", pr=42, work_id="w-1"), merged_shas={"it-1": "9fceb02"}
        )
    )
    tracker = FakeTracker()

    code, _ = invoke(["merged", "it-1", "--sha", "9fceb02"], runtime, tracker)

    assert code == 0
    assert tracker.mutations == [("close", "w-1")]


def test_abandon_without_a_reason_records_a_default_closure_note() -> None:
    """
    Given an abandon with no reason
    When it is enacted
    Then the closure still carries a reason.
    """
    runtime = FakeRuntime(run_state(item("it-1", parked=True, pr=9)))

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
    runtime = FakeRuntime(run_state(item("it-1", parked=True, pr=3, lane=None)))
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


def test_a_closure_against_an_item_that_never_opened_a_pr_is_refused() -> None:
    """
    Given an item waiting on a human, having never opened a PR
    When a closure is recorded for it
    Then it is refused with nothing appended.

    `waiting-human` is reachable straight from `queued`, and the fold checks
    neither that the item holds a PR nor that the event's number is its own —
    so without this the closure would be invented and the waiting item
    silently moved to `queued` or parked.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="waiting-human", work_id="w-1")))
    tracker = FakeTracker()

    code, envelope = invoke(
        ["pr-closed", "it-1", "--pr", "42", "--next", "queued", "--reason", "stale"],
        runtime,
        tracker,
    )

    assert code == 1
    assert envelope["error"]["code"] == "E_NO_OPEN_PR"
    assert runtime.appended == []
    assert tracker.mutations == []


def test_a_closure_naming_a_pr_the_item_is_not_on_is_refused() -> None:
    """
    Given an item on PR 42
    When a closure is recorded for PR 41
    Then it is refused with nothing appended.

    The fold does not compare the event's PR against the item's own, so this
    would tear down the live review cycle and record a closure for a PR the
    item is not on — a delayed notification for a superseded PR is enough to
    do it. The item's reference is the only thing that says which cycle a
    closure belongs to.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="pr-open", pr=42)))

    code, envelope = invoke(
        ["pr-closed", "it-1", "--pr", "41", "--next", "queued", "--reason", "stale"],
        runtime,
        FakeTracker(),
    )

    assert code == 1
    assert envelope["error"]["code"] == "E_USAGE"
    assert "42" in envelope["error"]["message"]
    assert runtime.appended == []


@pytest.mark.parametrize("status", ["queued", "in-progress", "blocked", "merged", "done"])
def test_a_merge_is_refused_from_any_status_holding_no_live_pr(status: str) -> None:
    """
    Given an item whose PR is not live
    When a merge is recorded
    Then it is refused or reported as already recorded, never appended.

    `merged`/`done` are the idempotent retry; the rest the runtime would flag.
    Either way nothing new reaches the log.
    """
    runtime = FakeRuntime(run_state(item("it-1", status=status, pr=42, work_id="w-1")))

    invoke(["merged", "it-1", "--sha", "deadbee"], runtime, FakeTracker())

    assert runtime.appended == []


def test_done_is_refused_before_the_merge_it_tears_down() -> None:
    """
    Given an item still in review
    When teardown is recorded as done
    Then it is refused with nothing appended.

    `item_done` follows a merge; the runtime accepts it from nowhere else.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="in-review", pr=42)))

    code, envelope = invoke(["done", "it-1"], runtime, FakeTracker())

    assert code == 1
    assert "in-review" in envelope["error"]["message"]
    assert runtime.appended == []


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
    assert envelope["error"]["code"] == "E_NO_OPEN_PR"
    assert envelope["error"]["retryable"] is False
    assert "holds no PR reference" in envelope["error"]["message"]
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


def test_a_tracker_write_that_landed_before_a_failed_exit_is_still_synced() -> None:
    """
    Given a facade call that completed and whose process then failed
    When the envelope is read
    Then the write was synced anyway and the failure still reported.

    An `ok: true` envelope means the facade finished its work; a non-zero exit
    after that is the process failing around a write that landed. Treating it
    as "no mutation" would strand that write unsynced on the local plane.
    """
    runtime = FakeRuntime(run_state(item("it-1", work_id="w-1")))
    tracker = FakeTracker(fail_after_write=["claim"])

    code, envelope = invoke(["start", "it-1"], runtime, tracker)

    assert code == 1
    assert tracker.syncs == 1
    assert envelope["error"]["data"]["tracker_called"] is True
    assert envelope["error"]["data"]["synced"] is True
    assert runtime.appended == []
    assert "_tracker_write_landed" not in envelope["error"]["data"]


def test_a_park_mismatch_owes_no_sync_because_the_facade_minted_nothing() -> None:
    """
    Given a park refused for naming a different reason than the tracker holds
    When the envelope is read
    Then no sync was issued.

    Only the facade's idempotent-replay branch can return a different reason,
    and that branch mints nothing — its mint branch returns the reason it was
    asked for. So this refusal has no write to push, and recording a mutation
    for it would sync an empty change.
    """
    runtime = FakeRuntime(run_state(item("it-1", status="pr-open", pr=7, work_id="w-1")))
    tracker = FakeTracker(parked_as="ci-failure")

    code, _ = invoke(["park", "it-1", "--reason", "merge-conflict"], runtime, tracker)

    assert code == 1
    assert tracker.syncs == 0


def test_a_mutation_that_landed_before_a_failed_append_is_still_synced() -> None:
    """
    Given a tracker-first row whose tracker write landed and whose runtime
    append then failed
    When the envelope is read
    Then the owed sync was issued anyway, and the reported failure is still
    the append's.

    The sync is owed by the mutation, not by the command succeeding — without
    this the write sits unsynced on the local plane until someone happens to
    retry. The append failure stays the cause; the sync is not a second story.
    """
    runtime = FakeRuntime(run_state(item("it-1", work_id="w-1")), fail_on=["item_started"])
    tracker = FakeTracker()

    code, envelope = invoke(["start", "it-1"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_RUNTIME_SUBPROCESS"
    assert tracker.mutations == [("claim", "w-1")]
    assert tracker.syncs == 1
    assert envelope["error"]["data"]["synced"] is True
    assert envelope["error"]["data"]["tracker_called"] is True
    assert envelope["error"]["data"]["event_appended"] is False


def test_an_event_the_runtime_wrote_but_flagged_is_reported_as_appended() -> None:
    """
    Given a tracker-first row whose tracker write landed and whose event the
    runtime wrote and then flagged as inapplicable
    When the error data is read
    Then it reports the event as appended.

    The runtime writes the event before reporting that it did not apply, so
    the two are separate facts. Reporting `event_appended: false` against a
    log that holds the event would mislead exactly the repair and audit
    tooling the field exists for.
    """
    runtime = FlaggingRuntime(run_state(item("it-1", work_id="w-1")))
    tracker = FakeTracker()

    code, envelope = invoke(["start", "it-1"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_USAGE"
    assert envelope["error"]["data"]["event_appended"] is True
    assert envelope["error"]["data"]["tracker_called"] is True
    assert envelope["error"]["data"]["synced"] is True
    # The port/enact marker is consumed, not republished into the envelope.
    assert "_event_was_written" not in envelope["error"]["data"]


def test_an_owed_sync_that_also_fails_is_reported_under_the_original_cause() -> None:
    """
    Given a landed tracker write, a failed append, and a sync that fails too
    When the envelope is read
    Then the append failure is still the reported code, with the sync failure
    and its repair as detail.

    Two things went wrong; the one that stopped the command is the one an
    operator needs first.
    """
    runtime = FakeRuntime(run_state(item("it-1", work_id="w-1")), fail_on=["item_started"])
    tracker = FakeTracker(fail_on=["sync"])

    _, envelope = invoke(["start", "it-1"], runtime, tracker)

    assert envelope["error"]["code"] == "E_RUNTIME_SUBPROCESS"
    assert envelope["error"]["data"]["synced"] is False
    assert envelope["error"]["data"]["repair"] == SYNC_REPAIR
    assert "scripted sync failure" in envelope["error"]["data"]["sync_error"]


def test_a_refusal_that_mutated_nothing_still_syncs_nothing() -> None:
    """
    Given a runtime-first row whose append failed before any tracker write
    When the envelope is read
    Then no sync was issued.

    The owed-sync rule is owed by a mutation, not by a failure: a command that
    wrote nothing has nothing to push.
    """
    runtime = FakeRuntime(
        run_state(item("it-1", status="in-review", pr=42, work_id="w-1")),
        fail_on=["item_merged"],
    )
    tracker = FakeTracker()

    code, _ = invoke(["merged", "it-1", "--sha", "deadbee"], runtime, tracker)

    assert code == 1
    assert tracker.mutations == []
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
