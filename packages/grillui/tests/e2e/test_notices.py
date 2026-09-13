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
    compacted = page.locator("#col-d2 .rationale").inner_text()
    retained = page.locator("#col-d3 .rationale").inner_text()
    assert COMPACTION in compacted, compacted
    assert RETENTION in retained, retained
    # And neither one is carrying the other's reason, which is what a message
    # homed on every moved decision would have done.
    assert RETENTION not in page.locator("#col-d2").inner_text()
    assert COMPACTION not in page.locator("#col-d3").inner_text()

    # The story itself is where the turn is shown, once.
    page.click('[data-act="notifications"]')
    page.wait_for_timeout(RENDER)
    panel = page.locator("#overlay").inner_text()
    assert panel.count(STORY) == 1, panel


KILLED = "the log is the store, so there is nothing left to compact"
SURVIVES_A_DISMISSAL = "retention is asked whatever the store is"


def test_a_dismissed_change_is_not_reported_as_one_and_an_applied_change_is(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a turn proposing an invalidate on each of two decisions, which is a
         kind that always waits for the human
    When the human applies the one and dismisses the other
    Then the applied decision says what moved it and why, and the dismissed one
         says nothing at all.

    Both proposals leave the queue on the human's gesture, so a decision read
    off the queue's absence alone would report the dismissed change as landed --
    the board would say a decision moved that the human had just refused to
    move.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_claude(
        turn(
            document(
                "Both of these are in question now.",
                updates=[
                    {"kind": "invalidate", "target": "d2", "why": KILLED},
                    {"kind": "invalidate", "target": "d3", "why": SURVIVES_A_DISMISSAL},
                ],
                rulings=[
                    ruling("d2", "invalidate", KILLED),
                    ruling("d3", "invalidate", SURVIVES_A_DISMISSAL),
                ],
            )
        )
    )
    page = board(session)

    page.click('#col-d1 [data-act="pick"][data-opt="a"]')
    session.settled()
    page.wait_for_timeout(RENDER)

    waiting = {
        one["target"]: one["id"]
        for one in session.board()["pending"]
        if one["kind"] == "invalidate"
    }
    assert set(waiting) == {"d2", "d3"}, session.board()["pending"]

    # Neither has moved yet, so neither reports a change. The waiting block on
    # each of them quotes the proposal, which is what a waiting change says
    # about itself -- so the claim is read off the line that reports a change
    # that happened, and not off the block.
    assert page.locator("#col-d2 .rationale").count() == 0
    assert page.locator("#col-d3 .rationale").count() == 0

    page.click('[data-act="inbox"]')
    page.wait_for_timeout(RENDER)
    page.click(f'#overlay [data-act="applyone"][data-uid="{waiting["d2"]}"]')
    page.wait_for_timeout(RENDER)
    # Acting on the queue closes the panel, so the second gesture re-opens it.
    page.click('[data-act="inbox"]')
    page.wait_for_timeout(RENDER)
    page.click(f'#overlay [data-act="dismissone"][data-uid="{waiting["d3"]}"]')
    page.wait_for_timeout(RENDER)
    session.settled()

    # The two proposals only: the turn's own message is on the queue as the
    # notice it is, and an empty queue would be a claim about that instead.
    assert not [one for one in session.board()["pending"] if one["kind"] == "invalidate"]
    moved = page.locator("#col-d2 .rationale").inner_text()
    assert KILLED in moved, moved
    assert "invalidate" in moved, moved
    # The dismissed one reports nothing, and carries the reason nowhere at all:
    # the human refused the change, so the board has nothing to say about it.
    assert page.locator("#col-d3 .rationale").count() == 0
    refused = page.locator("#col-d3").inner_text()
    assert SURVIVES_A_DISMISSAL not in refused, refused
