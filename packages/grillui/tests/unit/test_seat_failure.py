"""What a seat that fails leaves behind: a trace the human can read, and the
obligation the turn carried handed up or stated, never dropped.

A seat fails three ways the lane has to tell the human about: it cannot be
reached, it runs out of time, or the board refuses what it sent once the ladder
is spent. Each is a turn that ends without its reply, and each used to end the
same way -- an `error` entry nobody drew, and whatever the turn owed the board
gone with it.

The drivers here raise the way real ones do, so what is pinned is the lane's
handling of the failure and not any one transport's way of producing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from conftest import SpyDriver, run_turns
from test_lane import _seed, _seed_resting, statuses

from grillui.drivers import ReplyRefusedError, take_document
from grillui.lane import AgentUnreachableError, DocumentRefusedError, Lane
from grillui.log import SessionLog
from grillui.projector import impact_tasks, replay
from grillui.schemas import (
    FAST_TIER,
    HEAVY_TIER,
    MAP_CHANNEL,
    PRESSED_KEY,
    STATUS_PHASE_COMPOSING,
    STATUS_PHASE_ERROR,
    STATUS_PHASE_REPLIED,
    EventSubmission,
    GrillMasterDocument,
)

THREAD = "t1"


@dataclass
class FailingDriver:
    """A seat that raises out of every turn, the way a dead transport does."""

    tier: str
    error: Exception
    dispatches: list[Path] = field(default_factory=list)

    def run(self, _log: SessionLog, dispatch: Path, /) -> int | None:
        self.dispatches.append(dispatch)
        raise self.error


def _notices(log: SessionLog) -> list[str]:
    return [
        str(entry.payload.get("text"))
        for entry in log.entries()
        if entry.kind == "informational" and entry.actor == "backend"
    ]


def _errors(log: SessionLog) -> list[str]:
    return [str(one.payload.get("detail")) for one in statuses(log, STATUS_PHASE_ERROR)]


def _speak_in_thread(lane: Lane) -> None:
    """A thread the agent opened, and the human's turn in it, run out."""
    lane.log.submit(
        [
            EventSubmission(
                kind="thread-created",
                actor="grill-master",
                channel=THREAD,
                idempotency_key="mandate-1",
                payload={"turns": [{"who": "grill-master", "text": "This needs a thread."}]},
            )
        ],
        lane.log.epoch,
    )
    run_turns(
        lane,
        EventSubmission(
            kind="thread-turn",
            actor="human",
            channel=THREAD,
            idempotency_key="human-thread-1",
            payload={"turns": [{"who": "human", "text": "Durability is the point."}]},
        ),
    )


def _strand(lane: Lane) -> None:
    """The human applying an invalidate that strands `d2` and `d3`, run out."""
    log = lane.log
    _seed_resting(log)
    log.submit(
        [
            EventSubmission(
                kind="invalidate",
                actor="grill-master",
                idempotency_key="kill-d1",
                payload={"target": "d1", "why": "the export was dropped"},
            )
        ],
        log.epoch,
    )
    queued = replay(log.epoch, log.entries()).pending[0].id
    run_turns(
        lane,
        EventSubmission(
            kind="apply", actor="human", idempotency_key="apply-d1", payload={"pending": [queued]}
        ),
    )


def test_pnd_a13_a_thread_turn_whose_seat_fails_ends_on_an_error_naming_seat_and_cause(
    log: SessionLog,
) -> None:
    """
    Given a thread whose first-rung seat cannot be reached, and an expert that can
    When the human speaks in the thread
    Then the lane closes the thread's turn on an `error` naming the seat and the
         cause, and the expert is not engaged.

    The reply the thread turn owed is recorded unmet by that error, which the
    page draws as a trace. It is not handed up, because only the human's own
    gesture engages the expert on a thread.
    """
    fast = FailingDriver(FAST_TIER, AgentUnreachableError(FAST_TIER, "it exited 1"))
    expert = SpyDriver(tier=HEAVY_TIER, reply="Never asked.")
    lane = Lane(log, fast, expert=expert)

    _speak_in_thread(lane)

    assert expert.dispatches == [], "a thread turn engaged the expert without the human"
    closing = statuses(log)[-1]
    assert closing.channel == THREAD
    assert closing.payload["phase"] == STATUS_PHASE_ERROR
    assert "'fast' tier failed" in closing.payload["detail"]
    assert "it exited 1" in closing.payload["detail"]
    said = _notices(log)
    assert len(said) == 1, said
    assert f"thread {THREAD!r}" in said[0]
    assert "'fast' tier failed" in said[0]
    assert "it exited 1" in said[0]


