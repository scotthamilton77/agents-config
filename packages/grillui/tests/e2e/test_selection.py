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

# Where the notice's own words are drawn: the widest line of the text run
# carrying them, which is not the box of the notice. The notice also holds a
# stamp and a row of buttons, and a drag across the notice's vertical middle
# lands on whichever of those the wrapping put there -- on a loaded machine the
# words wrap differently and the middle line is the buttons. The widest line
# rather than the first, because the first may be the tail end of a line the
# tier label filled, too narrow to drag across.
WORDS = """([selector, words]) => {
  const note = document.querySelector(selector);
  const walker = document.createTreeWalker(note, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const at = node.data.indexOf(words);
    if (at < 0) continue;
    const range = document.createRange();
    range.setStart(node, at);
    range.setEnd(node, at + words.length);
    let line = null;
    for (const drawn of range.getClientRects()) {
      if (!line || drawn.width > line.width) line = drawn;
    }
    return line && {x: line.x, y: line.y, width: line.width, height: line.height};
  }
  return null;
}"""

# What the selection's two ends sit in. A selection is a run of text between an
# anchor and a focus, and the words it holds are the words of whatever nodes
# those are -- so a selection whose ends are both in the notice's own text node
# is a selection of the notice, and one whose end is in a button label is not,
# however much the two happen to share.
ENDS = """() => {
  const sel = document.getSelection();
  return [sel.anchorNode, sel.focusNode].map(n => n && n.textContent);
}"""

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
    """Drag a selection across the first drawn line of the notice's words on d1,
    in one direction or the other."""
    box = page.evaluate(WORDS, ["#col-d1 .infonote", NOTICED[:24]])
    assert box, "the notice's words are not drawn on the board"
    assert box["width"] > 40, f"the words' widest line is too narrow to drag across: {box}"
    middle = box["y"] + box["height"] / 2
    # A quarter in from either end, so the two are ordered whatever the width.
    ends = [box["x"] + box["width"] / 4, box["x"] + box["width"] * 3 / 4]
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
    # Waited for with its words on it. The board image and the log arrive on
    # two fetches, and a notice drawn between them shows a placeholder for its
    # text until the log catches up; a selection made across that placeholder
    # is over other words than the ones the next render draws.
    page.wait_for_selector(f'#col-d1 .infonote:has-text("{NOTICED[:24]}")')

    held = select_across(page, backwards)
    assert held["text"], "nothing was selected to hold"
    # The notice's own words, and only those: a drag that crossed the stamp or
    # the button row instead is the wrong selection to hold, and it is named
    # here rather than after the polls. Both ends of the selection sit in the
    # text node carrying the notice, which is what rules out a button label
    # that happens to share a few letters with it.
    assert str(held["text"]) in NOTICED, f"the drag captured {held['text']!r}"
    ends = page.evaluate(ENDS)
    assert all(NOTICED in str(one) for one in ends), f"the selection's ends are in {ends!r}"
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
