"""Which seat a gesture is composed on, decided off the board (GMR-A9).

The judgment classes are closed and every one of them is readable before a model
is called, which is what lets the classing decide a seat: there is no transcript
to read at that point, and a class inferred from the human's prose would be the
self-assessment the whole escalation design replaces.

So a classed gesture is composed by the expert from the start -- no first-rung
turn is recorded for it and nothing is round-tripped through a rung the class
already passed over -- and the `composing` entry names the seat that actually
takes it, which is the only thing the human has to go on while they wait.
Classing writes nothing, so the next clerical gesture is first-rung again with
no entry to undo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from conftest import decision, document, handoff, lane, option, ruling, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

STRANDED = [
    decision("d1", "Which storage?"),
    decision("d2", "How is it compacted?", prereqs=["d1"]),
    decision("d3", "What is retained?"),
]

MARKED = [
    decision(
        "d1",
        "Which storage?",
        options=[option("a", "Append-only log", ["d2", "d3"]), option("b", "Table")],
    ),
    decision("d2", "How is it compacted?"),
    decision("d3", "What is retained?"),
]


def answer(page: Page, node: str, chosen: str = "a") -> None:
    page.click(f'#col-{node} [data-act="pick"][data-opt="{chosen}"]')


def composings(session: Session) -> list[str | None]:
    """Which seat each map turn was announced on, in order."""
    return [tier for phase, tier in lane(session.entries(), "map") if phase == "composing"]


def queued(session: Session, kind: str) -> list[dict[str, Any]]:
    """The queue items of one kind waiting on the human."""
    return [one for one in session.board()["pending"] if one["kind"] == kind]


def apply_one(page: Page, uid: str) -> None:
    """Land one queued change, through the inbox the human opens to see it.

    Scoped to the overlay the inbox opens in. The same change offers the same
    control on the decision it targets, and that one is behind the overlay --
    a click aimed at it is intercepted rather than landing, which is the page
    working as intended and a scenario aiming at the wrong copy.
    """
    page.click('[data-act="inbox"]')
    page.wait_for_timeout(400)
    page.click(f'#overlay [data-act="applyone"][data-uid="{uid}"]')
    page.wait_for_timeout(400)


def open_thread(page: Page, node: str, said: str) -> None:
    page.click(f'[data-act="threads"][data-id="{node}"]')
    page.wait_for_timeout(400)
    page.fill("#ft-say", said)
    page.click('[data-act="draftsay"]')


def test_a_marked_answer_is_the_experts_and_the_next_clerical_gesture_is_not(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given an option that puts two live decisions in question, and a plain
         decision beside it
    When the human takes that option and then answers the plain decision
    Then the first gesture is announced and composed on the expert with no
         first-rung turn recorded for it, and the second is announced and
         composed on the first rung again -- the class bought one turn, not a
         session.
    """
    session = launcher(handoff=handoff(MARKED))
    session.script_claude(
        turn(
            document("Both die with it.", rulings=[ruling("d2", "stands"), ruling("d3", "stands")])
        )
    )
    session.script_codex(turn(document("Clerical.")))
    page = board(session)

    answer(page, "d1")
    session.settled()
    assert composings(session) == ["heavy"], composings(session)
    assert not session.codex_calls(), "the first rung took a turn the class passed over"

    answer(page, "d2")
    session.settled()
    assert composings(session) == ["heavy", "fast"], composings(session)
    assert len(session.claude_calls()) == 1, "the class outlived the gesture that bought it"
    assert len(session.codex_calls()) == 1, session.codex_calls()