def test_pnd_a13_an_appender_refusal_on_a_thread_is_quoted_in_its_error(
    log: SessionLog,
) -> None:
    """
    Given a thread whose seat's reply the appender refuses
    When the human speaks in the thread
    Then the turn's error, and the notice the human reads, quote the
         appender's reason.
    """
    refused = ReplyRefusedError(FAST_TIER, "the appender refused it: unknown node id: d9")
    lane = Lane(log, FailingDriver(FAST_TIER, refused), expert=SpyDriver(tier=HEAVY_TIER))

    _speak_in_thread(lane)

    assert "unknown node id: d9" in _errors(log)[-1]
    assert any("unknown node id: d9" in one for one in _notices(log)), _notices(log)


def _clerical(lane: Lane) -> None:
    """The human taking an unmarked option on the map, and the turn it buys."""
    _seed(lane.log)
    run_turns(
        lane,
        EventSubmission(
            kind="answer",
            actor="human",
            idempotency_key="human-answer",
            payload={"target": "d2", "answer": {"option": "a"}},
        ),
    )


def test_pnd_a13_a_failure_on_both_rungs_closes_on_an_error_naming_both_seats(
    log: SessionLog,
) -> None:
    """
    Given a map whose first rung and expert both cannot be reached
    When the human answers an unmarked option
    Then the lane closes on one `error` naming each seat and each cause, in the
         order the ladder met them.
    """
    fast = FailingDriver(FAST_TIER, AgentUnreachableError(FAST_TIER, "it exited 1"))
    expert = FailingDriver(HEAVY_TIER, AgentUnreachableError(HEAVY_TIER, "timed out"))
    lane = Lane(log, fast, expert=expert)

    _clerical(lane)

    errors = _errors(log)
    assert len(errors) == 1, errors
    assert errors[0].index("'fast' tier failed") < errors[0].index("'heavy' tier failed")
    assert "it exited 1" in errors[0]
    assert "timed out" in errors[0]


def test_pnd_a13_an_unreachable_expert_states_the_stranded_decisions_unmet(
    log: SessionLog,
) -> None:
    """
    Given two decisions resting on a third, and an expert that cannot be reached
    When the human applies the invalidate on that third
    Then the turn closes on an error naming the expert, one backend notice
         traces the failure, and another names both stranded decisions as
         unruled.

    The applied invalidate's obligation rides no task, so nothing else on the
    log would say that a ruling on them was owed and never made.
    """
    fast = SpyDriver(tier=FAST_TIER, reply="Noted.")
    expert = FailingDriver(HEAVY_TIER, AgentUnreachableError(HEAVY_TIER, "timed out"))
    lane = Lane(log, fast, expert=expert)

    _strand(lane)

    assert len(expert.dispatches) == 1
    assert "'heavy' tier failed" in _errors(log)[-1]
    said = _notices(log)
    assert len(said) == 2, said
    assert "'heavy' tier failed" in said[0]
    assert "d2, d3" in said[1]


def test_pnd_a13_a_document_refused_at_the_last_rung_states_the_obligation_unmet(
    log: SessionLog,
) -> None:
    """
    Given the same stranded decisions, and an expert whose document the board
          refuses after its own retry
    When the human applies the invalidate
    Then the human is told nothing was taken from the turn, and told which
         decisions were left unruled.
    """
    fast = SpyDriver(tier=FAST_TIER, reply="Noted.")
    expert = FailingDriver(HEAVY_TIER, DocumentRefusedError(HEAVY_TIER, "unknown node id"))
    lane = Lane(log, fast, expert=expert)

    _strand(lane)

    said = _notices(log)
    assert len(said) == 2, said
    assert "nothing was taken" in said[0]
    assert "unknown node id" in said[0], "the board's reason was not quoted"
    assert "d2, d3" in said[1]
    assert statuses(log)[-1].payload["phase"] == STATUS_PHASE_ERROR


def test_pnd_a13_a_failed_task_turn_leaves_its_targets_held_rather_than_offered(
    log: SessionLog,
) -> None:
    """
    Given an answer whose option puts two decisions in question, and an expert
          that cannot be reached
    When the human takes that option
    Then each task ends failed and holds its decision, the turn's error and
         its one notice name the seat and the cause, and no notice tells the
         human the board is offering decisions it is in fact holding.
    """
    fast = SpyDriver(tier=FAST_TIER, reply="Noted.")
    expert = FailingDriver(HEAVY_TIER, AgentUnreachableError(HEAVY_TIER, "timed out"))
    lane = Lane(log, fast, expert=expert)
    _seed(log)

    run_turns(
        lane,
        EventSubmission(
            kind="answer",
            actor="human",
            idempotency_key="human-answer",
            payload={"target": "d1", "answer": {"option": "b"}},
        ),
    )

    tasks = impact_tasks(log.entries())
    assert {one.phase for one in tasks.values()} == {STATUS_PHASE_ERROR}
    assert all(one.holds for one in tasks.values())
    assert "timed out" in _errors(log)[-1]
    said = _notices(log)
    assert len(said) == 1, said
    assert "timed out" in said[0]
    assert "d2" not in said[0]


