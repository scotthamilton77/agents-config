"""A failed ruling holds its decision as a named blocker, and a retry scoped to
that decision's subtree is how it is released.

A marked answer sends the expert to rule on the decisions it puts in question.
When that ruling errors, times out or is refused, the decision stays waiting
with the failure named on it, and nothing unlocks on inaction. The human's
retry asks for the same ruling again over the board as it now stands, and its
result lands exactly as the first run's would have -- except that it may not
reach outside the failed decision and what rests on it.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from conftest import TIMEOUT, SpyDriver, document, driven, run_turns

from grillui.drivers import HeavyDriver, ReplyRefusedError, read_document, record_document
from grillui.lane import AgentUnreachableError, Lane
from grillui.projector import impact_tasks, replay, to_image1
from grillui.schemas import (
    HEAVY_TIER,
    MAP_CHANNEL,
    REASON_DECISION_WAITING,
    STATUS_KIND,
    STATUS_PHASE_ACCEPTED,
    STATUS_PHASE_COMPOSING,
    STATUS_PHASE_ERROR,
    STATUS_PHASE_SUPERSEDED,
    DispatchContext,
    EventSubmission,
    MootnessObligation,
)
from grillui.session import open_session
from grillui.tiers import TierConfig

if TYPE_CHECKING:
    from pathlib import Path

    from grillui.log import SessionLog

MARKS_D2 = {"id": "b", "text": "Rebuild it", "puts_in_question": ["d2"]}
PLAIN = [{"id": "a", "text": "Yes"}, {"id": "c", "text": "No"}]
RETITLED = "Which d2, now that it is rebuilt?"


def _seed(log: SessionLog) -> None:
    """d1 and d4 each mark d2; d3 rests on d2, so it is in d2's subtree; d5
    rests on nothing and is outside it."""
    for node, options, prereqs in (
        ("d1", [PLAIN[0], MARKS_D2], []),
        ("d2", PLAIN, []),
        ("d3", PLAIN, ["d2"]),
        ("d4", [PLAIN[0], MARKS_D2], []),
        ("d5", PLAIN, []),
    ):
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
                        "prereqs": prereqs,
                        "options": options,
                    },
                )
            ],
            log.epoch,
        )[0]
        assert receipt.status == "accepted"


def _answer(node: str, option: str = "b", key: str | None = None) -> EventSubmission:
    return EventSubmission(
        kind="answer",
        actor="human",
        idempotency_key=key or f"answer-{node}-{option}",
        payload={"target": node, "answer": {"option": option}},
    )


@dataclass
class SequenceCli:
    """A `claude` CLI answering each call with the next scripted outcome.

    An outcome is a reply, or an exception the transport raises in its place.
    `hold` keeps a call open until the test releases it, so a retry can be
    caught in flight.
    """

    outcomes: list[str | Exception]
    calls: list[list[str]] = field(default_factory=list)
    hold: threading.Event | None = None
    started: threading.Event = field(default_factory=threading.Event)

    def __call__(self, argv: list[str], _directory: Path, /) -> str:
        self.calls.append(list(argv))
        self.started.set()
        if self.hold is not None:
            self.hold.wait(TIMEOUT)
        outcome = self.outcomes[min(len(self.calls), len(self.outcomes)) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return json.dumps({"session_id": "chain-1", "result": outcome})


TIMED_OUT = AgentUnreachableError(HEAVY_TIER, "it timed out")


def _lane(log: SessionLog, cli: SequenceCli) -> Lane:
    return Lane(log, SpyDriver(), HeavyDriver(TierConfig.from_env({}), cli))


def _failed(log: SessionLog, cli: SequenceCli) -> tuple[Lane, str]:
    """A board whose ruling on d2 failed, and the failed task's id."""
    _seed(log)
    lane = _lane(log, cli)
    run_turns(lane, _answer("d1"))
    failed = [one for one in impact_tasks(log.entries()).values() if one.target == "d2"]
    assert [one.phase for one in failed] == [STATUS_PHASE_ERROR]
    return lane, failed[0].id


