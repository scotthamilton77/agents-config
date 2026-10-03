"""The impact task on the log, and the frontier as the lock.

A marked answer sends the expert to rule on the decisions it puts in question.
For as long as that ruling is in flight those decisions are waiting: off the
frontier, named on the board with the task weighing them, and never answerable
on structure the ruling is about to move. Everything here is read off the log
and the replay, because a restarted backend has nothing else to read.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from conftest import TIMEOUT, SpyDriver

from grillui.drivers import record_document
from grillui.lane import Lane, open_announcements, unclosed_turns
from grillui.projector import replay
from grillui.schemas import (
    HEAVY_TIER,
    MAP_CHANNEL,
    REASON_DECISION_WAITING,
    STATUS_KIND,
    DispatchContext,
    EventSubmission,
    GrillMasterDocument,
    LogEntry,
    Ruling,
    Stop,
)
from grillui.session import open_session

if TYPE_CHECKING:
    from pathlib import Path

    from grillui.log import SessionLog

MARKS_TWO = {"id": "b", "text": "Close it unactioned", "puts_in_question": ["d2", "d3"]}
MARKS_ONE = {"id": "b", "text": "Rebuild it", "puts_in_question": ["d2"]}
PLAIN = [{"id": "a", "text": "Yes"}, {"id": "c", "text": "No"}]


def _seed(log: SessionLog, *extra: tuple[str, list[dict[str, Any]]]) -> None:
    """d1 marks d2 and d3; d4 marks d2 alone; d5 rests on nothing and is marked
    by nobody, so it is the decision no ruling in flight is about."""
    nodes = [
        ("d1", [*PLAIN, MARKS_TWO]),
        ("d2", PLAIN),
        ("d3", PLAIN),
        ("d4", [*PLAIN, MARKS_ONE]),
        ("d5", PLAIN),
        *extra,
    ]
    for node, options in nodes:
        receipt = log.submit(
            [
                EventSubmission(
                    kind="add-node",
                    actor="grill-master",
                    idempotency_key=f"seed-{node}",
                    payload={
                        "target": node,
                        "short": node,
                        "title": f"Which {node}?",
                        "body": "Decide.",
                        "prereqs": [],
                        "options": options,
                    },
                )
            ],
            log.epoch,
        )[0]
        assert receipt.status == "accepted"


def _answer(node: str, option: str = "b") -> EventSubmission:
    return EventSubmission(
        kind="answer",
        actor="human",
        idempotency_key=f"answer-{node}-{option}",
        payload={"target": node, "answer": {"option": option}},
    )


def _gesture(log: SessionLog, node: str) -> int:
    """The sequence the human's answer on this decision landed at."""
    return next(
        one.seq
        for one in log.entries()
        if one.kind == "answer" and one.payload.get("target") == node
    )


def _task_items(entries: list[LogEntry]) -> list[tuple[LogEntry, dict[str, Any]]]:
    """Every task named on a status entry, with the entry naming it."""
    return [
        (entry, item)
        for entry in entries
        if entry.kind == STATUS_KIND
        for item in entry.payload.get("tasks") or []
    ]


def _waiting(log: SessionLog) -> dict[str, dict[str, Any]]:
    image = replay(log.epoch, log.entries())
    return {node.id: node.model_dump()["waiting"] for node in image.decisions if node.waiting}


def _live_by_target(entries: list[LogEntry]) -> dict[str, list[str]]:
    """Which gesture-started tasks the log holds live at its end, by target."""
    live: dict[str, str] = {}
    targets: dict[str, str] = {}
    for _, item in _task_items(entries):
        if "target" in item:
            targets[item["id"]] = item["target"]
        live[item["id"]] = item["phase"]
    found: dict[str, list[str]] = {}
    for task, phase in live.items():
        if phase == "composing":
            found.setdefault(targets[task], []).append(task)
    return found


