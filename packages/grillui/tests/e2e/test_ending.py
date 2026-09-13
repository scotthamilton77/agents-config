"""Ending a session, and what the board asks before it writes the terminal entry.

The ending is the one gesture nothing undoes: the entry is durable, the result
is written beside it and the backend stops. Two states make it a gesture the
human can regret -- a turn still composing, whose answer could put a new
decision on the board, and a board with questions still open on it. Neither is
visible in the control itself, so the board says which one it is and asks again.

Measured in a browser against a real backend because the claim is about what a
click does: that the first one appends nothing is not a fact any source check
can reach, and a guard that renders but still writes would pass one.

The pending case is driven by a seat that genuinely takes its time. The scripted
turn sleeps, so the lane is open and unanswered for as long as the scenario
needs -- which is what "mid-turn" means everywhere else in this system.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from conftest import BOARD_TIMEOUT, RENDER, decision, document, handoff, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

PLAN = [decision("d1", "Which storage?"), decision("d2", "How is it compacted?")]
ONE = [decision("d1", "Which storage?")]

TOPBAR_END = '.topbar [data-act="endsession"]'
OFFER = "#completion"
OFFER_END = '#completion [data-act="endsession"]'
CONFIRM = "#confirm"
CONFIRM_END = '#confirm [data-act="confirm-end"]'

# The human's ruling, verbatim: what the board says when the ending would land
# on a turn nobody has heard back from.
PENDING_TEXT = (
    "There are pending agent responses that could result in new decisions to be made. "
    "Are you sure you want to end the session now?"
)

# How long a scenario waits on the log for something it expects. Longer than the
# page's own poll and far shorter than a scripted seat's sleep, so a wait that
# runs out is a fact about the board rather than about scheduling.
PATIENCE = 10.0
POLL = 0.05
# What a seat that must still be composing when the scenario clicks is scripted
# to sleep. Every wait before that click is bounded well inside it.
SLOW = 8


def endings(session: Session) -> list[object]:
    """The terminal entries in the log, of which there may never be more than one."""
    return [one for one in session.entries() if one.kind == "session-end"]


def mid_turn(session: Session) -> bool:
    """Whether a turn is open on some channel, by the lane's own pairing rule."""
    open_turns: set[str] = set()
    for entry in session.entries():
        if entry.kind != "status":
            continue
        if entry.payload.get("phase") == "composing":
            open_turns.add(entry.channel)
        elif entry.payload.get("phase") in {"replied", "error"}:
            open_turns.discard(entry.channel)
    return bool(open_turns)


def wait_for_a_turn(session: Session) -> None:
    """Wait until a seat is composing, which is what the sleeping turn buys."""
    deadline = time.monotonic() + PATIENCE
    while time.monotonic() < deadline:
        if mid_turn(session):
            return
        time.sleep(POLL)
    never = "no turn ever opened: the scripted seat never got as far as composing"
    raise AssertionError(never)


def wait_for_the_ending(session: Session) -> None:
    """Wait until the terminal entry is on the log."""
    deadline = time.monotonic() + PATIENCE
    while time.monotonic() < deadline:
        if endings(session):
            return
        time.sleep(POLL)
    never = "the confirmed ending never reached the log"
    raise AssertionError(never)


