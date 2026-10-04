"""Pre-rulings: the impact of an option weighed before the human takes it.

Settling a decision opens the decisions resting on it, and the expert weighs
each of their options against the decisions that option marks, in the
background. A pre-ruling holds nothing: its target stays answerable while it
runs and after it fails. Its result is cached, and lands only when the human
takes that option with no note while the board under it has not moved. Then no
task starts and nothing waits. A pre-ruling the board moved under is never
consumed, and is weighed again.

Everything here is read off the log and the replay, the way a restarted backend
would read it.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from conftest import TIMEOUT, ScriptedCli, SpyDriver, document, run_turns

from grillui.dispatch import record_dispatch
from grillui.drivers import HeavyDriver, record_reply, resume_file, write_resume
from grillui.lane import AgentUnreachableError, Lane, open_announcements
from grillui.projector import replay
from grillui.schemas import (
    HEAVY_TIER,
    MAP_CHANNEL,
    STATUS_KIND,
    STATUS_PHASE_COMPOSING,
    STATUS_PHASE_ERROR,
    STATUS_PHASE_REPLIED,
    DispatchContext,
    EventSubmission,
    LogEntry,
    MootnessObligation,
)
from grillui.session import open_session
from grillui.tiers import TierConfig

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from grillui.log import SessionLog

# The channel the background turns run on. Spelled out rather than imported,
# because the bytes on the log are the contract this file pins.
BACKGROUND = "pre-ruling"

PLAIN = [{"id": "a", "text": "Yes"}, {"id": "z", "text": "No"}]
MARKS = {"id": "b", "text": "Rebuild it", "puts_in_question": ["d2"]}
ALSO = {"id": "c", "text": "Replace it", "puts_in_question": ["d2"]}
DEEPER = {"id": "b", "text": "Split it", "puts_in_question": ["d4"]}


def _seed(log: SessionLog) -> None:
    """d9 is settled before the session's lane starts, and d2 rests on it. d1
    rests on d0, and two of its options mark d2. d3 rests on d1, so settling d0
    does not open it, and its option marks d4. d5 is marked by nobody."""
    for node, options, prereqs in (
        ("d9", PLAIN, []),
        ("d0", PLAIN, []),
        ("d1", [PLAIN[0], MARKS, ALSO], ["d0"]),
        ("d2", PLAIN, ["d9"]),
        ("d3", [PLAIN[0], DEEPER], ["d1"]),
        ("d4", PLAIN, []),
        ("d5", PLAIN, []),
    ):
        _accepted(
            log,
            EventSubmission(
                kind="add-node",
                actor="grill-master",
                idempotency_key=f"seed-{node}",
                payload={
                    "target": node,
                    "short": node,
                    "title": f"Which {node}?",
                    "body": "Decide.",
                    "prereqs": prereqs,
                    "options": options,
                },
            ),
        )
    _accepted(log, _answer("d9", "a"))


def _accepted(log: SessionLog, event: EventSubmission) -> int:
    receipt = log.submit([event], log.epoch)[0]
    assert receipt.status == "accepted", receipt
    return receipt.seq


def _answer(node: str, option: str = "b", note: str | None = None) -> EventSubmission:
    given: dict[str, Any] = {"option": option}
    if note is not None:
        given["text"] = note
    return EventSubmission(
        kind="answer",
        actor="human",
        idempotency_key=f"answer-{node}-{option}",
        payload={"target": node, "answer": given},
    )


def _revise(node: str) -> EventSubmission:
    """The grill-master changing a decision: it lands where the decision is
    unanswered, and waits for the human's apply where it is answered."""
    return EventSubmission(
        kind="revise",
        actor="grill-master",
        idempotency_key=f"revise-{node}",
        payload={"target": node, "body": f"{node}, moved.", "why": "moved"},
    )


def _apply(log: SessionLog, node: str) -> EventSubmission:
    """The human applying the proposal waiting on this decision."""
    pending = next(one.id for one in replay(log.epoch, log.entries()).pending if one.target == node)
    return EventSubmission(
        kind="apply",
        actor="human",
        idempotency_key=f"apply-{node}",
        payload={"pending": [pending]},
    )


def _ruled_title(task: str) -> str:
    return f"Which d2, as ruled by {task}?"