@dataclass
class HeldRuler:
    """An expert seat whose every call waits to be released, then rules
    `invalidate` on each decision its dispatch owed and queues the update that
    ruling is credited by.

    It lands through the real map-document recorder under the append lock, the
    way every seat does, so whatever the recorder does with a result that
    arrives for a superseded task is what this seat's turn meets.
    """

    tier: str = HEAVY_TIER
    started: list[threading.Event] = field(
        default_factory=lambda: [threading.Event() for _ in range(4)]
    )
    release: list[threading.Event] = field(
        default_factory=lambda: [threading.Event() for _ in range(4)]
    )
    calls: int = 0
    silent_on: frozenset[str] = frozenset()
    _taking: threading.Lock = field(default_factory=threading.Lock)

    def run(self, log: SessionLog, dispatch: Path, /) -> int | None:
        owed = DispatchContext.model_validate_json(dispatch.read_text(encoding="utf-8")).mootness
        with self._taking:
            mine = self.calls
            self.calls += 1
        self.started[mine].set()
        assert self.release[mine].wait(TIMEOUT), f"call {mine} was never released"
        ids = [] if owed is None else [one for one in owed.ids if one not in self.silent_on]
        document = GrillMasterDocument(
            text="",
            updates=[{"kind": "invalidate", "target": one, "why": "moved"} for one in ids],
            supersedes=[],
            rulings=[Ruling(decision=one, ruling="invalidate", why="moved") for one in ids],
            stop=Stop(met=False),
        )
        with log.appending():
            return record_document(log, self.tier, document, {}, owed)


def _join(turns: list[threading.Thread]) -> None:
    for turn in turns:
        turn.join(TIMEOUT)
        assert not turn.is_alive(), "a scheduled turn outlived its timeout"


# --- the task on the log, and the decision it holds -------------------------


def test_pnd_a1_a_marked_answer_records_a_task_per_target_and_each_target_waits(
    log: SessionLog,
) -> None:
    """
    Given a board whose d1 option marks d2 and d3, and a d5 nobody marked
    When the human takes that option and the ruling is still in flight
    Then the turn's opening status entry carries one impact task per target,
         each with its basis at the gesture's own sequence and the seat taking
         it; image 1 lists d2 and d3 as waiting with that gesture, seat and
         start; the frontier excludes them and still offers d5; and once the
         turn closes, both are back on the frontier.
    """
    _seed(log)
    seat = SpyDriver(tier=HEAVY_TIER, hold=True)
    lane = Lane(log, seat)

    _, turns = lane.accept([_answer("d1")], log.epoch)
    assert seat.started.wait(TIMEOUT)
    gesture = _gesture(log, "d1")

    opened = [
        (entry, item) for entry, item in _task_items(log.entries()) if item["phase"] == "composing"
    ]
    assert [item["target"] for _, item in opened] == ["d2", "d3"]
    for entry, item in opened:
        assert entry.payload["phase"] == "composing"
        assert entry.channel == MAP_CHANNEL
        assert item["gesture"] == gesture
        assert item["basis"] == gesture
        assert item["mode"] == "impact"
        assert item["seat"] == HEAVY_TIER
    start = opened[0][0].timestamp

    waiting = _waiting(log)
    assert set(waiting) == {"d2", "d3"}
    assert waiting["d2"] == {
        "task": opened[0][1]["id"],
        "gesture": gesture,
        "seat": HEAVY_TIER,
        "start": start,
    }
    frontier = replay(log.epoch, log.entries()).frontier
    assert "d2" not in frontier
    assert "d3" not in frontier
    assert "d5" in frontier

    seat.release.set()
    _join(turns)

    assert _waiting(log) == {}
    frontier = replay(log.epoch, log.entries()).frontier
    assert {"d2", "d3", "d5"} <= set(frontier)


def test_pnd_a1_an_option_with_no_mark_records_no_task(log: SessionLog) -> None:
    """
    Given the same board
    When the human takes d1's unmarked option
    Then no task is recorded anywhere and every other decision stays on the
         frontier while the turn runs.
    """
    _seed(log)
    seat = SpyDriver(tier=HEAVY_TIER, hold=True)
    lane = Lane(log, seat)

    _, turns = lane.accept([_answer("d1", "a")], log.epoch)
    assert seat.started.wait(TIMEOUT)

    assert _task_items(log.entries()) == []
    assert _waiting(log) == {}
    assert {"d2", "d3", "d4", "d5"} <= set(replay(log.epoch, log.entries()).frontier)
    seat.release.set()
    _join(turns)


