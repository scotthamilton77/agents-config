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

Waited for on the page's own reading of the log rather than on a clock. Each
round is a notice the page has to draw, so the wait ends on the page having
drawn the entries rather than on a duration that is either too long or, on a
loaded machine, a passing scenario that proved nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from conftest import decision, document, handoff, turn

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

# The doctor's rounds, which the expert seat takes rather than the map's own.
# Each one writes on d2, so the block the selection is in is untouched, and each
# says something different so a scenario waiting for the second round cannot be
# answered by the first.
ROUNDS = ["Compaction is still unspecified.", "The retention window is still unspecified."]


def looked(said: str) -> str:
    return document(text="", updates=[{"kind": "informational", "target": "d2", "text": said}])


TYPED = "Does the retention window decide it?"
CARET = 6

# Whether the selection runs the way it was made: a range from the anchor to the
# focus collapses when the focus is the earlier of the two, which is a selection
# dragged right to left.
DIRECTION = """() => {
  const sel = document.getSelection();
  const probe = document.createRange();
  probe.setStart(sel.anchorNode, sel.anchorOffset);
  probe.setEnd(sel.focusNode, sel.focusOffset);
  return {text: sel.toString(), backwards: probe.collapsed};
}"""


def selection(page: Page) -> dict[str, object]:
    """What is selected on the page, and which way round it runs."""
    held: dict[str, object] = page.evaluate(DIRECTION)
    return held


def select_across(page: Page, backwards: bool) -> dict[str, object]:
    """Drag a selection across the notice on d1, in one direction or the other."""
    box = page.locator("#col-d1 .infonote").last.bounding_box()
    assert box, "the notice is not on the board"
    middle = box["y"] + box["height"] / 2
    ends = [box["x"] + 20, box["x"] + box["width"] - 20]
    start, finish = (ends[1], ends[0]) if backwards else (ends[0], ends[1])
    page.mouse.move(start, middle)
    page.mouse.down()
    page.mouse.move(finish, middle, steps=8)
    page.mouse.up()
    return selection(page)


def polled(session: Session, page: Page, said: str) -> None:
    """One round of entries, landed from outside and waited for on the page.

    Two waits, because the cursor and the board move at different moments: the
    cursor says the poll has read the entries, and the notice they carry says
    the render that followed has drawn them.
    """
    session.call_doctor()
    session.settled()
    landed = session.entries()[-1].seq
    page.wait_for_function("at => window.WIRE && WIRE.cursor >= at", arg=landed)
    page.wait_for_selector(f'#col-d2 .infonote:has-text("{said}")')


@pytest.mark.parametrize("backwards", [False, True])
def test_a_poll_leaves_the_selection_the_human_is_holding_alone(
    backwards: bool, launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a notice on the board with text selected across it by a mouse, dragged
          left to right in one run of this and right to left in the other
    When two polls bring new entries in and the board is drawn again for each
    Then the selection is the same words running the same way, and the caret is
         in no answer box -- neither the mouse-up that made the selection nor
         either render took one.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(SAID))
    session.script_claude(turn(looked(ROUNDS[0])), turn(looked(ROUNDS[1])))
    page = board(session)

    # An answer, so the notice the grill-master writes on d1 is on the board --
    # and so the advance has already put the caret in an answer box, which is
    # the caret the selection then has to take away from it.
    page.click('#col-d2 [data-act="pick"][data-opt="a"]')
    session.settled()
    page.wait_for_selector("#col-d1 .infonote")

    held = select_across(page, backwards)
    assert held["text"], "nothing was selected to hold"
    # A run of the notice as it is drawn -- the drag crosses whatever the line
    # under the mouse holds, which is the notice's words and the stamp after
    # them.
    drawn = page.evaluate("document.querySelector('#col-d1 .infonote').textContent")
    assert held["text"] in drawn, held
    assert held["backwards"] is backwards, "the drag did not make the selection it was asked for"

    polled(session, page, ROUNDS[0])
    polled(session, page, ROUNDS[1])

    assert selection(page) == held
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
    session.script_claude(turn(looked(ROUNDS[0])))
    page = board(session)

    page.click('#col-d2 [data-act="newthread"][data-id="d2"]')
    page.wait_for_selector("#ft-say")
    page.fill("#ft-say", TYPED)
    page.evaluate(
        "at => { const box = document.getElementById('ft-say');"
        " box.focus(); box.setSelectionRange(at, at); }",
        CARET,
    )

    polled(session, page, ROUNDS[0])

    assert page.evaluate("document.activeElement.id") == "ft-say"
    assert page.evaluate("document.getElementById('ft-say').value") == TYPED
    assert page.evaluate("document.getElementById('ft-say').selectionStart") == CARET
