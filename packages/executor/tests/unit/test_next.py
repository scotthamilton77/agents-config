"""`executor next` — the composed open-new-work surface (S9T1-N1..N5).

Every test here drives the real CLI with both ports faked. The command reads
two facade surfaces and writes nothing at all, so most of what it has to prove
is an *absence*: no event, no mutation, no sync, and — when the parked report
fails — no ready list either.
"""

from __future__ import annotations

from typing import Any

from executor.envelope import JsonValue
from tests.unit.fakes import FakeRuntime, FakeTracker, invoke, item, run_state

# A parked row as `work parked` reports one: the facade's shape, its own
# `stale` flag included. Stated as a literal rather than built, because the
# claim under test is that these bytes cross unchanged.
_STALE_ROW: dict[str, JsonValue] = {
    "id": "wg-1",
    "title": "the rebase keeps conflicting",
    "reason": "merge-conflict",
    "category": "machine",
    "parked_at": "2026-06-01T09:00:00+00:00",
    "stale": True,
}
_FRESH_ROW: dict[str, JsonValue] = {
    "id": "wg-2",
    "title": "waiting on an approval",
    "reason": "approval-required",
    "category": "human",
    "parked_at": "2026-07-25T09:00:00+00:00",
    "stale": False,
}
_READY_ROW: dict[str, JsonValue] = {
    "id": "wg-7",
    "title": "wire the executor's open-new-work surface",
    "status": "open",
    "priority": 1,
    "labels": ["harness"],
    "track": "harness",
}


def _tracker(**kwargs: Any) -> FakeTracker:
    """A facade holding both parked rows and one ready item, unless a test
    says otherwise. Non-empty on both sides is the boring case here: an empty
    reply would let a pass-through bug look like agreement."""
    kwargs.setdefault("parked_rows", [_STALE_ROW, _FRESH_ROW])
    kwargs.setdefault("ready_rows", [_READY_ROW])
    return FakeTracker(**kwargs)


def _runtime() -> FakeRuntime:
    """A folded run holding an item. `next` must not consult it — the fake is
    here to record that it was left alone, not to answer anything."""
    return FakeRuntime(run_state(item("it-1")))


def test_the_parked_report_is_read_before_the_ready_list() -> None:
    """
    Given a reachable facade
    When `next` runs
    Then `parked` is read first and `ready` second.

    S9T1-N1. The order is the contract, not an implementation detail: D10's
    rule is that reviewing stuck work is the price of pulling new work, and a
    ready list assembled before the parked report could be handed out beside a
    surfacing that had not been attempted yet.
    """
    runtime, tracker = _runtime(), _tracker()

    code, _ = invoke(["next"], runtime, tracker)

    assert code == 0
    assert tracker.reads == [("parked",), ("ready",)]


def test_the_envelope_carries_the_parked_report_and_the_ready_list() -> None:
    """
    Given a facade holding parked work and ready work
    When `next` runs
    Then the data is exactly `{parked, ready}`, both rows crossing unchanged.

    S9T1-N1/S9T1-D11. The per-item `stale` flags arrive as the facade computed
    them — this package neither recomputes them nor drops them, which is what
    keeps the threshold behind them single-sourced.
    """
    runtime, tracker = _runtime(), _tracker()

    code, envelope = invoke(["next"], runtime, tracker)

    assert code == 0
    assert envelope["ok"] is True
    assert envelope["data"] == {
        "parked": [_STALE_ROW, _FRESH_ROW],
        "ready": [_READY_ROW],
    }


def test_a_failed_parked_read_suppresses_the_ready_list_entirely() -> None:
    """
    Given a facade whose parked report fails and whose ready list would not
    When `next` runs
    Then a typed failure envelope comes back, no ready read is issued, and no
    ready item reaches the caller.

    S9T1-N2, and the inverse control matters: the ready side is stocked, so a
    suppressed list cannot be mistaken for an empty queue. Degrading to "here
    is the ready work anyway" is the exact failure this AC exists to prevent —
    it inverts D10 by handing out new work while the stuck work goes unseen.
    """
    runtime, tracker = _runtime(), _tracker(fail_on=["parked"])

    code, envelope = invoke(["next"], runtime, tracker)

    assert code == 1
    assert envelope["ok"] is False
    assert envelope["data"] is None
    assert envelope["error"]["code"] == "E_TRACKER_SUBPROCESS"
    assert envelope["error"]["retryable"] is True
    # The read never got as far as being recorded, which is the strongest form
    # of "the ready list was not fetched": no second read exists to inspect.
    assert tracker.reads == []
    assert _READY_ROW["id"] not in str(envelope)


def test_a_failed_ready_read_is_reported_rather_than_answered_with_the_parked_half() -> None:
    """
    Given a facade whose parked report succeeds and whose ready list fails
    When `next` runs
    Then the envelope is the typed failure, carrying no partial data.

    The other half of S9T1-N2's fail-closed reading. `{parked, ready}` is one
    answer: emitting the parked half under `ok: true` would report a queue
    state nobody read.
    """
    runtime, tracker = _runtime(), _tracker(fail_on=["ready"])

    code, envelope = invoke(["next"], runtime, tracker)

    assert code == 1
    assert envelope["data"] is None
    assert envelope["error"]["code"] == "E_TRACKER_SUBPROCESS"
    assert tracker.reads == [("parked",)]