def test_pnd_a1_a_mark_naming_a_dead_or_absent_decision_records_nothing(
    log: SessionLog,
) -> None:
    """
    Given an option whose mark names one decision the human has invalidated and
         one the board never held
    When the human takes it
    Then no task is recorded and nothing is waiting.
    """
    _seed(
        log,
        (
            "d6",
            [*PLAIN, {"id": "b", "text": "Drop both", "puts_in_question": ["d5", "ghost"]}],
        ),
    )
    killed = log.submit(
        [
            EventSubmission(
                kind="invalidate",
                actor="human",
                idempotency_key="kill-d5",
                payload={"target": "d5", "why": "out of scope"},
            )
        ],
        log.epoch,
    )[0]
    assert killed.status == "accepted"
    seat = SpyDriver(tier=HEAVY_TIER, hold=True)
    lane = Lane(log, seat)

    _, turns = lane.accept([_answer("d6")], log.epoch)
    assert seat.started.wait(TIMEOUT)

    assert _task_items(log.entries()) == []
    assert _waiting(log) == {}
    seat.release.set()
    _join(turns)


def test_pnd_a1_a_restart_keeps_the_waiting_field_and_fails_the_dead_task(
    session_dir: Path, log: SessionLog
) -> None:
    """
    Given a marked answer whose ruling is in flight when its process dies
    When a fresh backend opens the same directory
    Then image 1 shows the same waiting field it showed before, and the task
         is closed on the log as failed rather than left live.
    """
    _seed(log)
    seat = SpyDriver(tier=HEAVY_TIER, hold=True)
    _, turns = Lane(log, seat).accept([_answer("d1")], log.epoch)
    assert seat.started.wait(TIMEOUT)
    before = _waiting(log)
    assert set(before) == {"d2", "d3"}

    successor = open_session(session_dir)

    after = {
        node.id: node.model_dump()["waiting"]
        for node in replay(successor.epoch, successor.entries()).decisions
        if node.waiting
    }
    assert after == before
    assert _live_by_target(successor.entries()) == {}
    failed = [
        item["id"]
        for entry, item in _task_items(successor.entries())
        if entry.epoch == successor.epoch
    ]
    phases = {
        item["id"]: item["phase"]
        for entry, item in _task_items(successor.entries())
        if entry.epoch == successor.epoch
    }
    assert sorted(failed) == sorted(one["task"] for one in before.values())
    assert set(phases.values()) == {"error"}

    seat.release.set()
    _join(turns)


# --- supersession -----------------------------------------------------------


def test_pnd_a3_a_second_gesture_supersedes_the_live_task_and_its_result_is_dropped(
    log: SessionLog,
) -> None:
    """
    Given d1's marked answer in flight with tasks on d2 and d3
    When the human answers d4, whose option also marks d2, and only then does
         d1's ruling arrive, ruling on both d2 and d3
    Then d1's task on d2 is superseded by a task over the new upstream state;
         d1's result for d2 is dropped with a history line naming its task and
         never queued, while its ruling on d3 is queued as usual; and at no
         sequence of the log do two live tasks share a target.
    """
    _seed(log)
    seat = HeldRuler()
    lane = Lane(log, seat)

    _, first = lane.accept([_answer("d1")], log.epoch)
    assert seat.started[0].wait(TIMEOUT)
    _, second = lane.accept([_answer("d4")], log.epoch)
    assert seat.started[1].wait(TIMEOUT)
    stale = f"impact-{_gesture(log, 'd1')}-d2"
    fresh = f"impact-{_gesture(log, 'd4')}-d2"

    assert _waiting(log)["d2"]["task"] == fresh

    seat.release[0].set()
    _join(first)

    image = replay(log.epoch, log.entries())
    queued = {(one.kind, one.target) for one in image.pending}
    assert ("invalidate", "d3") in queued
    assert ("invalidate", "d2") not in queued, "a superseded task's result was folded"
    assert any(stale in one.why for one in image.history.get("d2", [])), image.history.get("d2")
    assert _waiting(log)["d2"]["task"] == fresh
    assert "d3" not in _waiting(log)

    seat.release[1].set()
    _join(second)

    queued = {(one.kind, one.target) for one in replay(log.epoch, log.entries()).pending}
    assert ("invalidate", "d2") in queued
    entries = log.entries()
    for end in range(1, len(entries) + 1):
        shared = {
            target: tasks
            for target, tasks in _live_by_target(entries[:end]).items()
            if len(tasks) > 1
        }
        assert not shared, f"two live tasks share a target at seq {entries[end - 1].seq}"


