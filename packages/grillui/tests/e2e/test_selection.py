"""What a re-render is allowed to take away from the human.

The board re-renders on a timer: the poll brings entries in and the page draws
the board again, replacing every node on it. Two things the human is holding at
that moment are theirs and not the board's -- the text they have selected, and
the caret they are typing with. Both were being thrown away, and the second one
landed in a box they had not asked for, so a human reading a notice found their
selection gone and their keystrokes going into an answer.

Driven from outside the page on purpose. Every gesture on the board is itself a
re-render, so a scenario that clicked something to make entries arrive would be
proving what a click does; the map doctor is called over HTTP instead and the
page finds the entries the way it finds all of them, on its next poll.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conftest import RENDER, decision, document, handoff, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

PLAN = [decision("d1", "Which storage?"), decision("d2", "How is it compacted?")]

# Long enough to drag a mouse across, and about the decision it is put on, so it
# renders on that decision's block where the human is reading it.
NOTICED = (
    "The store choice leaves recovery resting on compaction, and nothing on this "
    "board has yet said what compaction drops or how long it keeps what it keeps."
)
SAID = document(text="", updates=[{"kind": "informational", "target": "d1", "text": NOTICED}])
# The doctor's rounds. They say nothing about d1, so the block the selection is
# in is the same block afterwards and the only thing that moved is the log.
LOOKED = document(text="Nothing on the board has changed.")

TYPED = "Does the retention window decide it?"
CARET = 6


def notice(page: Page) -> dict[str, float]:
    """Where the notice on d1 is drawn, to drag a mouse across."""
    found = page.locator("#col-d1 .infonote").last.bounding_box()
    assert found, "the notice is not on the board"
    return found


def select_across(page: Page, box: dict[str, float]) -> str:
    """Drag a selection across the middle of an element, and say what it caught."""
    middle = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + 20, middle)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] - 20, middle, steps=8)
    page.mouse.up()
    page.wait_for_timeout(RENDER)
    return str(page.evaluate("document.getSelection().toString()"))


def polled(session: Session, page: Page) -> None:
    """One round of entries, landed from outside and waited for on the page."""
    session.call_doctor()
    session.settled()
    page.wait_for_timeout(RENDER)


def test_a_poll_leaves_the_selection_the_human_is_holding_alone(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a notice on the board with text selected across it by a mouse
    When two polls bring new entries in and the board is drawn again for each
    Then the selection is the same words it was, and the caret is in no answer
         box -- neither the mouse-up that made the selection nor either render
         took one.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(SAID), turn(LOOKED), turn(LOOKED))
    page = board(session)

    # An answer, so the notice the grill-master writes on d1 is on the board --
    # and so the advance has already put the caret in an answer box, which is
    # the caret the selection then has to take away from it.
    page.click('#col-d2 [data-act="pick"][data-opt="a"]')
    session.settled()
    page.wait_for_timeout(RENDER)

    selected = select_across(page, notice(page))
    assert selected.strip(), "nothing was selected to hold"
    # A run of the notice as it is drawn -- the drag crosses whatever the line
    # under the mouse holds, which is the notice's words and the stamp after
    # them.
    drawn = page.evaluate("document.querySelector('#col-d1 .infonote').textContent")
    assert selected in drawn, selected

    polled(session, page)
    polled(session, page)

    assert page.evaluate("document.getSelection().toString()") == selected
    where = page.evaluate("document.activeElement.id")
    assert not str(where).startswith("ft-"), f"a render took the caret into {where}"


def test_a_poll_leaves_the_caret_where_the_human_is_typing(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given text typed into a thread's say box with the caret partway through it
    When a poll brings new entries in and the board is drawn again
    Then the box still has the caret, at the same position, over the same text.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(LOOKED))
    page = board(session)

    page.click('#col-d2 [data-act="newthread"][data-id="d2"]')
    page.wait_for_timeout(RENDER)
    page.fill("#ft-say", TYPED)
    page.evaluate(
        "at => { const box = document.getElementById('ft-say');"
        " box.focus(); box.setSelectionRange(at, at); }",
        CARET,
    )

    polled(session, page)

    assert page.evaluate("document.activeElement.id") == "ft-say"
    assert page.evaluate("document.getElementById('ft-say').value") == TYPED
    assert page.evaluate("document.getElementById('ft-say').selectionStart") == CARET