@dataclass
class Ruler:
    """The expert seat: revises each decision its dispatch owed a ruling on,
    retitling it after the turn's first task so a test can tell which ruling
    landed.

    It lands through the real reply recorder on the channel its dispatch names,
    the way every seat does. `release` holds every call until the test sets it,
    and `failing` makes every call on that channel fail outright.
    """

    tier: str = HEAVY_TIER
    calls: list[DispatchContext] = field(default_factory=list)
    release: threading.Event = field(default_factory=threading.Event)
    failing: str | None = None

    def __post_init__(self) -> None:
        self.release.set()

    def run(self, log: SessionLog, dispatch: Path, /) -> int | None:
        context = DispatchContext.model_validate_json(dispatch.read_text(encoding="utf-8"))
        self.calls.append(context)
        assert self.release.wait(TIMEOUT), "a held call was never released"
        if context.channel == self.failing:
            raise AgentUnreachableError(self.tier, "it timed out")
        owed = [] if context.mootness is None else context.mootness.ids
        title = _ruled_title(context.tasks[0] if context.tasks else "nothing")
        reply = document(
            text="",
            updates=[
                {"kind": "revise", "target": one, "title": title, "why": "moved"} for one in owed
            ],
            rulings=[{"decision": one, "ruling": "revise", "why": "moved"} for one in owed],
        )
        with log.appending():
            return record_reply(
                log, self.tier, context.channel, reply, {}, context.mootness, context.tasks
            )


def _lane(log: SessionLog, ruler: Ruler) -> Lane:
    return Lane(log, SpyDriver(), ruler)


def _until(done: Callable[[], bool]) -> None:
    deadline = time.monotonic() + TIMEOUT
    while not done():
        assert time.monotonic() < deadline, "the background never got there"
        time.sleep(0.01)


def _join(turns: list[threading.Thread]) -> None:
    for turn in turns:
        turn.join(TIMEOUT)
        assert not turn.is_alive(), "a scheduled turn outlived its timeout"


def _items(entries: list[LogEntry]) -> list[tuple[LogEntry, dict[str, Any]]]:
    """Every task named on a status entry, with the entry naming it."""
    return [
        (entry, item)
        for entry in entries
        if entry.kind == STATUS_KIND
        for item in entry.payload.get("tasks") or []
    ]


def _pre_rulings(log: SessionLog) -> dict[tuple[str, str], str]:
    """The latest pre-ruling opened for each option of d1, by option and target."""
    return {
        (item["option"], item["target"]): item["id"]
        for _, item in _items(log.entries())
        if "option" in item and item["phase"] == STATUS_PHASE_COMPOSING
    }


def _settled_d0(log: SessionLog, ruler: Ruler) -> Lane:
    """The board with d0 settled and every pre-ruling it started landed."""
    _seed(log)
    lane = _lane(log, ruler)
    run_turns(lane, _answer("d0", "a"))
    _until(lambda: len(_pre_rulings(log)) == 2 and len(_closed(log, BACKGROUND)) == 2)
    return lane


def _closed(log: SessionLog, channel: str) -> list[LogEntry]:
    return [
        one
        for one in log.entries()
        if one.kind == STATUS_KIND
        and one.channel == channel
        and one.payload.get("phase") in (STATUS_PHASE_REPLIED, STATUS_PHASE_ERROR)
    ]


def _d2(log: SessionLog) -> Any:
    return next(one for one in replay(log.epoch, log.entries()).decisions if one.id == "d2")


def _tasks_started_by(log: SessionLog, gesture: int) -> list[tuple[LogEntry, dict[str, Any]]]:
    return [
        (entry, item)
        for entry, item in _items(log.entries())
        if item.get("gesture") == gesture and item["phase"] == STATUS_PHASE_COMPOSING
    ]


def _gesture(log: SessionLog, node: str) -> int:
    return next(
        one.seq
        for one in log.entries()
        if one.kind == "answer" and one.actor == "human" and one.payload.get("target") == node
    )


def _credited(log: SessionLog, task: str) -> bool:
    history = replay(log.epoch, log.entries()).history.get("d2", [])
    return any(one.task == task for one in history)