def test_pnd_a13_a_turn_that_succeeds_records_no_failure_trace(log: SessionLog) -> None:
    """
    Given a thread whose first-rung seat answers
    When the human speaks in the thread
    Then nothing on the log is an error, a hand-up, or a notice in the backend's
         own voice.
    """
    expert = SpyDriver(tier=HEAVY_TIER, reply="Never asked.")
    lane = Lane(log, SpyDriver(tier=FAST_TIER, reply="Answered."), expert=expert)

    _speak_in_thread(lane)

    assert _errors(log) == []
    assert not [one for one in statuses(log) if one.payload.get(PRESSED_KEY)]
    assert _notices(log) == []
    assert expert.dispatches == []


def test_a_document_refused_at_the_last_rung_names_the_rulings_and_stop_it_carried(
    log: SessionLog,
) -> None:
    """
    Given an expert whose document read as the map document and was still
          refused by the board, carrying rulings and a met stop condition
    When the human applies the invalidate it was asked to rule on
    Then the notice saying nothing was taken names each ruling it carried and
         says its judgement that the grilling is over went with it.

    A refused turn's judgement dies with it. Saying what died is what lets the
    human ask for it again rather than assume it was never made.
    """
    carried = GrillMasterDocument.model_validate(
        {
            "text": "Both rest on nothing now.",
            "updates": [],
            "supersedes": [],
            "rulings": [
                {"decision": "d2", "ruling": "invalidate", "why": "gone"},
                {"decision": "d3", "ruling": "stands", "why": "independent"},
            ],
            "stop": {"met": True, "why": "nothing is left"},
        }
    )
    refused = DocumentRefusedError(HEAVY_TIER, "unknown node id", carried)
    lane = Lane(log, SpyDriver(tier=FAST_TIER), expert=FailingDriver(HEAVY_TIER, refused))

    _strand(lane)

    lost = _notices(log)[0]
    assert "d2 invalidate" in lost, lost
    assert "d3 stands" in lost, lost
    assert "grilling is over" in lost, lost


def test_the_ladder_hands_the_lane_the_document_the_appender_refused() -> None:
    """
    Given a seat whose valid document the appender refuses twice
    When the ladder gives up on it
    Then the refusal it raises carries that document, so its rulings can be
         named to the human; a reply that never read as the document carries
         none.
    """
    reply = (
        '{"text": "Done.", "updates": [], "supersedes": [], '
        '"rulings": [{"decision": "d2", "ruling": "stands", "why": "fine"}], '
        '"stop": {"met": false}}'
    )

    def land(_outcome: Any) -> None:
        raise ReplyRefusedError(HEAVY_TIER, "the appender refused it: unknown node id")

    with pytest.raises(DocumentRefusedError) as valid:
        take_document(HEAVY_TIER, "ask", lambda _prompt: reply, lambda said: said, land)
    assert valid.value.document is not None
    assert [one.decision for one in valid.value.document.rulings] == ["d2"]

    with pytest.raises(DocumentRefusedError) as prose:
        take_document(HEAVY_TIER, "ask", lambda _prompt: "prose", lambda said: said, land)
    assert prose.value.document is None


def test_pnd_a13_a_map_turn_whose_seat_fails_is_handed_up_and_says_so(
    log: SessionLog,
) -> None:
    """
    Given a clerical map gesture whose first-rung seat cannot be reached
    When the human answers an unmarked option
    Then the expert takes the turn on a hand-up announcement, the map carries
         one opening `composing` and one closing `replied` for it, and a backend
         notice names the seat that failed, why, and the seat it went up to.

    Said even though the turn landed: a dead seat is a fault the human may want
    to act on, and the turn landing on the rung above would hide it.
    """
    fast = FailingDriver(FAST_TIER, AgentUnreachableError(FAST_TIER, "it exited 1"))
    expert = SpyDriver(tier=HEAVY_TIER, reply="Taken.")
    lane = Lane(log, fast, expert=expert)

    _clerical(lane)

    on_map = [one for one in statuses(log) if one.channel == MAP_CHANNEL]
    opened = [
        one
        for one in on_map
        if one.payload["phase"] == STATUS_PHASE_COMPOSING and not one.payload.get(PRESSED_KEY)
    ]
    closed = [one for one in on_map if one.payload["phase"] == STATUS_PHASE_REPLIED]
    assert len(opened) == 1 and len(closed) == 1, [one.payload for one in on_map]
    assert len(expert.dispatches) == 1
    said = _notices(log)
    assert len(said) == 1, said
    assert "'fast' tier failed" in said[0]
    assert "it exited 1" in said[0]
    assert "'heavy' tier" in said[0]