def _retry(lane: Lane, task: str) -> None:
    turn = lane.retry(task)
    assert turn is not None, "the retry started nothing"
    turn.join(TIMEOUT)
    assert not turn.is_alive()


def _node(log: SessionLog, node_id: str) -> Any:
    return next(one for one in replay(log.epoch, log.entries()).decisions if one.id == node_id)


def _statuses(log: SessionLog) -> list[Any]:
    return [one for one in log.entries() if one.kind == STATUS_KIND]


def _items(log: SessionLog) -> list[tuple[Any, dict[str, Any]]]:
    return [(entry, item) for entry in _statuses(log) for item in entry.payload.get("tasks") or []]


def _revise(target: str, **fields: Any) -> dict[str, Any]:
    return {"kind": "revise", "target": target, "why": "the answer moved it", **fields}


def _rules_d2(*updates: dict[str, Any]) -> str:
    return document(
        "Ruled.",
        updates=updates,
        rulings=[{"decision": "d2", "ruling": "revise", "why": "the answer moved it"}],
    )


# --- the failure is a named blocker ------------------------------------------


def test_pnd_a5_a_failed_task_holds_its_decision_naming_cause_seat_and_time(
    log: SessionLog,
) -> None:
    """
    Given a marked answer whose ruling on d2 times out
    When the turn closes on its error
    Then d2 is waiting in image 1 with a failure naming the cause, the seat and
         the time the turn failed, and it is off the frontier.
    """
    _, task = _failed(log, SequenceCli([TIMED_OUT]))

    image = to_image1(replay(log.epoch, log.entries()))
    held = next(one for one in image.decisions if one.id == "d2")
    assert held.waiting is not None
    assert held.waiting.task == task
    failure = held.waiting.failed
    assert failure is not None, "the failure is not on the node"
    assert "it timed out" in failure.cause
    assert failure.seat == HEAVY_TIER
    closing = [one for one in _statuses(log) if one.payload["phase"] == STATUS_PHASE_ERROR][-1]
    assert failure.at == closing.timestamp
    assert "d2" not in image.frontier


def test_pnd_a5_a_live_task_carries_no_failure(log: SessionLog) -> None:
    """
    Given a marked answer whose ruling is still in flight
    When the board is read
    Then d2 is waiting with no failure on it, because nothing has failed yet.
    """
    _seed(log)
    hold = threading.Event()
    cli = SequenceCli([_rules_d2()], hold=hold)
    _, turns = _lane(log, cli).accept([_answer("d1")], log.epoch)
    assert cli.started.wait(TIMEOUT)
    try:
        held = _node(log, "d2")
        assert held.waiting is not None
        assert held.waiting.failed is None
    finally:
        hold.set()
        for one in turns:
            one.join(TIMEOUT)


# --- the retry ---------------------------------------------------------------


