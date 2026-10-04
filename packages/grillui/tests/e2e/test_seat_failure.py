"""A seat that fails leaves a trace on the page, through the real launch path.

A seat that runs out of time is the case nothing else here can produce: the
scripted CLI holds its turn open and is never released, and the backend's own
turn timeout kills it. What the human has to see is which seat failed and why,
whether the rung above then answered or nobody did.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conftest import BOARD_TIMEOUT, decision, document, handoff, lane, notices, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

# Three decisions, so answering two still leaves the board unfinished: a
# finished board raises its completion offer over everything this reads.
PLAN = [
    decision("d1", "Which storage?"),
    decision("d2", "How is it compacted?"),
    decision("d3", "What is retained?"),
]

# Short enough that a held turn is killed well inside the harness's own turn
# budget, and long enough that a shim that is not held always answers first.
TIMEOUT = {"GRILLUI_REQUEST_TIMEOUT": "2"}

# A name nothing releases, so a turn held under it runs into the timeout.
NEVER = "never"


def answer(page: Page, node: str) -> None:
    page.click(f'#col-{node} [data-act="pick"][data-opt="a"]')


def notifications(page: Page) -> str:
    """The notification list's text, with the panel opened to read it."""
    page.click('[data-act="notifications"]')
    page.wait_for_selector("#overlay .slide", timeout=BOARD_TIMEOUT)
    said = page.locator("#overlay").inner_text()
    page.click('[data-act="closepanel"]')
    return said


def test_pnd_a13_a_map_seat_that_times_out_is_handed_up_and_the_page_says_so(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a first-rung seat that never answers, and an expert that does
    When the human answers a decision
    Then the backend kills the first seat on its timeout, the expert takes the
         turn, the lane closes `replied`, and the page's notification list
         names the seat that timed out and the seat the turn went up to.
    """
    session = launcher(handoff=handoff(PLAN), config=TIMEOUT)
    session.script_codex(turn(document("Never said."), hold=NEVER))
    session.script_claude(turn(document("Taken up.")))
    page = board(session)

    answer(page, "d1")
    session.settled()

    assert lane(session.entries(), "map")[-1][0] == "replied"
    said = notices(session.entries())
    assert any("'fast' tier failed" in one and "timed out" in one for one in said), said
    # The log holds the notice before the page's next poll has brought it in,
    # so the notice itself is what is waited for.
    page.wait_for_function(
        "() => NOTES.some(n => n.text.indexOf('timed out') >= 0)",
        timeout=BOARD_TIMEOUT,
    )
    shown = notifications(page)
    assert "timed out" in shown, shown
    assert "handed up to the 'heavy' tier" in shown, shown


def test_pnd_a13_a_turn_no_seat_answers_leaves_a_trace_naming_each_seat_and_cause(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a turn both seats answer, and then a turn neither seat answers in time
    When the human answers one decision and then the other
    Then the first leaves no failure trace on the page, and the second leaves
         one naming the map, each seat that failed, and that each timed out.
    """
    session = launcher(handoff=handoff(PLAN), config=TIMEOUT)
    session.script_codex(turn(document("Fine.")), turn(document("Never said."), hold=NEVER))
    session.script_claude(turn(document("Never said."), hold=NEVER))
    page = board(session)

    answer(page, "d1")
    session.settled()
    assert "ended without a reply" not in notifications(page)

    answer(page, "d2")
    session.settled()

    assert lane(session.entries(), "map")[-1][0] == "error"
    # The poll that brings the closing entry in can trail the one that brought
    # the hand-up's notice, so the trace itself is what is waited for.
    page.wait_for_function(
        "() => NOTES.some(n => n.text.indexOf('ended without a reply') >= 0)",
        timeout=BOARD_TIMEOUT,
    )
    shown = notifications(page)
    assert "A turn on the map ended without a reply" in shown, shown
    assert "'fast' tier failed" in shown, shown
    assert "'heavy' tier failed" in shown, shown
    assert shown.count("timed out") >= 2, shown