def test_pnd_a3_two_gestures_in_one_batch_leave_one_live_task_per_target(
    log: SessionLog,
) -> None:
    """
    Given the same board
    When one batch carries the human's answers to d1 and to d4, both marking d2
    Then once the batch is accepted exactly one live task targets d2, and it is
         the later gesture's.
    """
    _seed(log)
    seat = HeldRuler()
    lane = Lane(log, seat)

    _, turns = lane.accept([_answer("d1"), _answer("d4")], log.epoch)

    live = _live_by_target(log.entries())
    assert live["d2"] == [f"impact-{_gesture(log, 'd4')}-d2"]
    assert live["d3"] == [f"impact-{_gesture(log, 'd1')}-d3"]
    for one in seat.release:
        one.set()
    _join(turns)


# --- how a superseded task ends ---------------------------------------------


def test_pnd_a15_a_superseded_task_is_closed_by_the_superseding_accepted_entry(
    log: SessionLog,
) -> None:
    """
    Given d1's task on d2 superseded by d4's answer while d1's turn runs
    When both turns run to their replies
    Then the superseding gesture's `accepted` entry names the superseded task
         as superseded, no later entry names it in any other phase, and the map
         channel still pairs one `composing` with one closing entry per turn.
         Inverse: d1's task on d3, which ran to its own reply, is closed by its
         turn's `replied` entry and named by no `accepted` entry.
    """
    _seed(log)
    seat = HeldRuler()
    lane = Lane(log, seat)

    _, first = lane.accept([_answer("d1")], log.epoch)
    assert seat.started[0].wait(TIMEOUT)
    _, second = lane.accept([_answer("d4")], log.epoch)
    assert seat.started[1].wait(TIMEOUT)
    seat.release[0].set()
    _join(first)
    seat.release[1].set()
    _join(second)

    stale = f"impact-{_gesture(log, 'd1')}-d2"
    ran = f"impact-{_gesture(log, 'd1')}-d3"
    named = [(entry, item) for entry, item in _task_items(log.entries()) if item["id"] == stale]
    closers = [(entry, item) for entry, item in named if item["phase"] != "composing"]
    assert closers, named
    first, how = closers[0]
    assert first.payload["phase"] == "accepted"
    assert how["phase"] == "superseded"
    assert {item["phase"] for _, item in closers} == {"superseded"}, closers

    ran_closers = [
        (entry.payload["phase"], item["phase"])
        for entry, item in _task_items(log.entries())
        if item["id"] == ran and item["phase"] != "composing"
    ]
    assert ran_closers == [("replied", "replied")]

    lane_phases = [
        entry.payload["phase"]
        for entry in log.entries()
        if entry.kind == STATUS_KIND and entry.channel == MAP_CHANNEL
    ]
    assert lane_phases.count("composing") == 2
    assert lane_phases.count("replied") + lane_phases.count("error") == 2