# --- what a pre-ruling holds ------------------------------------------------


def _hand_written(log: SessionLog, phase: str) -> None:
    """A pre-ruling on d2 for d1's option `b`, opened on the map channel by
    hand and left in this phase, as no lane would write it."""
    name = "impact-20-d2-d1-b"
    opened = log.emit_status(
        STATUS_PHASE_COMPOSING,
        "the 'heavy' tier is composing a reply",
        MAP_CHANNEL,
        tier=HEAVY_TIER,
        tasks=[
            {
                "id": name,
                "target": "d2",
                "gesture": 20,
                "basis": 20,
                "mode": "impact",
                "option": "b",
                "decision": "d1",
                "seat": HEAVY_TIER,
                "phase": STATUS_PHASE_COMPOSING,
            }
        ],
    )
    if phase != STATUS_PHASE_COMPOSING:
        log.emit_status(
            phase, "it ended", MAP_CHANNEL, tasks=[{"id": name, "phase": phase}], opened=opened.seq
        )


@pytest.mark.parametrize("phase", [STATUS_PHASE_COMPOSING, STATUS_PHASE_ERROR])
def test_a_pre_ruling_on_the_log_holds_nothing_live_or_failed(log: SessionLog, phase: str) -> None:
    """
    Given a pre-ruling task on d2 recorded on the log, still live or failed
    When the board is replayed and the human answers d2
    Then d2 is on the frontier with no waiting field, and the answer lands.
    """
    _seed(log)
    _hand_written(log, phase)

    image = replay(log.epoch, log.entries())
    assert "d2" in image.frontier
    assert _d2(log).waiting is None
    assert log.submit([_answer("d2", "a")], log.epoch)[0].status == "accepted"


# --- starting pre-rulings ---------------------------------------------------


def test_pnd_a6_settling_a_decision_pre_rules_each_option_of_what_it_opens_and_no_deeper(
    log: SessionLog,
) -> None:
    """
    Given d1 resting on d0 with two options marking d2, and d3 resting on d1
          with an option marking d4
    When the human settles d0
    Then one pre-ruling is recorded for each of d1's marking options on d2,
         each naming its option and decision, on the expert seat and on the
         background channel; none is recorded for d3, which d0 did not open;
         and d2 is unchanged while their results wait to be taken.
    """
    ruler = Ruler()
    _settled_d0(log, ruler)

    opened = [
        (entry, item)
        for entry, item in _items(log.entries())
        if "option" in item and item["phase"] == STATUS_PHASE_COMPOSING
    ]
    assert sorted((item["decision"], item["option"], item["target"]) for _, item in opened) == [
        ("d1", "b", "d2"),
        ("d1", "c", "d2"),
    ]
    for entry, item in opened:
        assert entry.channel == BACKGROUND
        assert item["mode"] == "impact"
        assert item["seat"] == HEAVY_TIER
        assert item["basis"] <= entry.seq
    assert len({item["id"] for _, item in opened}) == 2
    assert [one.channel for one in ruler.calls] == [BACKGROUND, BACKGROUND]
    assert _d2(log).title == "Which d2?"


def test_an_option_marking_its_own_decision_is_not_pre_ruled(log: SessionLog) -> None:
    """
    Given d1 resting on d0, with an option marking d1 itself
    When the human settles d0
    Then no pre-ruling is recorded: taking that option settles d1, which
         leaves the mark nothing standing to rule on.
    """
    for node, options, prereqs in (
        ("d0", PLAIN, []),
        ("d1", [PLAIN[0], {"id": "b", "text": "Itself", "puts_in_question": ["d1"]}], ["d0"]),
    ):
        _accepted(
            log,
            EventSubmission(
                kind="add-node",
                actor="grill-master",
                idempotency_key=f"seed-{node}",
                payload={
                    "target": node,
                    "short": node,
                    "title": f"Which {node}?",
                    "body": "Decide.",
                    "prereqs": prereqs,
                    "options": options,
                },
            ),
        )
    ruler = Ruler()

    run_turns(_lane(log, ruler), _answer("d0", "a"))

    assert _pre_rulings(log) == {}
    assert ruler.calls == []