def test_an_option_marking_only_dead_decisions_stays_clerical(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given an option marking a decision that has already been settled
    When the human takes it
    Then the gesture is clerical and stays on the first rung: a decision the
         board has stopped offering is not one the human is left answering, so
         there is nothing for the turn to rule on.
    """
    plan = [
        decision(
            "d1",
            "Which storage?",
            options=[option("a", "Append-only log", ["d2"]), option("b", "Table")],
        ),
        decision("d2", "How is it compacted?"),
    ]
    session = launcher(handoff=handoff(plan))
    session.script_codex(turn(document("First.")), turn(document("Second.")))
    page = board(session)

    # d2 is answered first, so by the time the mark resolves it names nothing
    # the board is still offering.
    answer(page, "d2")
    session.settled()
    answer(page, "d1")
    session.settled()

    assert composings(session) == ["fast", "fast"], composings(session)
    assert not session.claude_calls(), "a dead mark bought an expert turn"


def test_an_applied_invalidate_that_strands_a_dependent_buys_one_expert_turn(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a queued invalidate on a decision another one rests on
    When the human applies it
    Then the apply -- which is no message and would otherwise be answered by
         nothing -- schedules one turn, it is composed on the expert, and the
         dispatch it is given names the stranded decision and says the cause was
         the invalidate rather than an answer.
    """
    session = launcher(handoff=handoff(STRANDED))
    session.script_codex(
        turn(
            document(
                "d1 is moot.",
                updates=[{"kind": "invalidate", "target": "d1", "why": "the store is fixed"}],
            )
        )
    )
    session.script_claude(
        turn(document("d2 survives without it.", rulings=[ruling("d2", "stands")]))
    )
    page = board(session)

    answer(page, "d3")
    session.settled()
    waiting = queued(session, "invalidate")
    assert len(waiting) == 1, session.board()["pending"]

    apply_one(page, waiting[0]["id"])
    session.settled()

    assert composings(session) == ["fast", "heavy"], composings(session)
    assert len(session.claude_calls()) == 1, session.claude_calls()
    owed = [one["mootness"] for one in session.dispatches() if one.get("mootness")]
    assert owed, "no dispatch carried the obligation the apply left"
    assert owed[-1]["cause"] == "invalidate", owed[-1]
    assert owed[-1]["ids"] == ["d2"], owed[-1]
    assert owed[-1]["target"] == "d1", owed[-1]


def test_an_apply_that_strands_nobody_buys_no_turn_at_all(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a queued invalidate on a decision nothing rests on
    When the human applies it
    Then no turn is scheduled: applying is agreement, and a gesture that left
         the board offering nothing has nothing to be ruled on. This is the
         ordinary case, and it must cost no seat.
    """
    session = launcher(handoff=handoff(STRANDED))
    session.script_codex(
        turn(
            document(
                "d3 is moot.",
                updates=[{"kind": "invalidate", "target": "d3", "why": "nothing rests on it"}],
            )
        )
    )
    page = board(session)

    answer(page, "d1")
    session.settled()
    waiting = queued(session, "invalidate")
    assert len(waiting) == 1, session.board()["pending"]

    apply_one(page, waiting[0]["id"])
    session.settled()

    assert composings(session) == ["fast"], composings(session)
    assert not session.claude_calls(), "a strand-free apply bought an expert turn"
    assert len(session.codex_calls()) == 1, session.codex_calls()


def test_folding_a_thread_and_calling_the_doctor_are_both_the_experts(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a thread with something said in it
    When the human folds it, and then calls the map doctor
    Then each is announced and composed on the expert on the map channel: a
         conclusion being folded into the board and the board being reassessed
         whole are both judgements the first rung has no standing to make.

    Folding is answered on the map rather than in the thread, because the
    grill-master is the only agent that authors map mutations and a conclusion
    nobody hands it changes nothing.
    """
    session = launcher(handoff=handoff(STRANDED))
    session.stub.script("Retention is what that turns on.")
    session.script_claude(
        turn(document("Folded in.")), turn(document("Reassessed; nothing moved."))
    )
    page = board(session)

    open_thread(page, "d3", "What does retention cost?")
    session.settled()
    page.click('[data-act="fold"]')
    session.settled()

    assert composings(session) == ["heavy"], composings(session)
    assert not session.codex_calls(), "a fold was composed on the first rung"

    page.click('[data-act="doctor"]')
    session.settled()

    assert composings(session) == ["heavy", "heavy"], composings(session)
    assert len(session.claude_calls()) == 2, session.claude_calls()
    reassessed = [one for one in session.dispatches() if one.get("reassess")]
    assert len(reassessed) == 1, "the doctor's dispatch does not say it was called"