def test_pnd_a15_a_restart_after_a_supersession_shows_the_task_superseded(
    session_dir: Path, log: SessionLog
) -> None:
    """
    Given d1's task on d2 superseded by d4's answer, with both turns still in
         flight when their process dies
    When a fresh backend opens the same directory
    Then the tasks that were live are closed as failed, and the superseded one
         is named by no failure: it stays superseded.
    """
    _seed(log)
    seat = HeldRuler()
    lane = Lane(log, seat)
    _, first = lane.accept([_answer("d1")], log.epoch)
    assert seat.started[0].wait(TIMEOUT)
    _, second = lane.accept([_answer("d4")], log.epoch)
    assert seat.started[1].wait(TIMEOUT)
    stale = f"impact-{_gesture(log, 'd1')}-d2"

    successor = open_session(session_dir)

    restarted = {
        item["id"]: item["phase"]
        for entry, item in _task_items(successor.entries())
        if entry.epoch == successor.epoch
    }
    assert stale not in restarted
    assert restarted == {
        f"impact-{_gesture(log, 'd1')}-d3": "error",
        f"impact-{_gesture(log, 'd4')}-d2": "error",
    }
    assert _live_by_target(successor.entries()) == {}

    for one in seat.release:
        one.set()
    _join([*first, *second])


# --- two map turns at once, and what closes each ------------------------------


def _map_lane(entries: list[LogEntry]) -> list[LogEntry]:
    return [one for one in entries if one.kind == STATUS_KIND and one.channel == MAP_CHANNEL]


def test_pnd_a15_a_restart_closes_each_overlapping_map_turn_with_its_own_entry(
    session_dir: Path, log: SessionLog
) -> None:
    """
    Given two marked answers whose map turns are both in flight when their
         process dies, the second announced before the first replied
    When a fresh backend opens the same directory
    Then the map carries exactly one closing entry per announced turn, each
         dead task is named by the closing entry of the turn that opened it, and
         no closing entry names tasks from both turns.
    """
    _seed(log)
    seat = HeldRuler()
    lane = Lane(log, seat)
    _, first = lane.accept([_answer("d1")], log.epoch)
    assert seat.started[0].wait(TIMEOUT)
    _, second = lane.accept([_answer("d4")], log.epoch)
    assert seat.started[1].wait(TIMEOUT)
    owned = {
        "d1": {f"impact-{_gesture(log, 'd1')}-d3"},
        "d4": {f"impact-{_gesture(log, 'd4')}-d2"},
    }

    successor = open_session(session_dir)

    lane_entries = _map_lane(successor.entries())
    opened = [one for one in lane_entries if one.payload["phase"] == "composing"]
    closed = [one for one in lane_entries if one.payload["phase"] in {"replied", "error"}]
    assert len(opened) == 2
    assert len(closed) == 2, [one.payload for one in closed]
    named = [{item["id"] for item in one.payload.get("tasks") or []} for one in closed]
    assert sorted(map(sorted, named)) == sorted(map(sorted, owned.values())), named
    # Each closing entry names the announcement it closes, and that is the
    # announcement which opened the very tasks it fails.
    announced = {one.seq: {item["id"] for item in one.payload.get("tasks") or []} for one in opened}
    assert {one.payload.get("opened") for one in closed} == set(announced), [
        one.payload for one in closed
    ]
    for one in closed:
        failed = {item["id"] for item in one.payload.get("tasks") or []}
        assert failed <= announced[one.payload["opened"]], one.payload

    for one in seat.release:
        one.set()
    _join([*first, *second])


def test_one_of_two_overlapping_map_turns_closing_leaves_the_other_unclosed(
    log: SessionLog,
) -> None:
    """
    Given two marked answers whose map turns are both in flight
    When the first of them replies while the second is still running
    Then the map still reads as owing a turn, and stops only once the second
         closes too.

    A channel read as quiet while a turn on it is still running is a channel a
    restart would leave unclosed, and a reader asking whether a reply is still
    outstanding would be told no.
    """
    _seed(log)
    seat = HeldRuler()
    lane = Lane(log, seat)
    _, first = lane.accept([_answer("d1")], log.epoch)
    assert seat.started[0].wait(TIMEOUT)
    _, second = lane.accept([_answer("d4")], log.epoch)
    assert seat.started[1].wait(TIMEOUT)

    seat.release[0].set()
    _join(first)
    assert MAP_CHANNEL in unclosed_turns(log.entries())

    seat.release[1].set()
    _join(second)
    assert unclosed_turns(log.entries()) == {}