def test_pnd_a6_two_options_marking_one_target_each_hold_a_live_pre_ruling_and_it_never_waits(
    log: SessionLog,
) -> None:
    """
    Given d1's options `b` and `c` both marking d2
    When d0 is settled and both pre-rulings are still running
    Then both are live at once, d2 carries no waiting field, and d2 stays on
         the frontier.
    """
    _seed(log)
    ruler = Ruler()
    ruler.release.clear()
    _, turns = _lane(log, ruler).accept([_answer("d0", "a")], log.epoch)
    _until(lambda: len(ruler.calls) == 2)

    assert len(_pre_rulings(log)) == 2
    assert _closed(log, BACKGROUND) == []
    assert _d2(log).waiting is None
    assert "d2" in replay(log.epoch, log.entries()).frontier

    ruler.release.set()
    _join(turns)


def test_a_pre_ruling_leaves_its_target_answerable_and_a_result_after_the_answer_changes_nothing(
    log: SessionLog,
) -> None:
    """
    Given both pre-rulings on d2 still running
    When the human answers d2, and only then do the results arrive
    Then the answer lands, d2 keeps the human's answer and its own title, no
         history line credits either pre-ruling, and taking d1's option `b`
         afterwards consumes nothing.
    """
    _seed(log)
    ruler = Ruler()
    ruler.release.clear()
    lane = _lane(log, ruler)
    _, turns = lane.accept([_answer("d0", "a")], log.epoch)
    _until(lambda: len(ruler.calls) == 2)

    receipts, answered = lane.accept([_answer("d2", "a")], log.epoch)
    assert receipts[0].status == "accepted"
    ruler.release.set()
    _join([*turns, *answered])
    _until(lambda: len(_closed(log, BACKGROUND)) == 2)

    assert _d2(log).status == "settled"
    assert _d2(log).title == "Which d2?"
    assert not any(_credited(log, one) for one in _pre_rulings(log).values())

    run_turns(lane, _answer("d1", "b"))
    assert _d2(log).title == "Which d2?"
    assert not any(_credited(log, one) for one in _pre_rulings(log).values())


def test_a_failed_pre_ruling_holds_nothing_and_the_click_starts_a_task(log: SessionLog) -> None:
    """
    Given both pre-rulings on d2 failed outright
    When the board is read, a retry is pressed on one, and the human takes
         d1's option `b`
    Then d2 is on the frontier and waiting on nothing, the retry starts
         nothing, and the click starts a task on d2 that d2 waits on.
    """
    ruler = Ruler(failing=BACKGROUND)
    lane = _settled_d0(log, ruler)

    assert {one.payload["phase"] for one in _closed(log, BACKGROUND)} == {STATUS_PHASE_ERROR}
    assert _d2(log).waiting is None
    assert "d2" in replay(log.epoch, log.entries()).frontier
    assert lane.retry(_pre_rulings(log)[("b", "d2")]) is None

    ruler.release.clear()
    _, turns = lane.accept([_answer("d1", "b")], log.epoch)
    started = _tasks_started_by(log, _gesture(log, "d1"))
    assert [item["target"] for _, item in started] == ["d2"]
    assert _d2(log).waiting is not None
    ruler.release.set()
    _join(turns)


# --- consuming one ----------------------------------------------------------


def test_pnd_a6_taking_a_pre_ruled_option_with_no_note_consumes_it(log: SessionLog) -> None:
    """
    Given both pre-rulings on d2 landed and cached
    When the human takes d1's option `b` with no note
    Then no task starts, d2 never waits and is on the frontier at once in the
         shape the `b` pre-ruling gave it, its history credits that pre-ruling
         by task, the expert is not called again, and the `c` pre-ruling's
         result never lands.
    """
    ruler = Ruler()
    lane = _settled_d0(log, ruler)
    taken = _pre_rulings(log)[("b", "d2")]
    other = _pre_rulings(log)[("c", "d2")]

    _, turns = lane.accept([_answer("d1", "b")], log.epoch)

    assert _tasks_started_by(log, _gesture(log, "d1")) == []
    assert _d2(log).waiting is None
    assert "d2" in replay(log.epoch, log.entries()).frontier
    assert _d2(log).title == _ruled_title(taken)
    assert _credited(log, taken)
    _join(turns)
    assert [one.channel for one in ruler.calls if one.channel == MAP_CHANNEL] == []
    assert not _credited(log, other)


