"""What an impact task's result may touch, and what an empty revise may not.

A marked answer sends the expert to rule on the decisions it puts in question.
What that ruling changes on its own target lands without the human's apply, and
the history it leaves names the task that changed it. Anything it reaches past
that target -- another decision, a new one -- waits in the inbox for the human.

A revise is a structural change or it is nothing. One that supplies no
structural field would unlock its target while claiming to have changed it, so
the document gate refuses it, and says where a disagreement with no change
behind it belongs instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from conftest import TIMEOUT, ScriptedCli, SpyDriver, document, event, post, proposed, run_turns

from grillui.drivers import HeavyDriver, document_problem, read_document, record_document
from grillui.lane import Lane
from grillui.projector import replay, to_image1
from grillui.schemas import DispatchContext, EventSubmission, Image2, LogEntry
from grillui.session import open_session
from grillui.tiers import TierConfig

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient

    from grillui.log import SessionLog

MARKS_D2 = {"id": "b", "text": "Rebuild it", "puts_in_question": ["d2"]}
MARKS_BOTH = {"id": "d", "text": "Replace it", "puts_in_question": ["d2", "d3"]}
PLAIN = [{"id": "a", "text": "Yes"}, {"id": "c", "text": "No"}]
STRUCTURAL = ("short", "title", "body", "prereqs", "options")
NEW_TITLE = "Which d2, now that it is rebuilt?"


def _seed(log: SessionLog) -> None:
    """d1's option b marks d2 and its option d marks d2 and d3. Nothing else
    marks anything."""
    for node, options in (
        ("d1", [PLAIN[0], MARKS_D2, MARKS_BOTH]),
        ("d2", PLAIN),
        ("d3", PLAIN),
        ("d4", PLAIN),
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


def _lane(log: SessionLog, reply: str) -> tuple[Lane, ScriptedCli]:
    """A lane whose expert seat answers every turn it is given with this
    document, and whose first rung is never asked anything."""
    cli = ScriptedCli(reply=reply)
    return Lane(log, SpyDriver(), HeavyDriver(TierConfig.from_env({}), cli)), cli


def _task_of(log: SessionLog, target: str) -> str:
    gesture = next(
        one.seq for one in log.entries() if one.kind == "answer" and one.payload["target"] == "d1"
    )
    return f"impact-{gesture}-{target}"


def _node(log: SessionLog, node_id: str) -> Any:
    return next(one for one in replay(log.epoch, log.entries()).decisions if one.id == node_id)


def _queued(log: SessionLog) -> set[tuple[str, str | None]]:
    return {(one.kind, one.target) for one in replay(log.epoch, log.entries()).pending}


# --- a result on its own target lands, naming the task ------------------------


def test_pnd_a4_a_result_revising_its_own_target_lands_and_names_the_task(
    log: SessionLog,
) -> None:
    """
    Given d1's option b marks d2, and an expert seat that revises d2's title
    When the human takes that option and the ruling lands
    Then d2 carries the new title without any apply, its history line for the
         revise names the impact task in `task` and carries no `proposed_by`,
         nothing waits in the inbox on d2, and d2 is back on the frontier.
    """
    _seed(log)
    lane, _ = _lane(
        log,
        document(
            "",
            updates=[{"kind": "revise", "target": "d2", "title": NEW_TITLE}],
            rulings=[{"decision": "d2", "ruling": "revise", "why": "b rebuilds it"}],
        ),
    )

    run_turns(lane, _answer("d1"))

    image = replay(log.epoch, log.entries())
    assert _node(log, "d2").title == NEW_TITLE
    revised = [one for one in image.history["d2"] if one.kind == "revise"]
    assert len(revised) == 1, image.history["d2"]
    recorded = revised[0].model_dump()
    assert recorded["task"] == _task_of(log, "d2"), recorded
    assert "proposed_by" not in recorded, recorded
    assert not [one for one in image.pending if one.target == "d2"], image.pending
    assert "d2" in image.frontier


def test_pnd_a4_a_result_invalidating_its_own_target_lands_without_the_human(
    log: SessionLog,
) -> None:
    """
    Given d1's option b marks d2, and an expert seat that rules d2 invalidated
    When the human takes that option and the ruling lands
    Then d2 is invalidated with no apply, and its history names the task.

    An agent's invalidate always waits for the human anywhere else; the target
    of the task weighing it is the one exception.
    """
    _seed(log)
    lane, _ = _lane(
        log,
        document(
            "",
            updates=[{"kind": "invalidate", "target": "d2", "why": "b leaves nothing to ask"}],
            rulings=[{"decision": "d2", "ruling": "invalidate", "why": "b leaves nothing to ask"}],
        ),
    )

    run_turns(lane, _answer("d1"))

    image = replay(log.epoch, log.entries())
    assert _node(log, "d2").status == "invalidated"
    assert ("invalidate", "d2") not in _queued(log)
    assert [one.task for one in image.history["d2"] if one.kind == "invalidate"] == [
        _task_of(log, "d2")
    ]


def test_pnd_a4_a_result_reaching_past_its_target_waits_in_the_inbox(log: SessionLog) -> None:
    """
    Given d1's option b marks d2 alone, and an expert seat that rules d2
         standing while revising d3, which nobody has answered, and adding a node
    When the human takes that option and the ruling lands
    Then the revise of d3 and the new node both wait in the inbox, d3 keeps its
         title, and the new node is not on the board.
    """
    _seed(log)
    lane, _ = _lane(
        log,
        document(
            "",
            updates=[
                {"kind": "revise", "target": "d3", "title": "Which d3, after the rebuild?"},
                {
                    "kind": "add-node",
                    "title": "Who runs the rebuild?",
                    "options": [{"id": "a", "text": "Us"}, {"id": "b", "text": "Them"}],
                },
            ],
            rulings=[{"decision": "d2", "ruling": "stands", "why": "asked either way"}],
        ),
    )

    run_turns(lane, _answer("d1"))

    queued = _queued(log)
    assert ("revise", "d3") in queued, queued
    assert any(kind == "add-node" for kind, _ in queued), queued
    assert _node(log, "d3").title == "Which d3?"
    assert {one.id for one in replay(log.epoch, log.entries()).decisions} == {
        "d1",
        "d2",
        "d3",
        "d4",
    }


def test_pnd_a4_a_turn_carrying_no_task_lands_what_it_always_did(log: SessionLog) -> None:
    """
    Given a map turn that carries no impact task
    When it revises a decision nobody has answered and adds a node
    Then both land as an agent's update always has, and the history line names
         no task.
    """
    _seed(log)
    turn = read_document(
        document(
            "",
            updates=[
                {"kind": "revise", "target": "d3", "title": "Which d3, really?"},
                {
                    "kind": "add-node",
                    "title": "Who runs it?",
                    "options": [{"id": "a", "text": "Us"}, {"id": "b", "text": "Them"}],
                },
            ],
        )
    )

    with log.appending():
        record_document(log, "heavy", turn, {})

    image = replay(log.epoch, log.entries())
    assert _node(log, "d3").title == "Which d3, really?"
    assert not image.pending
    assert all("task" not in one.model_dump() for one in image.history["d3"])


def test_pnd_a4_a_result_entry_recorded_without_its_tasks_replays_as_it_always_did(
    log: SessionLog,
) -> None:
    """
    Given a marked answer whose task on d2 is live, and an entry recorded the
         way a turn's result was before entries named their tasks -- an
         invalidate of d2 with no `tasks` key
    When the log is replayed
    Then the invalidate waits in the inbox as an agent's invalidate always did,
         and d2's history names no task: a log recorded before the key replays
         unchanged.
    """
    _seed(log)
    seat = SpyDriver(tier="heavy", hold=True)
    _, turns = Lane(log, seat).accept([_answer("d1")], log.epoch)
    assert seat.started.wait(TIMEOUT)
    older = read_document(
        document(
            "",
            updates=[{"kind": "invalidate", "target": "d2", "why": "moot"}],
            rulings=[{"decision": "d2", "ruling": "invalidate", "why": "moot"}],
        )
    )

    with log.appending():
        record_document(log, "heavy", older, {})
    seat.release.set()
    for one in turns:
        one.join(TIMEOUT)

    assert not any("tasks" in one.payload for one in log.entries() if one.kind == "fold")
    assert ("invalidate", "d2") in _queued(log)
    assert _node(log, "d2").status == "open"
    history = replay(log.epoch, log.entries()).history.get("d2", [])
    assert all(one.task is None for one in history), history


def _die_after_landing(
    session_dir: Path, log: SessionLog, option: str, landed: list[str]
) -> tuple[Image2, list[LogEntry]]:
    """A marked answer whose turn lands a result for the tasks on `landed` and
    whose process dies before the turn's closing entry, then a fresh backend
    over the same directory: the board that backend replays, and the entries it
    wrote on opening.

    The result is recorded through the real recorder, naming the tasks it is
    the result of, while the turn is still held open; the restart happens
    before the turn is released, which is the crash between the two appends.
    """
    _seed(log)
    seat = SpyDriver(tier="heavy", hold=True)
    _, turns = Lane(log, seat).accept([_answer("d1", option)], log.epoch)
    assert seat.started.wait(TIMEOUT)
    context = DispatchContext.model_validate_json(seat.dispatches[0].read_text("utf-8"))
    result = read_document(
        document(
            "",
            updates=[
                {"kind": "revise", "target": one, "title": f"{one}, rebuilt"} for one in landed
            ],
            rulings=[{"decision": one, "ruling": "revise", "why": "rebuilt"} for one in landed],
        )
    )
    with log.appending():
        record_document(
            log,
            "heavy",
            result,
            {},
            context.mootness,
            [one for one in context.tasks if one.rsplit("-", 1)[1] in landed],
        )

    successor = open_session(session_dir)
    written = [one for one in successor.entries() if one.epoch == successor.epoch]
    image = replay(successor.epoch, successor.entries())
    seat.release.set()
    for one in turns:
        one.join(TIMEOUT)
    return image, written


def _closings(written: list[LogEntry]) -> list[LogEntry]:
    return [
        one
        for one in written
        if one.kind == "status" and one.payload.get("phase") in {"replied", "error"}
    ]


def test_pnd_a4_a_restart_after_a_result_landed_closes_its_task_as_replied(
    session_dir: Path, log: SessionLog
) -> None:
    """
    Given d1's marked answer, whose turn landed its result revising d2 and
         whose process died before writing the turn's closing entry
    When a fresh backend opens the same directory
    Then it writes one closing entry for that turn, `replied`, naming d2's task
         as replied; d2 carries its new title, waits on nothing and is back on
         the frontier, exactly as if the process had lived to close the turn.
    """
    image, written = _die_after_landing(session_dir, log, "b", ["d2"])

    closings = _closings(written)
    assert len(closings) == 1, closings
    assert closings[0].payload["phase"] == "replied", closings[0].payload
    assert [item["phase"] for item in closings[0].payload["tasks"]] == ["replied"]
    d2 = next(one for one in image.decisions if one.id == "d2")
    assert d2.title == "d2, rebuilt"
    assert d2.waiting is None
    assert "d2" in image.frontier


def test_pnd_a4_a_restart_fails_only_the_task_whose_result_never_landed(
    session_dir: Path, log: SessionLog
) -> None:
    """
    Given d1's answer marking d2 and d3, whose turn's entry on the log names
         d2's task as its result and not d3's, and whose process then died
    When a fresh backend opens the same directory
    Then its one closing entry for the turn names d2's task replied and d3's
         failed: d2 is free and changed, and d3 still waits on its failed task.
    """
    image, written = _die_after_landing(session_dir, log, "d", ["d2"])

    closings = _closings(written)
    assert len(closings) == 1, closings
    phases = {item["id"].rsplit("-", 1)[1]: item["phase"] for item in closings[0].payload["tasks"]}
    assert phases == {"d2": "replied", "d3": "error"}, closings[0].payload
    by_id = {one.id: one for one in image.decisions}
    assert by_id["d2"].waiting is None
    assert by_id["d2"].title == "d2, rebuilt"
    assert by_id["d3"].waiting is not None
    assert "d3" not in image.frontier


# --- the empty revise ---------------------------------------------------------


def test_pnd_a4_a_revise_supplying_no_structural_field_is_refused_at_the_document_gate() -> None:
    """
    Given a map document whose only update is a revise carrying a target and a
         why and nothing it would change
    When the document gate judges it
    Then it is refused, the fault names every structural field a revise may
         supply, and it says a why with no change behind it is an informational.
    """
    fault = document_problem(
        document("", updates=[{"kind": "revise", "target": "d2", "why": "I disagree"}])
    )

    assert fault is not None
    assert fault.startswith("updates.0:"), fault
    for name in STRUCTURAL:
        assert f"`{name}`" in fault, (name, fault)
    assert "informational" in fault, fault


def test_pnd_a4_an_empty_revise_never_reaches_the_inbox_and_its_retry_quotes_the_fault(
    log: SessionLog,
) -> None:
    """
    Given an expert seat that answers a marked answer's ruling with an empty
         revise on d2, every time it is asked
    When the human takes the option and the ladder runs out
    Then the retry the seat was given quotes the structural set, no revise is
         queued, and d2's title is what it was.
    """
    _seed(log)
    lane, cli = _lane(
        log,
        document(
            "",
            updates=[{"kind": "revise", "target": "d2", "why": "I disagree with the answer"}],
            rulings=[{"decision": "d2", "ruling": "revise", "why": "I disagree"}],
        ),
    )

    run_turns(lane, _answer("d1"))

    assert len(cli.calls) == 2, cli.calls
    retried = " ".join(cli.calls[1])
    assert "`prereqs`" in retried, retried
    assert "informational" in retried, retried
    assert ("revise", "d2") not in _queued(log)
    assert _node(log, "d2").title == "Which d2?"


def test_pnd_a4_a_revise_supplying_only_prereqs_is_a_structural_change(log: SessionLog) -> None:
    """
    Given an expert seat whose ruling revises d2's prereqs and nothing else
    When the document gate judges it, and the ruling lands
    Then the gate takes it, and d2 rests on d3 afterwards.
    """
    reply = document(
        "",
        updates=[{"kind": "revise", "target": "d2", "prereqs": ["d3"]}],
        rulings=[{"decision": "d2", "ruling": "revise", "why": "it needs d3 first"}],
    )
    assert document_problem(reply) is None
    _seed(log)
    lane, _ = _lane(log, reply)

    run_turns(lane, _answer("d1"))

    assert _node(log, "d2").prereqs == ["d3"]


# --- the preference leaves no mark on the replay ------------------------------


def test_pnd_a12_an_apply_made_by_the_preference_replays_as_the_same_board(
    log: SessionLog,
) -> None:
    """
    Given a revise queued on d3 by a turn that also invalidated it
    When the human's apply lands carrying `by_preference: true`
    Then image 1 replayed from that log is the image replayed from the same log
         with the marker stripped: the apply is all the board ever sees.
    """
    _seed(log)
    queued = log.submit(
        [
            EventSubmission(
                kind="invalidate",
                actor="grill-master",
                idempotency_key="proposal",
                payload={"target": "d3", "why": "moot"},
            )
        ],
        log.epoch,
    )[0]
    assert queued.status == "accepted"
    applied = log.submit(
        [
            EventSubmission(
                kind="apply",
                actor="human",
                idempotency_key="auto",
                payload={"pending": ["proposal"], "by_preference": True},
            )
        ],
        log.epoch,
    )[0]
    assert applied.status == "accepted"

    entries = log.entries()
    stripped = [
        LogEntry.model_validate(
            {
                **one.model_dump(),
                "payload": {k: v for k, v in one.payload.items() if k != "by_preference"},
            }
        )
        for one in entries
    ]
    assert entries[-1].payload["by_preference"] is True
    assert to_image1(replay(log.epoch, entries)) == to_image1(replay(log.epoch, stripped))
    assert _node(log, "d3").status == "invalidated"


def test_pnd_a12_the_api_accepts_an_apply_the_preference_made(
    log: SessionLog, client: TestClient
) -> None:
    """
    Given an agent's invalidate of d3 waiting in the queue
    When the page posts the apply its switch makes -- the ids and
         `by_preference: true` -- to the write route the page itself uses
    Then the route accepts it, the entry on the log carries the marker, and
         the invalidate lands.

    Pinned at the boundary rather than left to the browser scenario, because
    the payload shape the route validates against is where a refusal would be.
    """
    _seed(log)
    post(client, log.epoch, event("invalidate", key="proposal", target="d3", why="moot"))
    waiting = proposed(client, "d3")
    assert len(waiting) == 1

    receipts = post(
        client,
        log.epoch,
        event("apply", actor="human", key="auto", pending=waiting, by_preference=True),
    )

    assert receipts[0]["status"] == "accepted", receipts
    assert log.entries()[-1].payload["by_preference"] is True
    assert _node(log, "d3").status == "invalidated"