def test_the_whole_command_touches_neither_plane() -> None:
    """
    Given a successful run
    When the two ports are inspected
    Then no event was appended, no tracker mutation was recorded, no sync was
    issued, and the runtime was not even read.

    S9T1-N3. Zero mutations means zero syncs by S9T1-D9, so the sync count is
    part of the claim rather than a bonus. The untouched fold is the same
    property one level further out: `next` has no pairing row, so it needs no
    folded state, and consulting one would make the command fail on a machine
    whose grind run simply does not exist.
    """
    runtime, tracker = _runtime(), _tracker()

    code, _ = invoke(["next"], runtime, tracker)

    assert code == 0
    assert runtime.appended == []
    assert runtime.state_reads == 0
    assert tracker.mutations == []
    assert tracker.syncs == 0


def test_a_failed_read_leaves_both_planes_untouched_too() -> None:
    """
    Given a facade whose parked report fails
    When `next` runs
    Then nothing was appended, mutated or synced.

    The failure path of S9T1-N3: a read-only command has no owed sync to flush
    on the way out, so the refusal cannot strand anything either.
    """
    runtime, tracker = _runtime(), _tracker(fail_on=["parked"])

    invoke(["next"], runtime, tracker)

    assert runtime.appended == []
    assert tracker.mutations == []
    assert tracker.syncs == 0


def test_an_empty_parked_report_is_an_empty_list_not_an_absent_key() -> None:
    """
    Given a facade with nothing parked
    When `next` runs
    Then `parked` is present and empty.

    S9T1-N4, the empty boundary — and the same principle the facade's own
    `parked_stale` block applies: "no stale parked work" is a reported fact. A
    consumer testing for the key would read an absent one as "the report was
    not run", which is exactly the ambiguity fail-closed reading exists to
    remove.
    """
    runtime = _runtime()
    tracker = FakeTracker(parked_rows=[], ready_rows=[_READY_ROW])

    code, envelope = invoke(["next"], runtime, tracker)

    assert code == 0
    assert envelope["data"] == {"parked": [], "ready": [_READY_ROW]}


def test_an_empty_facade_still_answers_with_both_keys() -> None:
    """
    Given a facade with nothing parked and nothing ready
    When `next` runs
    Then both keys are present and empty, and the command still succeeds.

    Nothing to do is an answer, not a failure.
    """
    runtime = _runtime()
    tracker = FakeTracker(parked_rows=[], ready_rows=[])

    code, envelope = invoke(["next"], runtime, tracker)

    assert code == 0
    assert envelope["data"] == {"parked": [], "ready": []}


def test_the_stale_threshold_is_passed_through_rather_than_interpreted() -> None:
    """
    Given `--stale-days 30`
    When `next` runs
    Then the parked read receives 30.

    S9T1-N4. The executor holds no threshold of its own: it forwards the
    caller's number and reads whatever `stale` flags come back.
    """
    runtime, tracker = _runtime(), _tracker()

    code, _ = invoke(["next", "--stale-days", "30"], runtime, tracker)

    assert code == 0
    assert tracker.reads == [("parked", "30"), ("ready",)]


def test_omitting_the_threshold_passes_no_threshold_at_all() -> None:
    """
    Given no `--stale-days`
    When `next` runs
    Then the parked read receives none, leaving the facade's default (S2-D4)
    to stand.

    S9T1-N4's load-bearing half. Defaulting to `7` here would put a second
    copy of the threshold in the tree, and the two would diverge the first
    time either side was tuned — silently, since both would look right alone.
    """
    runtime, tracker = _runtime(), _tracker()

    invoke(["next"], runtime, tracker)

    assert tracker.reads[0] == ("parked",)


def test_two_consecutive_runs_return_identical_envelopes() -> None:
    """
    Given an unchanged facade
    When `next` runs twice
    Then both envelopes are identical and neither plane moved.

    S9T1-N5. A read-only command is idempotent by construction, so this is a
    guard rather than a discovery: it fails the moment `next` grows a counter,
    a marker note, or any other trace of having been run.
    """
    runtime, tracker = _runtime(), _tracker()

    first_code, first = invoke(["next"], runtime, tracker)
    second_code, second = invoke(["next"], runtime, tracker)

    assert (first_code, second_code) == (0, 0)
    assert first == second
    assert runtime.appended == []
    assert tracker.mutations == []
    assert tracker.syncs == 0
    assert tracker.reads == [("parked",), ("ready",), ("parked",), ("ready",)]


def test_next_names_no_item() -> None:
    """
    Given a positional argument
    When `next` runs
    Then it is a usage failure.

    `next` is the surface that reports which items there are; naming one is a
    caller confusing it with an enacting verb, and argparse's complaint
    reaches stdout as an envelope like every other failure.
    """
    runtime, tracker = _runtime(), _tracker()

    code, envelope = invoke(["next", "it-1"], runtime, tracker)

    assert code == 1
    assert envelope["error"]["code"] == "E_USAGE"
    assert tracker.reads == []