def test_pnd_a6_an_answer_with_a_note_consumes_nothing(log: SessionLog) -> None:
    """
    Given both pre-rulings on d2 landed and cached
    When the human takes d1's option `b` with a note
    Then the pre-ruling is not consumed and a task starts on d2.
    """
    ruler = Ruler()
    lane = _settled_d0(log, ruler)
    ruler.release.clear()

    _, turns = lane.accept([_answer("d1", "b", note="but keep the old one")], log.epoch)

    assert "d2" in [item["target"] for _, item in _tasks_started_by(log, _gesture(log, "d1"))]
    assert not _credited(log, _pre_rulings(log)[("b", "d2")])
    ruler.release.set()
    _join(turns)


# Each step is built only when the one before it has landed, because an apply
# names the proposal the revise before it queued.
TOUCHES: dict[str, list[Callable[[SessionLog], EventSubmission]]] = {
    "its-target": [lambda _log: _revise("d2")],
    "the-decision-it-was-computed-for": [lambda _log: _revise("d1")],
    "an-ancestor-of-its-target": [lambda _log: _revise("d9"), lambda log: _apply(log, "d9")],
    "an-ancestor-of-its-decision": [lambda _log: _revise("d0"), lambda log: _apply(log, "d0")],
}


@pytest.mark.parametrize("touched", sorted(TOUCHES))
def test_pnd_a6_a_landed_change_after_its_basis_makes_a_pre_ruling_stale(
    log: SessionLog, touched: str
) -> None:
    """
    Given both pre-rulings on d2 landed and cached
    When a change lands on d2, on d1, or on an ancestor of either -- an agent's
         revise of an unanswered decision, or a human's apply of a proposal on
         an answered one -- and the human then takes d1's option `b`
    Then the pre-ruling is never consumed, and the click starts a task on d2.
    """
    ruler = Ruler()
    lane = _settled_d0(log, ruler)
    taken = _pre_rulings(log)[("b", "d2")]
    for step in TOUCHES[touched]:
        _accepted(log, step(log))

    ruler.release.clear()
    _, turns = lane.accept([_answer("d1", "b")], log.epoch)

    assert not _credited(log, taken)
    assert [item["target"] for _, item in _tasks_started_by(log, _gesture(log, "d1"))] == ["d2"]
    ruler.release.set()
    _join(turns)


def test_pnd_a6_a_proposal_merely_queued_leaves_a_pre_ruling_fresh(log: SessionLog) -> None:
    """
    Given both pre-rulings on d2 landed, and a revise of d9 -- an ancestor of
          d2, already answered -- waiting in the inbox
    When the human takes d1's option `b`
    Then the pre-ruling is consumed and no task starts.
    """
    ruler = Ruler()
    lane = _settled_d0(log, ruler)
    taken = _pre_rulings(log)[("b", "d2")]
    _accepted(log, _revise("d9"))
    assert any(one.target == "d9" for one in replay(log.epoch, log.entries()).pending)

    run_turns(lane, _answer("d1", "b"))

    assert _credited(log, taken)
    assert _tasks_started_by(log, _gesture(log, "d1")) == []


def test_pnd_a6_a_stale_pre_ruling_is_recomputed_and_the_fresh_one_is_consumed(
    log: SessionLog,
) -> None:
    """
    Given both pre-rulings on d2 landed, and then a revise of d1 lands
    When the human's next gesture is accepted elsewhere on the board
    Then both are weighed again over the moved board, with a later basis; and
         taking d1's option `b` consumes the fresh one, never the stale one.
    """
    ruler = Ruler()
    lane = _settled_d0(log, ruler)
    stale = _pre_rulings(log)[("b", "d2")]
    moved = _accepted(log, _revise("d1"))

    run_turns(lane, _answer("d5", "a"))
    _until(lambda: len(_closed(log, BACKGROUND)) == 4)

    fresh = _pre_rulings(log)
    assert fresh[("b", "d2")] != stale
    recomputed = [
        item
        for _, item in _items(log.entries())
        if item["id"] in fresh.values() and item["phase"] == STATUS_PHASE_COMPOSING
    ]
    assert len(recomputed) == 2
    assert all(item["basis"] > moved for item in recomputed)

    run_turns(lane, _answer("d1", "b"))

    assert _credited(log, fresh[("b", "d2")])
    assert not _credited(log, stale)