# --- the gate holds the lock, not only the page -------------------------------


def _submit(log: SessionLog, event: EventSubmission) -> Any:
    return log.submit([event], log.epoch)[0]


def _settled(log: SessionLog, node: str) -> bool:
    found = next(one for one in replay(log.epoch, log.entries()).decisions if one.id == node)
    return found.status == "settled"


def test_pnd_a1_an_answer_to_a_waiting_decision_is_refused_and_settles_nothing(
    session_dir: Path, log: SessionLog
) -> None:
    """
    Given d2 waiting on the ruling d1's marked answer started
    When a client that has not redrawn answers d2 anyway, opens a thread on it,
         and answers d4, whose option also marks d2
    Then the answer to d2 is refused by name and settles nothing, the thread and
         the superseding answer are accepted, and after a restart that fails
         the task, an answer to d2 is still refused.
    """
    _seed(log)
    seat = SpyDriver(tier=HEAVY_TIER, hold=True)
    lane = Lane(log, seat)
    _, turns = lane.accept([_answer("d1")], log.epoch)
    assert seat.started.wait(TIMEOUT)

    refused = _submit(log, _answer("d2", "a"))
    assert refused.status == "rejected"
    assert refused.reason == REASON_DECISION_WAITING
    assert "d2" in refused.detail
    assert not _settled(log, "d2")

    opened = _submit(
        log,
        EventSubmission(
            kind="thread-created",
            actor="human",
            channel="t-d2",
            idempotency_key="discuss-d2",
            payload={"decision": "d2", "turns": [{"who": "human", "text": "Why wait?"}]},
        ),
    )
    assert opened.status == "accepted"
    assert _submit(log, _answer("d4")).status == "accepted"

    successor = open_session(session_dir)
    again = successor.submit(
        [
            EventSubmission(
                kind="answer",
                actor="human",
                idempotency_key="after-restart",
                payload={"target": "d2", "answer": {"option": "a"}},
            )
        ],
        successor.epoch,
    )[0]
    assert again.status == "rejected"
    assert again.reason == REASON_DECISION_WAITING

    seat.release.set()
    _join(turns)


def test_pnd_a3_a_drop_is_recorded_only_for_a_target_the_result_spoke_to(
    log: SessionLog,
) -> None:
    """
    Given d1's marked answer in flight with tasks on d2 and d3, and d4's answer
         superseding the task on d2
    When d1's turn then arrives ruling on d3 alone
    Then no dropped-result line is recorded on d2, because nothing for d2 arrived
         to be dropped; d3's ruling lands as usual.
    """
    _seed(log)
    seat = HeldRuler(silent_on=frozenset({"d2"}))
    lane = Lane(log, seat)
    _, first = lane.accept([_answer("d1")], log.epoch)
    assert seat.started[0].wait(TIMEOUT)
    _, second = lane.accept([_answer("d4")], log.epoch)
    assert seat.started[1].wait(TIMEOUT)
    stale = f"impact-{_gesture(log, 'd1')}-d2"

    seat.release[0].set()
    _join(first)

    image = replay(log.epoch, log.entries())
    assert not any(stale in one.why for one in image.history.get("d2", [])), image.history["d2"]
    assert not [
        entry
        for entry, item in _task_items(log.entries())
        if item["id"] == stale and entry.payload["phase"] == "rulings-dropped"
    ]
    assert ("invalidate", "d3") in {(one.kind, one.target) for one in image.pending}

    seat.release[1].set()
    _join(second)


def test_a_closing_entry_closes_no_announcement_on_another_channel(log: SessionLog) -> None:
    """
    Given a turn announced on the map
    When a closing entry on a thread names that announcement's sequence
    Then the map's turn is still open: a closing entry only ever closes a turn
         on its own channel.
    """
    announced = log.emit_status("composing", "the 'heavy' tier is composing a reply", tier="heavy")
    log.emit_status("replied", "the turn is over", "t-elsewhere", opened=announced.seq)

    assert [one.seq for one in open_announcements(log.entries())] == [announced.seq]
