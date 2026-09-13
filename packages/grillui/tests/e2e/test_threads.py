"""What a thread is, and what its agent is handed (GMR-A7, GUI-D47).

Four threads with four kinds are opened here, and the fact under test is the
same in all of them: the material about *driving the board* crosses to the help
thread and to no other kind. Anchoring no decision is deliberately not the test.
The map thread anchors none either and is about the plan, and a thread opened
from a notice that targeted nothing anchors none while being about what that
notice said -- so the rule is stated positively on the kind, which is what stops
a kind added later from inheriting the material by saying nothing.

The legend is the other half of what a thread agent is given. It is a property
of the role rather than of the channel, so it rides the standing brief every
thread turn carries -- including the sentence about `proposed_by` and `verdict`,
without which an agent asked why the board moved composes a cause out of
`prereqs` while the actual rationale sits unquoted in the same bytes.

The third scenario is what a thread agent is handed when the human comes back to
a thread they had parked: the thread itself, opened again by their turn, and the
catch-up telling its seat what the board did while it was away.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from conftest import BOARD_TIMEOUT, RENDER, decision, document, handoff, turn

from grillui.tiers import BOARD_LEGEND

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

PLAN = [decision("d1", "Which storage?"), decision("d2", "How is it compacted?")]

REFERENCE = "Park a thread to set it aside; folding hands its conclusion to the map agent."
NOTICED = "The store choice leaves recovery resting on compaction."

# One turn that puts both a notice and a proposal on d1, so there is one of each
# for the human to open a thread from.
SAID = document(
    text="",
    updates=[
        {"kind": "informational", "target": "d1", "text": NOTICED},
        {"kind": "invalidate", "target": "d1", "why": "the store makes this moot"},
    ],
)

# The parked thread's conversation: what the human asked before parking it, what
# the seat said, and what they asked on coming back to it.
PARKED_ASKED = "How long does a session have to be kept?"
PARKED_REPLY = "Thirty days, then it is archived."
PICKED_UP = "And what archives it?"
PICKED_UP_REPLY = "Whatever the compaction job is, which d2 now names."


def waiting(session: Session, kind: str) -> str:
    """The id of the one queue item of this kind."""
    found = [one for one in session.board()["pending"] if one["kind"] == kind]
    assert len(found) == 1, session.board()["pending"]
    return str(found[0]["id"])


def say(page: Page, text: str) -> None:
    page.fill("#ft-say", text)
    page.click('[data-act="draftsay"]')
    page.wait_for_timeout(600)


def say_again(page: Page, text: str) -> None:
    """Say the next thing in the thread the panel is already showing.

    A different control from the one that opened it: `draftsay` starts a thread
    that does not exist yet, and once it does the same box sends into it.
    """
    page.fill("#ft-say", text)
    page.click('[data-act="say"]')
    page.wait_for_timeout(600)


def thread_id(session: Session) -> str:
    """The channel the human's thread was opened on, off the log."""
    opened = [one for one in session.entries() if one.kind == "thread-created"]
    assert opened, "no thread was created"
    return str(opened[0].channel)


def threads_of(session: Session) -> dict[str, dict[str, Any]]:
    return {one["id"]: one for one in session.image2()["threads"]}


def dispatched(session: Session) -> dict[str, dict[str, Any]]:
    """The last context each channel's agent was given."""
    return {one["channel"]: one for one in session.dispatches()}