def test_pnd_a5_retry_records_a_task_naming_the_failed_one_whose_result_folds(
    log: SessionLog,
) -> None:
    """
    Given a failed ruling on d2
    When the human presses retry, and the expert's document revises d2 and d3
    Then the press is acknowledged by an entry ending the failed task, a new
         task in the failed one's mode opens naming it, over the board at the
         press, seated on the expert; the dispatch is scoped to d2 and what rests
         on it and carries the backpressure paragraph; and the result folds as
         the first run's would have -- d2 changes directly, with history naming
         the new task, and d3 waits in the inbox.
    """
    cli = SequenceCli(
        [TIMED_OUT, _rules_d2(_revise("d2", title=RETITLED), _revise("d3", title="x"))]
    )
    lane, failed = _failed(log, cli)
    gesture = next(one.seq for one in log.entries() if one.kind == "answer")

    _retry(lane, failed)

    accepted = [
        (entry, item)
        for entry, item in _items(log)
        if entry.payload["phase"] == STATUS_PHASE_ACCEPTED and item["id"] == failed
    ]
    assert len(accepted) == 1, "the press did not end the failed task"
    assert accepted[0][1]["phase"] == STATUS_PHASE_SUPERSEDED
    press = accepted[0][0].seq
    opened = [
        item
        for entry, item in _items(log)
        if entry.payload["phase"] == STATUS_PHASE_COMPOSING and item.get("retries") == failed
    ]
    assert len(opened) == 1, opened
    task = opened[0]
    assert task["id"] == f"impact-{press}-d2"
    assert task["target"] == "d2"
    assert task["mode"] == "impact"
    assert task["gesture"] == gesture
    assert task["basis"] == press
    assert task["seat"] == HEAVY_TIER

    context = DispatchContext.model_validate_json(
        sorted((log.directory / "dispatches").glob("*.json"))[-1].read_text(encoding="utf-8")
    )
    assert context.tasks == [task["id"]]
    assert context.scope == ["d2", "d3"]
    assert context.mootness is not None
    assert context.mootness.ids == ["d2"]
    assert context.backpressure
    prompt = cli.calls[-1][-1]
    assert "## A retry of a failed ruling" in prompt
    assert "d2, d3" in prompt

    d2 = _node(log, "d2")
    assert d2.title == RETITLED
    assert d2.waiting is None
    history = replay(log.epoch, log.entries()).history["d2"]
    assert history[-1].task == task["id"]
    queued = {
        (one.kind, one.target)
        for one in replay(log.epoch, log.entries()).pending
        if one.kind != "informational"
    }
    assert queued == {("revise", "d3")}


def test_pnd_a5_nothing_unlocks_when_the_retry_fails_too(log: SessionLog) -> None:
    """
    Given a failed ruling on d2
    When the retry fails as well
    Then d2 is still waiting, now on the retry's task, with the retry's own
         failure and the task it retried named, and it is still off the frontier.
    """
    lane, failed = _failed(log, SequenceCli([TIMED_OUT]))

    _retry(lane, failed)

    waiting = _node(log, "d2").waiting
    assert waiting is not None
    assert waiting.task != failed
    assert waiting.retries == failed
    assert waiting.failed is not None
    assert "d2" not in replay(log.epoch, log.entries()).frontier


def test_pnd_a5_the_retry_is_absent_once_an_upstream_answer_superseded_the_failure(
    log: SessionLog,
) -> None:
    """
    Given a failed ruling on d2
    When another answer marking d2 lands, and the human then presses retry on
         the failed task
    Then the failed task is superseded by the answer's own task, the waiting
         field carries no failure, and the press starts nothing and writes
         nothing.
    """
    lane, failed = _failed(log, SequenceCli([TIMED_OUT, _rules_d2()]))
    hold = threading.Event()
    lane.expert.cli.hold = hold  # type: ignore[union-attr]
    _, turns = lane.accept([_answer("d4")], log.epoch)
    try:
        assert impact_tasks(log.entries())[failed].phase == STATUS_PHASE_SUPERSEDED
        waiting = _node(log, "d2").waiting
        assert waiting is not None
        assert waiting.failed is None
        before = len(log.entries())

        assert lane.retry(failed) is None
        assert len(log.entries()) == before
    finally:
        hold.set()
        for one in turns:
            one.join(TIMEOUT)


def test_pnd_a5_pressing_retry_while_a_retry_is_live_starts_nothing(log: SessionLog) -> None:
    """
    Given a failed ruling on d2, and a retry of it still in flight
    When the human presses retry again
    Then nothing starts, and the log holds exactly one retry task.
    """
    cli = SequenceCli([TIMED_OUT, _rules_d2()])
    lane, failed = _failed(log, cli)
    hold = threading.Event()
    cli.hold = hold
    first = lane.retry(failed)
    assert first is not None
    try:
        assert lane.retry(failed) is None
    finally:
        hold.set()
        first.join(TIMEOUT)
    retries = [item for _, item in _items(log) if item.get("retries") == failed]
    assert len(retries) == 1, retries


