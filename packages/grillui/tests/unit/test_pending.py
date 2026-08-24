"""The pending queue, superseding, and the map doctor.

Three rules are pinned here.

**Every grill-master dispatch carries the queue the human is looking at.** That
is asserted against the bytes the backend wrote under `dispatches/`, never
against an image the test folded for itself: what an agent was told about the
queue is exactly what is in those bytes, and a check on an in-memory image would
pass just as happily against a recorder that dropped the queue on the way out.

**A withdrawal the human got in front of goes back to its author.** The board
must be exactly as the human left it afterwards, so the assertions are about
what did *not* happen as much as about the dispatch that did -- no answer
rewritten, no notice resurrected, no map mutation from anyone but the
grill-master.

**The map doctor freezes the board and lets it go.** The freeze is a property of
this process, so the assertions are on the lane's own state with a turn held
mid-flight and released by the test, rather than on a timer.

Nothing here reaches a network or a model: every turn runs against a scripted
driver, and every concurrency claim is settled by joining the turn's thread.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from conftest import TIMEOUT, SpyDriver, document, driven
from fastapi.testclient import TestClient

from grillui.dispatch import DISPATCH_DIR, GRILL_MASTER, record_dispatch
from grillui.drivers import declared_updates, document_problem, record_reply
from grillui.lane import Lane, UnreachableDriver
from grillui.log import SessionLog
from grillui.projector import fold, supersede_conflicts
from grillui.schemas import (
    FOLD_KIND,
    MAP_CHANNEL,
    MAP_MUTATION_KINDS,
    STATUS_KIND,
    STATUS_PHASE_ERROR,
    SUPERSEDES_KEY,
    DispatchContext,
    EventSubmission,
    Image2,
    LogEntry,
)
from grillui.tiers import REASSESS_RULE, SUPERSEDE_CONFLICT_RULE, SUPERSEDE_RULE, compose

NODE = "d-store"
OTHER = "d-compaction"
NOTICE = "notice-store"
OTHER_NOTICE = "notice-compaction"
HUMAN_ANSWER = "an append-only log, because the audit trail is the point"
# One fast-tier reply, copied out of a live session's log byte for byte: the
# fence a hosted model put around its update object, and the reason a session's
# whole map went unmoved while the human was told it had been settled.
LIVE_FENCED_REPLY = (Path(__file__).parent / "fenced-map-reply.txt").read_text(encoding="utf-8")


@dataclass
class ScriptedMap:
    """A grill-master that says its scripted piece, one reply per turn.

    The replies go into the log through the real reply path, so what a scripted
    turn can and cannot make the board do is what a real one can: a driver that
    wrote entries of its own would prove nothing about the appender that stands
    between an agent and the board.
    """

    replies: list[str] = field(default_factory=list)
    tier: str = "heavy"
    dispatches: list[Path] = field(default_factory=list)
    ran: threading.Semaphore = field(default_factory=lambda: threading.Semaphore(0))

    def run(self, log: SessionLog, dispatch: Path, /) -> None:
        self.dispatches.append(dispatch)
        context = DispatchContext.model_validate_json(dispatch.read_text(encoding="utf-8"))
        reply = self.replies.pop(0) if self.replies else document(text="Nothing further.")
        try:
            record_reply(log, self.tier, context.channel, reply, {})
        finally:
            self.ran.release()

    def recorded(self, index: int) -> DispatchContext:
        return DispatchContext.model_validate_json(
            self.dispatches[index].read_text(encoding="utf-8")
        )


def withdrawing(text: str, *ids: str) -> str:
    """A reply that withdraws pending notices and changes nothing else."""
    return document(text=text, supersedes=list(ids))


def submit(
    log: SessionLog, kind: str, key: str, actor: str = "grill-master", **payload: Any
) -> None:
    receipt = log.submit(
        [EventSubmission(kind=kind, actor=actor, idempotency_key=key, payload=payload)], log.epoch
    )[0]
    assert receipt.status == "accepted", receipt


def seed(log: SessionLog, node_id: str = NODE) -> None:
    """One decision on the board, minted the way an agent mints one."""
    submit(
        log,
        "add-node",
        f"seed-{node_id}",
        target=node_id,
        short=node_id,
        title="Which storage?",
        body="Pick the storage layer.",
        prereqs=[],
        options=[{"id": "a", "text": "Append-only log"}, {"id": "b", "text": "Mutable table"}],
    )


def notice(
    log: SessionLog, key: str = NOTICE, target: str = NODE, actor: str = "grill-master"
) -> None:
    """One notice on the pending queue, whose pending id is its key."""
    submit(
        log,
        "elicit-alert",
        key,
        actor=actor,
        target=target,
        text="This answer may not survive the retention question.",
        blocking=False,
    )


def answer(log: SessionLog, node_id: str = NODE, key: str = "human-answer") -> None:
    submit(
        log,
        "answer",
        key,
        actor="human",
        target=node_id,
        answer={"option": "a", "text": HUMAN_ANSWER},
        why="the audit trail is the point",
    )


def answering(node_id: str = NODE, key: str = "human-answer") -> EventSubmission:
    return EventSubmission(
        kind="answer",
        actor="human",
        channel=MAP_CHANNEL,
        idempotency_key=key,
        payload={"target": node_id, "answer": {"option": "a", "text": HUMAN_ANSWER}},
    )


def run_turns(lane: Lane, *events: EventSubmission) -> None:
    """Accept human gestures and wait out every turn they set off, including
    any the backend raised on its own afterwards."""
    for event in events:
        _receipts, threads = lane.accept([event], lane.log.epoch)
        for thread in threads:
            thread.join(TIMEOUT)
            assert not thread.is_alive()


def recorded(session_dir: Path) -> list[str]:
    """The dispatch files as the backend left them, in dispatch order."""
    return [
        path.read_text(encoding="utf-8")
        for path in sorted((session_dir / DISPATCH_DIR).glob("*.json"))
    ]


def queue_of(recorded_bytes: str) -> list[dict[str, Any]]:
    """The pending queue as one recorded dispatch states it."""
    document: dict[str, Any] = json.loads(recorded_bytes)
    queue: list[dict[str, Any]] = document["image2"]["pending"]
    return queue


def image(log: SessionLog) -> Image2:
    return fold(log.epoch, log.entries())


def mutations(entries: list[LogEntry]) -> list[LogEntry]:
    return [entry for entry in entries if entry.kind in MAP_MUTATION_KINDS]


# GUI-A38 -- the queue is in the dispatch, as of dispatch time.


def test_a_recorded_dispatch_names_every_queued_updates_id_target_and_kind(
    log: SessionLog, session_dir: Path
) -> None:
    """
    Given two notices standing on the pending queue
    When the backend records a grill-master dispatch
    Then the file it wrote carries both, each with its id, its target and its
         kind.

    The grill-master reasons about the board the human is actually looking at,
    and the queue is the part of that board it did not put there itself. A
    dispatch that carried the decisions and left the queue behind would have the
    agent repeating notices the human is already staring at.
    """
    seed(log)
    seed(log, OTHER)
    notice(log)
    notice(log, OTHER_NOTICE, OTHER)

    record_dispatch(log)

    queue = queue_of(recorded(session_dir)[0])
    assert [(one["id"], one["target"], one["kind"]) for one in queue] == [
        (NOTICE, NODE, "elicit-alert"),
        (OTHER_NOTICE, OTHER, "elicit-alert"),
    ]


def test_the_dispatched_queue_is_the_one_standing_when_the_dispatch_was_folded(
    log: SessionLog, session_dir: Path
) -> None:
    """
    Given a dispatch recorded before a second notice was authored
    When another dispatch is recorded after it
    Then the first names one queued update and the second names two.

    "As of dispatch time" is the whole claim: a queue read from anything cached
    would tell one turn about a notice that arrived after it, or leave the next
    turn reasoning from a queue the human cleared minutes ago.
    """
    seed(log)
    seed(log, OTHER)
    notice(log)
    record_dispatch(log)

    notice(log, OTHER_NOTICE, OTHER)
    record_dispatch(log)

    first, second = recorded(session_dir)
    assert [one["id"] for one in queue_of(first)] == [NOTICE]
    assert [one["id"] for one in queue_of(second)] == [NOTICE, OTHER_NOTICE]


def test_every_grill_master_dispatch_the_lane_raises_carries_the_queue(
    log: SessionLog, session_dir: Path
) -> None:
    """
    Given a queued notice on a decision nobody has answered
    When the human speaks on the map and the lane dispatches the grill-master
    Then that dispatch is addressed to the grill-master and carries the queue.

    Asserted on the lane's own dispatch rather than on a hand-made one, because
    "every dispatch" is a claim about the path the backend actually takes.
    """
    seed(log)
    seed(log, OTHER)
    notice(log, OTHER_NOTICE, OTHER)
    driver = ScriptedMap(replies=[document(text="Noted.")])

    run_turns(Lane(log, driver), answering())

    context = driver.recorded(0)
    assert context.agent == GRILL_MASTER
    assert [(one.id, one.target, one.kind) for one in context.image2.pending] == [
        (OTHER_NOTICE, OTHER, "elicit-alert")
    ]
    assert OTHER_NOTICE in recorded(session_dir)[0]


# GUI-A39 -- superseding, and the conflict when the human got there first.


def test_a_grill_master_withdrawing_its_own_queued_notice_marks_it_superseded(
    log: SessionLog,
) -> None:
    """
    Given a notice the grill-master queued earlier
    When a later grill-master response withdraws it
    Then the item stays in the queue marked superseded, and no conflict is
         raised.

    Marked rather than deleted: the queue is what the next dispatch tells the
    agent the human is looking at, and an item that vanished would leave the
    page and the agent disagreeing about whether the notice was ever sent.
    """
    seed(log)
    notice(log)

    submit(log, "informational", "reply-2", text="Ignore that.", supersedes=[NOTICE])

    queue = image(log).pending
    # The withdrawal is itself something the human has not read yet, so it joins
    # the queue behind the item it marks.
    assert [(one.id, one.superseded) for one in queue] == [(NOTICE, True), ("reply-2", False)]
    assert supersede_conflicts(log.entries()) == []


def test_a_withdrawal_naming_a_notice_the_sender_did_not_author_changes_nothing(
    log: SessionLog,
) -> None:
    """
    Given a notice the human authored
    When the grill-master's response names that notice as superseded
    Then the item is untouched.

    Superseding is an author revising itself. A response able to withdraw
    somebody else's notice is a response able to clear the queue of everything
    it would rather the human did not read.
    """
    seed(log)
    notice(log, actor="human")

    submit(log, "informational", "reply-2", text="Ignore that.", supersedes=[NOTICE])

    assert [(one.id, one.superseded) for one in image(log).pending] == [
        (NOTICE, False),
        ("reply-2", False),
    ]


def test_the_human_answering_a_decision_takes_its_notices_off_the_queue(
    log: SessionLog,
) -> None:
    """
    Given notices standing on two decisions
    When the human answers one of them
    Then that decision's notice leaves the queue and the other's stays.

    The queue is what the human has not yet dealt with, and answering the
    decision a notice is about is dealing with it -- they were told, and then
    they decided. Merely reading a notice is not: read-state is the page's and
    never crosses the wire.
    """
    seed(log)
    seed(log, OTHER)
    notice(log)
    notice(log, OTHER_NOTICE, OTHER)

    answer(log)

    assert [one.id for one in image(log).pending] == [OTHER_NOTICE]


def test_a_withdrawal_the_human_got_in_front_of_goes_back_to_the_grill_master(
    log: SessionLog,
) -> None:
    """
    Given a notice the human has already answered the decision of
    When the grill-master's next reply withdraws that notice
    Then the backend dispatches the grill-master again, and that dispatch names
         the update, its target and the sequence the human acted at.

    Only the authoring agent knows what the rewrite was for. A backend that
    picked one of the two -- the withdrawal or the human's answer -- would be
    settling a design question by dropping half of it.
    """
    seed(log)
    notice(log)
    driver = ScriptedMap(
        replies=[withdrawing("That no longer holds.", NOTICE), document(text="Understood.")]
    )

    run_turns(Lane(log, driver), answering())

    assert len(driver.dispatches) == 2
    handed_back = driver.recorded(1)
    assert handed_back.agent == GRILL_MASTER
    assert handed_back.conflict is not None
    assert handed_back.conflict.update.id == NOTICE
    assert handed_back.conflict.update.target == NODE
    assert handed_back.conflict.update.kind == "elicit-alert"
    assert handed_back.conflict.applied_at == 3


def test_the_conflict_dispatch_rewrites_nothing_on_the_board(log: SessionLog) -> None:
    """
    Given the same conflict, handed back to the grill-master
    When the dispatch has been recorded
    Then the human's answer stands untouched, the notice is not back on the
         queue, and every map mutation in the log is still the grill-master's.

    Neither the page nor the backend resolves a conflict. What the backend may
    do is ask; anything it decided for itself would be a decision the human made
    being reversed by code that does not know why.
    """
    seed(log)
    notice(log)
    driver = ScriptedMap(
        replies=[withdrawing("That no longer holds.", NOTICE), document(text="Understood.")]
    )

    run_turns(Lane(log, driver), answering())

    board = image(log)
    settled = next(one for one in board.decisions if one.id == NODE)
    assert settled.status == "settled"
    assert settled.answer is not None
    assert settled.answer.text == HUMAN_ANSWER
    assert all(one.id != NOTICE for one in board.pending)
    assert {entry.actor for entry in mutations(log.entries())} <= {"grill-master", "human"}


def test_a_conflict_already_handed_back_is_not_handed_back_again(log: SessionLog) -> None:
    """
    Given one conflict already reconciled on an earlier turn
    When a second, different conflict is raised on a later turn
    Then only the new one is dispatched: four turns in total, not five.

    A conflict is a disagreement, not a standing condition. Re-sending one every
    turn would spend the grill-master's turn on something it already answered,
    and the log grows with every turn, so the queue of grievances would only get
    longer.
    """
    seed(log)
    seed(log, OTHER)
    notice(log)
    notice(log, OTHER_NOTICE, OTHER)
    driver = ScriptedMap(
        replies=[
            withdrawing("The store notice no longer holds.", NOTICE),
            document(text="Understood."),
            withdrawing("Nor does the compaction one.", OTHER_NOTICE),
            document(text="Understood."),
        ]
    )

    run_turns(Lane(log, driver), answering(), answering(OTHER, key="human-answer-2"))

    conflicts = [one.update.id for one in supersede_conflicts(log.entries())]
    assert conflicts == [NOTICE, OTHER_NOTICE]
    assert len(driver.dispatches) == 4
    assert [context.conflict is not None for context in map(driver.recorded, range(4))] == [
        False,
        True,
        False,
        True,
    ]


def test_a_reply_that_only_withdraws_carries_the_withdrawal_into_the_log(
    log: SessionLog,
) -> None:
    """
    Given a grill-master reply that withdraws a notice and declares no updates
    When the driver records it
    Then the entry it appended carries the withdrawal.

    The common case changes nothing on the board: the agent is taking back what
    it told the human last turn. A reply shape that could only withdraw
    alongside a map update would make the ordinary self-correction impossible to
    say.
    """
    seed(log)
    notice(log)

    record_reply(log, "heavy", MAP_CHANNEL, withdrawing("Ignore that.", NOTICE), {})

    spoken = log.entries()[-1]
    assert spoken.kind == "informational"
    assert spoken.payload["text"] == "Ignore that."
    assert spoken.payload[SUPERSEDES_KEY] == [NOTICE]
    assert [(one.id, one.superseded) for one in image(log).pending if one.id == NOTICE] == [
        (NOTICE, True)
    ]


def test_a_reply_that_is_neither_an_update_nor_a_withdrawal_is_prose() -> None:
    """
    Given a JSON reply of some other shape
    When it is read for what the turn declared
    Then it is what the agent said, and nothing was declared.

    Guessing at a half-shaped object would author board changes -- or clear a
    queue, or answer a decision -- out of a reply that asked for none of them.
    """
    assert declared_updates('{"text": "just prose"}') == ('{"text": "just prose"}', [], [], None)
    assert declared_updates("plain words") == ("plain words", [], [], None)
    half_shaped = '```json\n{"text": "just prose"}\n```'
    assert declared_updates(half_shaped) == (half_shaped, [], [], None)


FENCED_SAID = "Decision d1 is settled on option a (the whole spec, four parts)."
FENCED_REVISE = {"kind": "revise", "target": "d1", "basis": 4}


@pytest.mark.parametrize("fence", ["```json\n{body}\n```", "```\n{body}```", "{body}"])
def test_a_document_lands_as_the_updates_it_declared_through_whatever_fence(
    log: SessionLog, fence: str
) -> None:
    """
    Given one document sent fenced as a hosted model presents JSON, fenced with
          no info string, and bare
    When the driver records each
    Then each lands as a fold carrying the update it declared, with the fence
         nowhere in what the human is told.

    A fence is how a model presents JSON to a reader, not something the turn
    said. Read as prose, every update it declared is discarded without a word:
    the human gets an answer whose text is raw JSON, the board does not move,
    and nothing in the log says a change was ever proposed.
    """
    seed(log, "d1")

    record_reply(
        log,
        "fast",
        MAP_CHANNEL,
        fence.format(body=document(text=FENCED_SAID, updates=[FENCED_REVISE])),
        {},
    )

    spoken = log.entries()[-1]
    assert spoken.kind == FOLD_KIND
    said, declared = spoken.payload["updates"][0], spoken.payload["updates"][1]
    assert said["kind"] == "informational"
    assert said["text"] == FENCED_SAID
    assert "```" not in said["text"]
    assert (declared["kind"], declared["target"]) == ("revise", "d1")


def test_the_reply_one_live_session_sent_is_refused_by_the_shape() -> None:
    """
    Given the reply a hosted model actually sent in a live session
    When it is judged against the document shape
    Then it is refused, naming the keys it is missing and the one it carried
         outside the shape.

    Kept as the bytes that arrived rather than corrected into the shape: the
    fault is what a model does unprompted -- three keys dropped and a `basis`
    hoisted to the top level -- and it is why the shape is closed rather than
    read leniently for whatever it happens to carry.
    """
    problem = document_problem(LIVE_FENCED_REPLY)

    assert problem is not None
    for missing in ("supersedes", "rulings", "stop"):
        assert missing in problem
    assert "basis" in problem


def test_the_conflict_dispatch_tells_the_turn_why_it_was_called(log: SessionLog) -> None:
    """
    Given a dispatch carrying a supersede conflict
    When the turn's prompt is composed
    Then it names the update, when the human acted, and whose the
         reconciliation is.

    The board looks exactly as it did before -- the conflict is the absence of a
    change. A turn left to infer that from the board is a turn that will not.
    """
    seed(log)
    notice(log)
    answer(log)
    submit(log, "informational", "withdrawal", text="Taking that back.", supersedes=[NOTICE])
    conflict = supersede_conflicts(log.entries())[0]

    path = record_dispatch(log, conflict=conflict)
    body = path.read_text(encoding="utf-8")
    prompt = compose(body, DispatchContext.model_validate_json(body), log.entries())

    assert NOTICE in prompt
    assert SUPERSEDE_CONFLICT_RULE in prompt
    assert REASSESS_RULE not in prompt


def test_the_grill_masters_standing_brief_says_how_to_withdraw() -> None:
    """
    Given the grill-master's system prompt
    Then it states how a response withdraws its own pending notices.

    An agent handed a queue it has no way to act on will act on it anyway -- by
    repeating itself into a queue the human is already looking at.
    """
    from grillui.tiers import HEAVY_TIER, system_prompt

    assert SUPERSEDE_RULE in system_prompt(HEAVY_TIER, GRILL_MASTER)


# GUI-A40 -- the map doctor.


def test_the_map_doctor_dispatches_the_grill_master_over_the_whole_board(
    log: SessionLog,
) -> None:
    """
    Given a board with a settled decision and a queued notice
    When the map doctor is called
    Then the grill-master is dispatched with image 2 whole, the pending queue,
         and the instruction to reassess everything.

    The doctor is the escape hatch when self-healing has not been enough, so it
    is given everything: a reassessment over a trimmed board would confirm
    exactly the part of the board nobody doubted.
    """
    seed(log)
    seed(log, OTHER)
    answer(log)
    notice(log, OTHER_NOTICE, OTHER)
    driver = ScriptedMap(replies=[document(text="Reassessed; d-compaction no longer follows.")])
    lane = Lane(log, driver)

    thread = lane.call_doctor()

    assert thread is not None
    thread.join(TIMEOUT)
    body = driver.dispatches[0].read_text(encoding="utf-8")
    context = driver.recorded(0)
    assert context.agent == GRILL_MASTER
    assert context.reassess is True
    # Folded independently of the dispatch, from the log as it stood when the
    # dispatch was taken: the lane announces the turn before scheduling it, so a
    # snapshot from before the call is a board one entry behind. Pinning it to
    # the recorded seq keeps this a tripwire on what crossed rather than a
    # restatement of what the dispatch says about itself.
    expected = fold(log.epoch, [one for one in log.entries() if one.seq <= context.seq])
    assert expected.model_dump_json() in body
    assert [one.id for one in context.image2.pending] == [OTHER_NOTICE]
    assert REASSESS_RULE in compose(body, context, log.entries())


def test_the_board_is_frozen_while_the_doctor_runs_and_free_when_it_lands(
    log: SessionLog,
) -> None:
    """
    Given a map-doctor turn held mid-flight
    When the turn is released and finishes
    Then the lane reports the board frozen while it was outstanding and free
         once the reply landed.

    This is the state the page holds its modal against. The backend reports it
    and does not enforce it: refusing a write would need a rejection reason, and
    that vocabulary is closed.
    """
    seed(log)
    driver = SpyDriver(hold=True)
    lane = Lane(log, driver)

    thread = lane.call_doctor()

    assert thread is not None
    assert driver.started.wait(TIMEOUT)
    assert lane.doctor_outstanding is True
    driver.release.set()
    thread.join(TIMEOUT)
    assert lane.doctor_outstanding is False


def test_a_second_doctor_call_while_one_is_outstanding_is_not_a_second_turn(
    log: SessionLog,
) -> None:
    """
    Given a map-doctor turn already outstanding
    When the doctor is called again
    Then nothing is dispatched.

    The human clicking twice on a frozen board must not put two reassessments on
    one resume chain, where the second resumes a conversation the first is still
    adding to.
    """
    seed(log)
    driver = SpyDriver(hold=True)
    lane = Lane(log, driver)
    first = lane.call_doctor()

    assert lane.call_doctor() is None

    assert first is not None
    driver.release.set()
    first.join(TIMEOUT)
    assert len(driver.dispatches) == 1


def test_a_doctor_turn_that_fails_still_gives_the_board_back(log: SessionLog) -> None:
    """
    Given a tier that cannot be reached
    When the map doctor is called
    Then the failure surfaces on the status lane and the board is free again.

    A board frozen against a turn that already failed is frozen for good, and
    the human's only way out would be to kill the session.
    """
    seed(log)
    lane = Lane(log, UnreachableDriver())

    thread = lane.call_doctor()

    assert thread is not None
    thread.join(TIMEOUT)
    assert lane.doctor_outstanding is False
    phases = [entry.payload["phase"] for entry in log.entries() if entry.kind == STATUS_KIND]
    assert STATUS_PHASE_ERROR in phases


def test_the_doctor_with_no_tier_attached_never_freezes_the_board(log: SessionLog) -> None:
    """
    Given a session with no tier configured
    When the map doctor is called
    Then nothing is dispatched and the board is never frozen.

    Freezing against an answer nobody is composing is the one failure mode the
    modal cannot recover from by waiting.
    """
    seed(log)
    lane = Lane(log)

    assert lane.call_doctor() is None
    assert lane.doctor_outstanding is False


@pytest.mark.parametrize("method", ["get", "post"])
def test_the_doctor_route_reports_whether_the_board_is_frozen(log: SessionLog, method: str) -> None:
    """
    Given a doctor turn held mid-flight
    When the page asks the doctor route
    Then it is told the board is frozen, on the call that started it and on the
         cheap read afterwards.

    The page decides whether to render its modal from this and from nothing
    else, which is why the answer comes from memory rather than from the log.
    """
    seed(log)
    driver = SpyDriver(hold=True)
    client: TestClient = driven(log, driver)

    started = client.post("/doctor")
    assert started.json() == {"outstanding": True}
    response = getattr(client, method)("/doctor")

    assert response.json() == {"outstanding": True}

    driver.release.set()
    assert driver.finished.wait(TIMEOUT)
    deadline = time.monotonic() + TIMEOUT
    while client.get("/doctor").json()["outstanding"] and time.monotonic() < deadline:
        time.sleep(0.005)
    assert client.get("/doctor").json() == {"outstanding": False}