def test_only_the_help_thread_is_handed_the_material_about_driving_the_board(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a session briefed with reference material about the board
    When the human opens a thread from a notice on a decision, a thread from a
         change waiting on that decision, the thread about the map itself, and
         the help thread
    Then the notice thread is kinded `notice` and anchored to the decision the
         notice targeted, the map thread anchors nothing, none of the three
         carries the reference material, and the help thread -- which anchors
         nothing either -- carries it.
    """
    session = launcher(handoff=handoff(PLAN, help_reference=REFERENCE))
    session.script_codex(turn(SAID))
    session.stub.script("On the notice.", "On the change.", "On the map.", "On the board itself.")
    page = board(session)

    page.click('#col-d2 [data-act="pick"][data-opt="a"]')
    session.settled()

    # A thread from the notice, opened where the human meets it: on the decision
    # it was addressed to. The notifications panel offers the same gesture over
    # the log's notification stream, which numbers its items separately from the
    # queue these ids come from.
    page.click('[data-act="toggle"][data-id="d1"]')
    page.wait_for_timeout(400)
    page.click(
        f'#col-d1 [data-act="discussnotice"][data-uid="{waiting(session, "informational")}"]'
    )
    page.wait_for_timeout(600)
    session.settled()

    # A thread from the change waiting on that same decision.
    page.click('[data-act="inbox"]')
    page.wait_for_timeout(400)
    page.click(f'#overlay [data-act="discuss"][data-uid="{waiting(session, "invalidate")}"]')
    page.wait_for_timeout(600)
    session.settled()

    # The thread about the map itself, and the one about the board.
    page.click('[data-act="mapthread"]')
    page.wait_for_timeout(400)
    say(page, "Change d2 to ask about retention instead.")
    session.settled()
    page.click('[data-act="help"]')
    page.wait_for_timeout(400)
    say(page, "What does folding a thread do?")
    session.settled()

    opened = threads_of(session)
    kinds = {one["kind"]: one for one in opened.values()}
    assert set(kinds) == {"notice", "pending", "map", "help"}, sorted(kinds)
    assert kinds["notice"]["decision"] == "d1", kinds["notice"]
    assert kinds["pending"]["decision"] == "d1", kinds["pending"]
    assert kinds["map"]["decision"] is None, kinds["map"]
    assert kinds["help"]["decision"] is None, kinds["help"]

    # The material crosses to one kind and to no other, whether or not the
    # thread anchors a decision.
    given = dispatched(session)
    for kind in ("notice", "pending", "map"):
        channel = kinds[kind]["id"]
        assert given[channel]["help_reference"] is None, f"{kind} was handed the board's manual"
    assert given[kinds["help"]["id"]]["help_reference"] == REFERENCE, given[kinds["help"]["id"]]
    assert given["map"]["help_reference"] is None, "the grill-master was handed the board's manual"


def test_every_thread_turn_is_briefed_with_the_legend_that_says_who_proposed_a_move(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a thread on a decision
    When its agent takes a turn
    Then the standing brief it was sent carries the board legend, and the glossary
         definitions it leans on: that a `history` entry names who proposed the
         change and what was judged -- so an agent asked why the board moved
         quotes the record rather than inferring a cause from the shape of the
         graph.

    The fields are defined once, in the baseline both roles read, because the
    grill-master is handed the same board and a field defined for one seat and
    left blank for the other is the same defect twice.
    """
    session = launcher(handoff=handoff(PLAN))
    session.stub.script("Retention is what that turns on.")
    page = board(session)

    page.click('[data-act="threads"][data-id="d1"]')
    page.wait_for_timeout(400)
    say(page, "Why did the board move here?")
    session.settled()

    assert len(session.stub.calls) == 1, session.stub.calls
    brief = session.stub.system_of(0)
    assert BOARD_LEGEND in brief, brief
    assert "quoting the decision's `rationale` or an entry of its `history`" in brief
    assert "`proposed_by` where an agent's queued change was applied" in brief
    assert "`verdict` where one was judged" in brief
    assert "no `proposed_by` and no `verdict` is a move nobody proposed and nobody judged" in brief


def test_a_parked_thread_is_picked_back_up_and_its_seat_is_told_what_it_missed(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a thread the human parked, and a decision they settled afterwards
    When they open that thread from the board and say something in it
    Then the thread is open again and the seat's reply lands on it, and the
         dispatch that produced that reply carries a catch-up naming the
         decision that moved while the thread was away.

    Parking is the human saying they may come back to this, so the board owes
    them a way back that is one gesture: saying something in the thread. What its
    seat is owed is the other half -- it reasoned from a board that has since
    moved, and a reply composed against the older one would answer a question
    about a plan nobody is looking at any more.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    session.stub.script(PARKED_REPLY, PICKED_UP_REPLY)
    page = board(session)

    page.click('[data-act="threads"][data-id="d1"]')
    page.wait_for_timeout(400)
    say(page, PARKED_ASKED)
    session.settled()
    channel = thread_id(session)

    page.click(f'[data-act="park"][data-tid="{channel}"]')
    session.settled()
    assert threads_of(session)[channel]["state"] == "parked", threads_of(session)[channel]

    # The board moves while the thread is away, which is what there is to catch
    # up on.
    page.click('#col-d2 [data-act="pick"][data-opt="a"]')
    session.settled()

    page.click('[data-act="threads"][data-id="d1"]')
    page.wait_for_timeout(400)
    say_again(page, PICKED_UP)
    session.settled()

    picked_up = threads_of(session)[channel]
    assert picked_up["state"] == "open", picked_up
    assert [one["text"] for one in picked_up["turns"]] == [
        PARKED_ASKED,
        PARKED_REPLY,
        PICKED_UP,
        PICKED_UP_REPLY,
    ], picked_up["turns"]

    given = [one for one in session.dispatches() if one["channel"] == channel]
    assert len(given) == 2, [one["catch_up"] for one in given]
    assert given[0]["catch_up"] == [], given[0]["catch_up"]
    assert [one["target"] for one in given[1]["catch_up"]] == ["d2"], given[1]["catch_up"]


# A thread turn that offers an answer to the decision the thread is about, which
# is the only shape the board takes an offer in.
OFFER_TEXT = "Keep a session for thirty days, then archive it."
OFFERED = json.dumps(
    {
        "text": "Then thirty days is what it turns on.",
        "proposed_answer": {
            "decision": "d1",
            "option": "a",
            "text": OFFER_TEXT,
            "because": "recovery never reaches further back than that",
        },
    }
)

COMPACTED = "Compact on read and never on a timer."
OFFERED_ON_D2 = json.dumps(
    {
        "text": "Compaction follows the read, then.",
        "proposed_answer": {
            "decision": "d2",
            "option": "a",
            "text": COMPACTED,
            "because": "a timer compacts sessions nobody is reading",
        },
    }
)

# What the human writes into the decision's box after taking an offer: once
# under the offer, and once as a sentence with the offer's own words inside it.
# The second is what a fold that hunted for those words would cut out of their
# own sentence.
MINE = "Thirty is fine, but say what archiving costs."
REWRITTEN = "My answer is " + OFFER_TEXT + ", with one caveat."


def newest_thread(session: Session) -> str:
    """The channel of the thread opened most recently."""
    opened = [one for one in session.entries() if one.kind == "thread-created"]
    assert opened, "no thread was created"
    return str(opened[-1].channel)


def take_the_offer(page: Page, session: Session, node: str, asked: str) -> str:
    """Open a thread on a decision, let its seat offer an answer, and take it.

    The control is waited for rather than assumed: the seat's turn reaches the
    page on the page's own poll, and the board having settled is the backend's
    word rather than the browser's. Taking it puts nothing on the wire, so there
    is no log move to wait on afterwards.
    """
    page.click(f'[data-act="threads"][data-id="{node}"]')
    page.wait_for_timeout(400)
    say(page, asked)
    session.settled()
    page.wait_for_selector('[data-act="arm"]', timeout=BOARD_TIMEOUT)
    page.click('[data-act="arm"]')
    page.wait_for_timeout(RENDER)
    return newest_thread(session)


def test_taking_an_offer_shows_in_the_thread_and_the_fold_undoes_only_its_own_writing(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given two decisions whose threads have each offered an answer
    When the human takes the first into an empty box and folds that thread, and
         takes the second, writes more of their own under it and folds that one
    Then the first fold leaves the box empty, the second leaves the box exactly
         as the human last had it, and neither option is left marked.

    Taking an offer sends nothing -- it fills the decision's box for the human
    to send from there -- so the thread saying so is the only evidence the press
    landed. The arm belongs to the conversation that made it and goes when that
    conversation ends, but what the fold puts back is what arming found, and
    only while the box is still the one arming wrote. A box the human has
    touched since is theirs.
    """
    session = launcher(handoff=handoff(PLAN))
    session.stub.script(OFFERED, OFFERED_ON_D2)
    session.script_claude(turn(document("Folded in.")), turn(document("And that one too.")))
    page = board(session)

    channel = take_the_offer(page, session, "d1", "How long is a session kept?")

    # Arming closes the slide-out onto the decision it filled, so the thread is
    # opened again to read what the offer says now.
    page.click('[data-act="threads"][data-id="d1"]')
    page.wait_for_selector('[data-armed="d1"]', timeout=BOARD_TIMEOUT)
    assert page.locator('[data-act="arm"]').count() == 0, "the control is still on offer"
    armed = page.locator('[data-armed="d1"]')
    assert "send it from there" in armed.inner_text(), armed.inner_text()

    marked = page.locator('#col-d1 [data-act="pick"][data-opt="a"]')
    assert "armed" in (marked.get_attribute("class") or ""), marked.get_attribute("class")
    assert page.input_value("#ft-d1") == OFFER_TEXT, page.input_value("#ft-d1")

    page.click(f'[data-act="fold"][data-tid="{channel}"]')
    session.settled()
    page.wait_for_timeout(RENDER)
    assert "armed" not in (marked.get_attribute("class") or ""), marked.get_attribute("class")
    assert page.input_value("#ft-d1") == "", page.input_value("#ft-d1")

    # The same again, with the human's own words written under the offer before
    # the thread ends.
    channel = take_the_offer(page, session, "d2", "And what compacts it?")
    theirs = COMPACTED + "\n\n" + MINE
    page.fill("#ft-d2", theirs)
    page.wait_for_timeout(400)

    page.click('[data-act="threads"][data-id="d2"]')
    page.wait_for_selector('[data-armed="d2"]', timeout=BOARD_TIMEOUT)
    page.click(f'[data-act="fold"][data-tid="{channel}"]')
    session.settled()
    page.wait_for_timeout(RENDER)

    second = page.locator('#col-d2 [data-act="pick"][data-opt="a"]')
    assert "armed" not in (second.get_attribute("class") or ""), second.get_attribute("class")
    assert page.input_value("#ft-d2") == theirs, page.input_value("#ft-d2")


def test_a_box_the_human_wrote_the_offers_own_words_into_survives_the_fold(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given an offer taken into a decision's box
    When the human rewrites the box into a sentence of their own that quotes the
         offer's words, and then folds the thread
    Then the box is exactly what they wrote.

    This is the sequence that says why the fold recognises the box rather than
    searching it: a fold that cut the offer's words out wherever it found them
    would cut them out of the human's sentence, and on a decision whose answer
    an agent has just proposed, writing the same words is the likely case.
    """
    session = launcher(handoff=handoff(PLAN))
    session.stub.script(OFFERED)
    session.script_claude(turn(document("Folded in.")))
    page = board(session)

    channel = take_the_offer(page, session, "d1", "How long is a session kept?")
    page.fill("#ft-d1", REWRITTEN)
    page.wait_for_timeout(400)

    page.click('[data-act="threads"][data-id="d1"]')
    page.wait_for_selector('[data-armed="d1"]', timeout=BOARD_TIMEOUT)
    page.click(f'[data-act="fold"][data-tid="{channel}"]')
    session.settled()
    page.wait_for_timeout(RENDER)

    marked = page.locator('#col-d1 [data-act="pick"][data-opt="a"]')
    assert "armed" not in (marked.get_attribute("class") or ""), marked.get_attribute("class")
    assert page.input_value("#ft-d1") == REWRITTEN, page.input_value("#ft-d1")