def test_pnd_a5_two_presses_at_once_start_exactly_one_retry(log: SessionLog) -> None:
    """
    Given a failed ruling on d2
    When two presses of retry arrive together
    Then exactly one of them starts a retry, and the log holds one retry task.
    """
    lane, failed = _failed(log, SequenceCli([TIMED_OUT, _rules_d2()]))
    gate = threading.Barrier(2)
    started: list[threading.Thread | None] = []

    def press() -> None:
        gate.wait(TIMEOUT)
        started.append(lane.retry(failed))

    pressers = [threading.Thread(target=press) for _ in range(2)]
    for one in pressers:
        one.start()
    for one in pressers:
        one.join(TIMEOUT)
    turns = [one for one in started if one is not None]
    for one in turns:
        one.join(TIMEOUT)

    assert len(turns) == 1, started
    assert len([item for _, item in _items(log) if item.get("retries") == failed]) == 1


def test_pnd_a5_a_failed_pre_ruling_offers_no_retry(log: SessionLog) -> None:
    """
    Given a pre-ruling -- a task carrying the option it was computed for --
          that failed
    When the human presses retry on it
    Then nothing starts and nothing is written: a pre-ruling holds no lock, so
         there is no blocker for a retry to release.
    """
    _seed(log)
    name = "impact-6-d2-b"
    opened = log.emit_status(
        STATUS_PHASE_COMPOSING,
        "the 'heavy' tier is composing a reply",
        MAP_CHANNEL,
        tier=HEAVY_TIER,
        tasks=[
            {
                "id": name,
                "target": "d2",
                "gesture": 6,
                "basis": 6,
                "mode": "impact",
                "option": "b",
                "seat": HEAVY_TIER,
                "phase": STATUS_PHASE_COMPOSING,
            }
        ],
    )
    log.emit_status(
        STATUS_PHASE_ERROR,
        "the 'heavy' tier failed",
        MAP_CHANNEL,
        tasks=[{"id": name, "phase": STATUS_PHASE_ERROR}],
        opened=opened.seq,
    )
    lane = _lane(log, SequenceCli([_rules_d2()]))
    before = len(log.entries())

    assert lane.retry(name) is None
    assert len(log.entries()) == before


def test_pnd_a5_a_restart_mid_retry_recovers_the_same_state_from_the_log(
    session_dir: Path, log: SessionLog
) -> None:
    """
    Given a retry in flight when its process dies
    When a fresh backend opens the same directory
    Then the failed task reads superseded, the retry reads failed, d2 waits on
         the retry with its failure and the task it retried named, and the
         fresh backend offers a retry of the retry.
    """
    cli = SequenceCli([TIMED_OUT, _rules_d2()])
    lane, failed = _failed(log, cli)
    hold = threading.Event()
    cli.hold = hold
    turn = lane.retry(failed)
    assert turn is not None
    assert cli.started.wait(TIMEOUT)

    try:
        successor = open_session(session_dir)
        tasks = impact_tasks(successor.entries())
        assert tasks[failed].phase == STATUS_PHASE_SUPERSEDED
        retried = [one for one in tasks.values() if one.retries == failed]
        assert len(retried) == 1
        assert retried[0].phase == STATUS_PHASE_ERROR
        waiting = next(
            one for one in replay(successor.epoch, successor.entries()).decisions if one.id == "d2"
        ).waiting
        assert waiting is not None
        assert waiting.task == retried[0].id
        assert waiting.retries == failed
        assert waiting.failed is not None
    finally:
        hold.set()
        turn.join(TIMEOUT)


