"""Where a turn's message lands, and what each decision it moved says locally.

A turn speaks once and may move several decisions in the same breath. The
message is about the turn, so the board shows it once, where the turn is shown.
Homing it on every decision the turn moved instead puts one paragraph in four
places, and the human reads the same three sentences four times.

That leaves each moved decision owing a statement of its own, and it already
has one: the change that moved it carries a `why`, and the board shows that line
on the decision. So the turn-level story and the per-decision consequence reach
the human in two different places, each once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conftest import RENDER, decision, document, handoff, option, ruling, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

PLAN = [
    decision(
        "d1",
        "Which storage?",
        options=[option("a", "Append-only log", ["d2", "d3"]), option("b", "Table")],
    ),
    decision("d2", "How is it compacted?"),
    decision("d3", "What is retained?"),
]

STORY = (
    "Taking option a of d1 makes the log the store, which changes what two other decisions "
    "are asking. Compaction is now a question about the log rather than about a table, and "
    "retention is a question about how far back the log is kept."
)
COMPACTION = "the log is the store, so compaction is a question about the log"
RETENTION = "retention is now how far back the log is kept"


def test_a_turns_message_lands_once_and_each_moved_decision_says_what_moved(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a turn whose message names no decision and whose two revises each
         carry their own `why`
    When the human takes the option that puts both of those decisions in
         question
    Then the message is nowhere in the column and is in the notification panel,
         and each revised decision carries its own reason on its own block.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_claude(
        turn(
            document(
                STORY,
                updates=[
                    {
                        "kind": "revise",
                        "target": "d2",
                        "body": "How is the log compacted?",
                        "why": COMPACTION,
                    },
                    {
                        "kind": "revise",
                        "target": "d3",
                        "body": "How far back is it kept?",
                        "why": RETENTION,
                    },
                ],
                rulings=[ruling("d2", "revise", COMPACTION), ruling("d3", "revise", RETENTION)],
            )
        )
    )
    page = board(session)

    page.click('#col-d1 [data-act="pick"][data-opt="a"]')
    session.settled()
    page.wait_for_timeout(RENDER)

    # The turn's story is not repeated against what the turn moved -- nor
    # against anything else on the board.
    column = page.locator("#column").inner_text()
    assert STORY not in column, column

    # Each moved decision says what moved on it, without the human opening
    # anything.
    assert COMPACTION in page.locator("#col-d2").inner_text(), page.locator("#col-d2").inner_text()
    assert RETENTION in page.locator("#col-d3").inner_text(), page.locator("#col-d3").inner_text()
    # And neither one is carrying the other's reason, which is what a message
    # homed on every moved decision would have done.
    assert RETENTION not in page.locator("#col-d2").inner_text()
    assert COMPACTION not in page.locator("#col-d3").inner_text()

    # The story itself is where the turn is shown, once.
    page.click('[data-act="notifications"]')
    page.wait_for_timeout(RENDER)
    panel = page.locator("#overlay").inner_text()
    assert panel.count(STORY) == 1, panel
