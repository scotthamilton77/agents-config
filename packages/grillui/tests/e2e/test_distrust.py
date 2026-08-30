"""Two wordless refusals of the first rung move the channel; one is noise (GMR-A10).

Applying and dismissing carry no text, so no transcript condition sees them.
A dismissal of a first-rung proposal is the human saying wordlessly that the
seat got it wrong; the backend's own press of a refused turn onto the expert is
the same evidence about the same rung -- and the two are counted alike.

One writes nothing, because one is noise: a proposal the human simply did not
want is not a seat that cannot do the work. The second is the pattern, and it
writes the same status entry the escalation policy writes. The count is this
process's and the entry is the log's, which is the division that matters: a
successor process starts counting again, and finds the move already made.

The entry is sticky by design. A channel the human took back down stays down --
the way back is theirs -- so a third signal buys nothing, and neither does a
restart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from conftest import decision, document, handoff, lane, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

PLAN = [decision(f"d{index}", f"Question {index}?") for index in range(1, 5)]

# Three changes the first rung proposes, so there are three of its turns for the
# human to refuse without saying a word.
PROPOSES_THREE = document(
    "Three of these are moot.",
    updates=[
        {"kind": "invalidate", "target": "d2", "why": "moot"},
        {"kind": "invalidate", "target": "d3", "why": "moot"},
        {"kind": "invalidate", "target": "d4", "why": "moot"},
    ],
)

PROSE = "I do not remember the shape."


def answer(page: Page, node: str, chosen: str = "a") -> None:
    page.click(f'#col-{node} [data-act="pick"][data-opt="{chosen}"]')


def transferred(session: Session) -> list[str]:
    """Every entry saying the policy moved the map to the expert."""
    return [
        str(one.payload.get("detail"))
        for one in session.entries()
        if one.kind == "status"
        and one.channel == "map"
        and one.payload.get("phase") == "transferred"
    ]


def composings(session: Session) -> list[str | None]:
    return [tier for phase, tier in lane(session.entries(), "map") if phase == "composing"]


def queued(session: Session) -> list[dict[str, Any]]:
    return [one for one in session.board()["pending"] if one["kind"] == "invalidate"]


def dismiss(page: Page, uid: str) -> None:
    page.click('[data-act="inbox"]')
    page.wait_for_timeout(400)
    page.click(f'#overlay [data-act="dismissone"][data-uid="{uid}"]')
    page.wait_for_timeout(600)


def test_the_second_wordless_refusal_moves_the_channel_and_the_third_buys_nothing(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given three changes the first rung proposed
    When the human dismisses them one after another
    Then the first dismissal writes nothing, the second writes exactly one
         `transferred` entry naming the count as the reason, and the third
         writes nothing new -- and the human's own transfer control still takes
         the channel back down afterwards.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(PROPOSES_THREE), turn(document("Back on the first rung.")))
    page = board(session)

    answer(page, "d1")
    session.settled()
    waiting = queued(session)
    assert len(waiting) == 3, session.board()["pending"]

    dismiss(page, waiting[0]["id"])
    assert transferred(session) == [], "one refusal moved the channel"

    dismiss(page, waiting[1]["id"])
    moved = transferred(session)
    assert len(moved) == 1, moved
    assert "refused twice" in moved[0], moved[0]

    dismiss(page, waiting[2]["id"])
    assert len(transferred(session)) == 1, transferred(session)

    # The way back down is the human's, and the policy does not buy the channel
    # again after they have reversed it.
    page.wait_for_timeout(800)
    control = page.locator('[data-act="transfer"][data-channel="map"]')
    assert control.inner_text().strip().endswith("Return to fast agent"), control.inner_text()
    control.click()
    page.wait_for_timeout(300)
    answer(page, "d2")
    session.settled()

    assert composings(session)[-1] == "fast", composings(session)
    assert len(session.codex_calls()) == 2, session.codex_calls()
    assert not session.claude_calls(), "the expert took a turn on a channel handed back"


def test_a_dismissal_and_a_press_are_the_same_signal(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given one change the first rung proposed and, afterwards, a first-rung turn
         whose reply is not the reply document twice
    When the human dismisses the change and the refused turn is handed up
    Then the two count as one pattern and exactly one `transferred` entry is
         written -- the press is counted where the decision to hand up is made,
         so a seat that answered badly and one the human overruled are the same
         evidence about the same rung.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(
        turn(
            document("One is moot.", updates=[{"kind": "invalidate", "target": "d2", "why": "m"}])
        ),
        turn(PROSE),
        turn(PROSE),
    )
    session.script_claude(turn(document("The expert took it.")))
    page = board(session)

    answer(page, "d1")
    session.settled()
    dismiss(page, queued(session)[0]["id"])
    assert transferred(session) == [], "the dismissal alone moved the channel"

    answer(page, "d3")
    session.settled()

    assert len(session.codex_calls()) == 3, session.codex_calls()
    assert len(session.claude_calls()) == 1, session.claude_calls()
    assert len(transferred(session)) == 1, transferred(session)


def test_two_presses_move_the_channel_and_the_move_survives_a_fresh_backend(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given two clerical gestures whose first-rung turns are both refused twice
    When each is handed up to the expert, and then the backend is replaced by a
         fresh one over the same session directory
    Then the two presses write exactly one `transferred` entry, and the new
         process finds the map already moved: the next gesture is composed on
         the expert without any signal being counted, because the entry is in
         the log rather than in the memory of the process that wrote it.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(PROSE), turn(PROSE), turn(PROSE), turn(PROSE))
    session.script_claude(turn(document("First press.")), turn(document("Second press.")))
    page = board(session)

    answer(page, "d1")
    session.settled()
    assert transferred(session) == [], "one press moved the channel"

    answer(page, "d2")
    session.settled()
    assert len(transferred(session)) == 1, transferred(session)
    assert len(session.codex_calls()) == 4, session.codex_calls()

    # A fresh tenure over the same directory. Its counter starts at nothing --
    # what survives is the entry, which is what it reads before writing another.
    session.close()
    resumed = launcher(name="session")
    # The script is stated whole rather than appended to: the shims record every
    # call the directory ever took, across tenures, and read their turn index off
    # that record -- which is the same thing the resume chain does and for the
    # same reason. A fresh tenure is not a fresh conversation.
    resumed.script_claude(
        turn(document("First press.")),
        turn(document("Second press.")),
        turn(document("Still the expert's.")),
    )
    page = board(resumed)

    answer(page, "d3")
    resumed.settled()

    assert composings(resumed)[-1] == "heavy", composings(resumed)
    # Three expert calls over the directory's whole life: the two presses of the
    # first tenure and this one. The record spans tenures because the directory
    # does.
    assert len(resumed.claude_calls()) == 3, resumed.claude_calls()
    assert len(resumed.codex_calls()) == 4, "a restarted backend put the moved channel back"
    assert len(transferred(resumed)) == 1, transferred(resumed)
