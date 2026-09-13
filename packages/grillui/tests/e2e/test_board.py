"""What the option row says about an answer once the human has given it.

The column is where a human checks what they answered, and the option row is the
part of it they read fastest: a filled button reads as the standing answer. So
the mark has to sit on the option the answer names, and the recommendation's
fill has to leave when the answer arrives. A row that kept option a filled after
the human took option b would tell them the opposite of what the log says, in
the one place they would look to catch it.

The claim is a rendered one, which is why it is here rather than in the source
checks: a class assembled in a function nobody renders is not a mark anyone saw.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conftest import BOARD_TIMEOUT, decision, document, handoff, option, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

PLAN = [
    decision(
        "d1",
        "Which storage?",
        options=[option("a", "Append-only log"), option("b", "Table")],
    ),
    decision("d2", "How is it compacted?"),
]


def test_a_settled_decision_marks_the_option_the_human_chose(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a decision offering two options
    When the human answers it with the second one and opens it again
    Then that option's control wears the mark and the tick, and the first
         option wears neither the mark nor the recommendation's fill.

    The decision is reopened because settling collapses it, and a mark on a row
    nobody can see is not the fix. The first option is asserted on directly: the
    failure being closed is one control staying filled, and a check that only
    looked at the answered option would pass with both of them filled.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    page = board(session)

    page.click('#col-d1 [data-act="pick"][data-opt="b"]')
    session.settled()
    page.wait_for_selector("#col-d1 .pill.settled", timeout=BOARD_TIMEOUT)
    page.click('#col-d1 [data-act="toggle"]')

    taken = '#col-d1 [data-act="pick"][data-opt="b"]'
    page.wait_for_selector(taken + ".chosen", timeout=BOARD_TIMEOUT)
    assert "✓" in page.locator(taken).inner_text(), page.locator(taken).inner_text()

    passed_over = page.locator('#col-d1 [data-act="pick"][data-opt="a"]')
    worn = passed_over.get_attribute("class") or ""
    assert "primary" not in worn, worn
    assert "chosen" not in worn, worn


def test_the_human_reopens_a_decision_they_settled(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a decision the human has answered
    When they open its block again and press the control that reopens it
    Then the board reads that decision as a question again.

    An agent's unsettle waits in the queue for the human to apply it, so on a
    board where no agent has proposed one this control is the only way back
    from an answer the human regrets. The whole path is exercised because that
    is where it breaks: a gesture the page builds, a kind the backend accepts
    from the human, and the fold that returns the decision to the frontier.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    page = board(session)

    page.click('#col-d1 [data-act="pick"][data-opt="b"]')
    session.settled()
    page.wait_for_selector("#col-d1 .pill.settled", timeout=BOARD_TIMEOUT)
    page.click('#col-d1 [data-act="toggle"]')

    page.click('#col-d1 [data-act="reopen"]')
    session.settled()
    page.wait_for_selector("#col-d1 .pill.open", timeout=BOARD_TIMEOUT)