@pytest.mark.parametrize("order", ["mutation-first", "answer-first"])
def test_pnd_a6_a_mutation_in_the_consuming_batch_lands_before_or_after_the_consume(
    log: SessionLog, order: str
) -> None:
    """
    Given both pre-rulings on d2 landed, and a revise of d9 -- an ancestor of
          d2 -- waiting in the inbox
    When one batch carries the human's apply of that revise and their answer
         taking d1's option `b`
    Then with the apply first, it lands before the staleness check and the
         pre-ruling is not consumed; with the answer first, the consume lands
         on the entry straight after the answer and the apply after it.
    """
    ruler = Ruler()
    lane = _settled_d0(log, ruler)
    taken = _pre_rulings(log)[("b", "d2")]
    _accepted(log, _revise("d9"))
    applied, answered = _apply(log, "d9"), _answer("d1", "b")
    batch = [applied, answered] if order == "mutation-first" else [answered, applied]

    run_turns(lane, *batch)

    entries = log.entries()
    answer = _gesture(log, "d1")
    apply = next(one.seq for one in entries if one.kind == "apply")
    consumed = [
        one.seq
        for one in entries
        if one.actor == "grill-master"
        and one.channel == MAP_CHANNEL
        and any(item.get("id") == taken for item in one.payload.get("tasks") or [])
    ]
    if order == "mutation-first":
        assert apply < answer
        assert consumed == []
        assert not _credited(log, taken)
    else:
        assert consumed == [answer + 1]
        assert apply > answer + 1
        assert _credited(log, taken)


# --- the background channel -------------------------------------------------


def _map_pairing(entries: list[LogEntry]) -> tuple[int, int]:
    """How many turns the map channel announced, and how many it closed."""
    statuses = [one for one in entries if one.kind == STATUS_KIND and one.channel == MAP_CHANNEL]
    announced = [
        one
        for one in statuses
        if one.payload.get("phase") == STATUS_PHASE_COMPOSING and not one.payload.get("pressed")
    ]
    closing = [
        one
        for one in statuses
        if one.payload.get("phase") in (STATUS_PHASE_REPLIED, STATUS_PHASE_ERROR)
    ]
    return len(announced), len(closing)


def test_pnd_a14_pre_rulings_announce_and_close_on_their_own_channel(log: SessionLog) -> None:
    """
    Given d0 settled and both pre-rulings it started still running
    When the map channel is read, and again once they have closed
    Then the map channel carries no announcement naming a pre-ruling and no
         turn left open, each pre-ruling is announced on the background channel
         and closed there by an entry naming its own announcement, and the map
         channel's announcements and closings pair one to one throughout.
    """
    _seed(log)
    ruler = Ruler()
    ruler.release.clear()
    _, turns = _lane(log, ruler).accept([_answer("d0", "a")], log.epoch)
    _until(lambda: len(ruler.calls) == 2)
    _until(lambda: _map_pairing(log.entries()) == (1, 1))

    on_map = [entry for entry, item in _items(log.entries()) if "option" in item]
    assert all(entry.channel == BACKGROUND for entry in on_map)
    assert [one for one in open_announcements(log.entries()) if one.channel == MAP_CHANNEL] == []

    ruler.release.set()
    _join(turns)
    _until(lambda: len(_closed(log, BACKGROUND)) == 2)

    announced = {
        entry.seq
        for entry, item in _items(log.entries())
        if "option" in item and item["phase"] == STATUS_PHASE_COMPOSING
    }
    assert {one.payload["opened"] for one in _closed(log, BACKGROUND)} == announced
    assert _map_pairing(log.entries()) == (1, 1)
    assert open_announcements(log.entries()) == []