def test_pnd_a5_a_failed_decision_refuses_the_humans_answer_until_the_retry_lands(
    log: SessionLog,
) -> None:
    """
    Given a failed ruling on d2
    When the human answers d2 directly, then presses retry and the retry lands,
         then answers d2 again
    Then the first answer is refused as waiting on a ruling, and the second is
         accepted: only the retry's result or an upstream answer releases it.
    """
    cli = SequenceCli([TIMED_OUT, _rules_d2(_revise("d2", title=RETITLED))])
    lane, failed = _failed(log, cli)

    refused = log.submit([_answer("d2", "a", "too-early")], log.epoch)[0]
    assert refused.status == "rejected"
    assert refused.reason == REASON_DECISION_WAITING

    _retry(lane, failed)

    taken = log.submit([_answer("d2", "a", "after-retry")], log.epoch)[0]
    assert taken.status == "accepted", taken


# --- the retry's scope -------------------------------------------------------


def test_pnd_a8_a_retry_document_reaching_outside_the_subtree_is_refused_at_the_gate(
    log: SessionLog,
) -> None:
    """
    Given a retry's document scoped to d2 and d3 that revises d5 as well
    When it is recorded
    Then it is refused naming d5, and nothing of it reaches the log; the same
         document with the d5 revise left out lands.
    """
    _seed(log)
    owed = MootnessObligation(target="d1", answer="Rebuild it", ids=["d2"], gesture=6)
    outside = read_document(_rules_d2(_revise("d2", title=RETITLED), _revise("d5", title="x")))
    before = len(log.entries())

    with pytest.raises(ReplyRefusedError) as refused:
        record_document(log, HEAVY_TIER, outside, {}, owed, (), scope=("d2", "d3"))

    assert "d5" in str(refused.value)
    assert len(log.entries()) == before
    inside = read_document(_rules_d2(_revise("d2", title=RETITLED), _revise("d3", title="x")))
    assert record_document(log, HEAVY_TIER, inside, {}, owed, (), scope=("d2", "d3"))


def test_pnd_a8_a_retry_that_reaches_outside_twice_fails_and_lands_nothing(
    log: SessionLog,
) -> None:
    """
    Given a failed ruling on d2, and a retry whose seat revises d5 on both of
          its asks
    When the human presses retry
    Then the seat's second ask quotes the refusal, the retry fails holding d2,
         and d5 is untouched.
    """
    reach = _rules_d2(_revise("d5", title="Moved"))
    cli = SequenceCli([TIMED_OUT, reach, reach])
    lane, failed = _failed(log, cli)

    _retry(lane, failed)

    assert "d5" in cli.calls[-1][-1], "the retry's second ask did not quote the fault"
    assert _node(log, "d5").title == "Which d5?"
    waiting = _node(log, "d2").waiting
    assert waiting is not None
    assert waiting.retries == failed
    assert waiting.failed is not None


def test_pnd_a5_the_retry_route_starts_one_retry_and_then_reports_none(log: SessionLog) -> None:
    """
    Given a failed ruling on d2
    When the page posts the retry twice for that task
    Then the first post starts it and the second reports that nothing started.
    """
    cli = SequenceCli([TIMED_OUT, _rules_d2()])
    hold = threading.Event()
    _seed(log)
    client = driven(log, SpyDriver(), HeavyDriver(TierConfig.from_env({}), cli))
    response = client.post(
        "/events", json={"epoch": log.epoch, "events": [_answer("d1").model_dump()]}
    )
    assert response.status_code == 200
    deadline = threading.Event()
    while not any(one.phase == STATUS_PHASE_ERROR for one in impact_tasks(log.entries()).values()):
        deadline.wait(0.01)
    failed = next(iter(impact_tasks(log.entries())))
    cli.hold = hold
    try:
        first = client.post("/retry", json={"task": failed}).json()
        second = client.post("/retry", json={"task": failed}).json()
    finally:
        hold.set()
    assert first == {"started": True}
    assert second == {"started": False}