def test_ending_mid_turn_asks_again_and_writes_nothing_until_it_is_answered(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a seat still composing its answer to the decision just settled
    When the human presses the top row's ending control
    Then nothing is written, the board asks again in the words the ending is
         worth asking about, and only the answer to that question ends it.

    The log is read for the terminal entry rather than the page for a banner:
    what must not happen is an append, and a page that rendered the question and
    sent the event anyway would look identical until the entry is counted.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted."), delay=SLOW))
    page = board(session)

    page.click('#col-d1 [data-act="pick"][data-opt="a"]')
    wait_for_a_turn(session)
    page.wait_for_timeout(RENDER)

    page.click(TOPBAR_END)
    page.wait_for_selector(CONFIRM, timeout=BOARD_TIMEOUT)
    assert mid_turn(session), "the seat replied before the click: this proved nothing"
    said = page.locator(f"{CONFIRM} .box").inner_text()
    assert PENDING_TEXT in said, said
    assert not endings(session), "the first click ended the session behind the question"

    page.click(CONFIRM_END)
    wait_for_the_ending(session)
    assert len(endings(session)) == 1, endings(session)


def test_the_completion_offer_says_a_turn_is_still_out_and_names_its_act_for_it(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given the last open decision settled while its seat is still composing
    When the finished board announces itself
    Then the offer says responses are pending and the act it offers says it is
         ending anyway -- and pressing it is still guarded.

    A board can be finished and busy at the same time, and the offer is the one
    place saying "nothing is waiting on you". Left alone it would say that over
    a turn whose answer is what reopens the board.
    """
    session = launcher(handoff=handoff(ONE))
    session.script_codex(turn(document("Noted."), delay=SLOW))
    page = board(session)

    page.click('#col-d1 [data-act="pick"][data-opt="a"]')
    page.wait_for_selector(OFFER, timeout=BOARD_TIMEOUT)
    offered = page.locator(f"{OFFER} .box").inner_text()
    assert "Agent responses are still pending" in offered, offered
    assert page.locator(OFFER_END).inner_text().strip() == "End Session Anyway", offered

    page.click(OFFER_END)
    page.wait_for_selector(CONFIRM, timeout=BOARD_TIMEOUT)
    assert PENDING_TEXT in page.locator(f"{CONFIRM} .box").inner_text()
    assert not endings(session), "the offer's own control ended the session unasked"

    page.click(CONFIRM_END)
    wait_for_the_ending(session)
    assert len(endings(session)) == 1, endings(session)


def test_ending_an_unfinished_board_asks_once_and_names_what_is_still_open(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a board with both its decisions still open and no turn running
    When the human presses the ending control
    Then one question is raised, and it is about the board rather than about a
         turn: it counts what is still open, and confirming it ends the session.
    """
    session = launcher(handoff=handoff(PLAN))
    page = board(session)

    page.click(TOPBAR_END)
    page.wait_for_selector(CONFIRM, timeout=BOARD_TIMEOUT)
    said = page.locator(f"{CONFIRM} .box").inner_text()
    assert "2 decisions on this board are still open" in said, said
    assert PENDING_TEXT not in said, said
    assert not endings(session), "the click ended the unfinished board behind the question"

    page.click(CONFIRM_END)
    wait_for_the_ending(session)
    assert len(endings(session)) == 1, endings(session)


def test_a_finished_and_quiet_board_ends_on_the_one_click(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given every decision settled and every turn closed
    When the human presses the offer's ending control
    Then the session ends on that press, with nothing in between.

    The guard is worth having only if it stays out of the way of the gesture it
    is guarding, so the unguarded path is pinned as hard as the guarded ones.
    The control's own wording is asserted first: it reads as the plain ending
    exactly when nothing is pending, which is what makes the single click a
    measurement of a quiet board rather than of a lucky one.
    """
    session = launcher(handoff=handoff(ONE))
    session.script_codex(turn(document("Noted.")))
    page = board(session)

    page.click('#col-d1 [data-act="pick"][data-opt="a"]')
    session.settled()
    page.wait_for_selector(OFFER, timeout=BOARD_TIMEOUT)
    page.wait_for_timeout(RENDER)
    assert not mid_turn(session), "a turn was still open: this measured the guarded path"
    assert page.locator(OFFER_END).inner_text().strip() == "End the session"

    page.click(OFFER_END)
    assert page.locator(CONFIRM).count() == 0, "the quiet board asked anyway"
    wait_for_the_ending(session)
    assert len(endings(session)) == 1, endings(session)