def test_pnd_a14_a_restart_closes_the_background_turn_and_leaves_the_map_alone(
    session_dir: Path, log: SessionLog
) -> None:
    """
    Given both pre-rulings running when their process dies
    When a fresh backend opens the same directory
    Then it closes each on the background channel with an entry naming its
         announcement, writes nothing on the map channel, and leaves d2 on the
         frontier with no waiting field.
    """
    _seed(log)
    ruler = Ruler()
    ruler.release.clear()
    _, turns = _lane(log, ruler).accept([_answer("d0", "a")], log.epoch)
    _until(lambda: len(ruler.calls) == 2)
    _until(lambda: _map_pairing(log.entries()) == (1, 1))
    announced = {
        entry.seq
        for entry, item in _items(log.entries())
        if "option" in item and item["phase"] == STATUS_PHASE_COMPOSING
    }

    successor = open_session(session_dir)

    written = [one for one in successor.entries() if one.epoch == successor.epoch]
    closings = [one for one in written if one.kind == STATUS_KIND]
    assert {one.channel for one in closings} == {BACKGROUND}
    assert {one.payload["opened"] for one in closings} == announced
    assert _map_pairing(successor.entries()) == (1, 1)
    image = replay(successor.epoch, successor.entries())
    assert "d2" in image.frontier
    assert next(one for one in image.decisions if one.id == "d2").waiting is None

    ruler.release.set()
    _join(turns)


def test_pnd_a14_the_task_a_missing_pre_ruling_leaves_runs_on_the_map_channel(
    log: SessionLog,
) -> None:
    """
    Given the pre-rulings on d2 still running, so none has a result to take
    When the human takes d1's option `b`
    Then a task on d2 opens on the map channel's own announcement, seated on
         the expert, and d2 waits on it.
    """
    _seed(log)
    ruler = Ruler()
    ruler.release.clear()
    lane = _lane(log, ruler)
    _, first = lane.accept([_answer("d0", "a")], log.epoch)
    _until(lambda: len(ruler.calls) == 2)

    _, second = lane.accept([_answer("d1", "b")], log.epoch)

    started = _tasks_started_by(log, _gesture(log, "d1"))
    assert [(entry.channel, item["target"]) for entry, item in started] == [(MAP_CHANNEL, "d2")]
    assert started[0][0].payload["tier"] == HEAVY_TIER
    assert _d2(log).waiting is not None
    ruler.release.set()
    _join([*first, *second])


def test_pnd_a14_the_expert_takes_a_pre_ruling_cold_and_its_result_lands_on_its_own_channel(
    log: SessionLog,
) -> None:
    """
    Given a pre-ruling's dispatch, and a chain the background channel already
          holds from an earlier pre-ruling
    When the expert seat takes it
    Then it opens a fresh chain rather than resuming that one, its prompt says
         the human has not taken the option yet, and its result lands as the
         grill-master's on the background channel without changing d2.
    """
    _seed(log)
    write_resume(log.directory, BACKGROUND, "earlier-pre-ruling", resume_file(HEAVY_TIER))
    name = "impact-20-d2-d1-b"
    log.emit_status(
        STATUS_PHASE_COMPOSING,
        "the 'heavy' tier is composing a reply",
        BACKGROUND,
        tier=HEAVY_TIER,
        tasks=[
            {
                "id": name,
                "target": "d2",
                "gesture": 20,
                "basis": 20,
                "mode": "impact",
                "option": "b",
                "decision": "d1",
                "seat": HEAVY_TIER,
                "phase": STATUS_PHASE_COMPOSING,
            }
        ],
    )
    cli = ScriptedCli(
        reply=document(
            text="",
            updates=[{"kind": "revise", "target": "d2", "title": "Moved", "why": "moved"}],
            rulings=[{"decision": "d2", "ruling": "revise", "why": "moved"}],
        )
    )
    dispatch = record_dispatch(
        log,
        channel=BACKGROUND,
        mootness=MootnessObligation(target="d1", answer=MARKS["text"], ids=["d2"]),
        tasks=(name,),
        option="b",
    )

    spoke = HeavyDriver(TierConfig.from_env({}), cli).run(log, dispatch)

    assert "--resume" not in cli.calls[0]
    assert any("has not taken" in one for one in cli.calls[0])
    landed = next(one for one in log.entries() if one.seq == spoke)
    assert (landed.actor, landed.channel) == ("grill-master", BACKGROUND)
    assert _d2(log).title == "Which d2?"
