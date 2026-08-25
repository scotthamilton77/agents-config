"""What credits a ruling, and what a ruling that credits nothing costs (GMR-A3/A4).

Saying a decision is dead is not proposing its death. The board goes on offering
every decision until something moves it, so a verdict of `invalidate` or `revise`
counts only where the same turn also carries that update against that decision --
crediting the word alone is exactly the failure the ruling exists to catch.

A verdict of `stands` is the other shape and is credited on its `why` alone,
because standing is the absence of a change: the decision goes on being offered,
which is the point. What it does put on the board is a notice on that decision
carrying the reasoning, so the judgement is somewhere the human reads rather
than nowhere.

The check is coverage and never correctness. A ruling the backend would disagree
with is not a ruling missing, and no code here reads what a `why` means.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conftest import agent_turns, decision, document, handoff, notices, option, ruling, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

MARKED = [
    decision(
        "d1",
        "Which storage?",
        options=[option("a", "Append-only log", ["d2", "d3"]), option("b", "Table")],
    ),
    decision("d2", "How is it compacted?"),
    decision("d3", "What is retained?"),
]

DEAD_WITH_IT = "it has no question left once the log is the store"
SURVIVES = "retention is asked whatever the store is"


def answer(page: Page, node: str, chosen: str = "a") -> None:
    page.click(f'#col-{node} [data-act="pick"][data-opt="{chosen}"]')


def test_a_verdict_counts_only_where_the_same_turn_carried_the_change(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a turn ruling `invalidate` on both decisions the answer put in
         question, but carrying that update against only one of them
    When the human takes the marked option
    Then the ruling backed by an update discharges its decision and the bare one
         does not: the human is told by name that the second went unruled, and
         the board is still offering it while the first has a change waiting.
    """
    session = launcher(handoff=handoff(MARKED))
    session.script_claude(
        turn(
            document(
                "The store settles both.",
                updates=[{"kind": "invalidate", "target": "d2", "why": DEAD_WITH_IT}],
                rulings=[
                    ruling("d2", "invalidate", DEAD_WITH_IT),
                    ruling("d3", "invalidate", "this one is a word and nothing else"),
                ],
            )
        )
    )
    page = board(session)

    answer(page, "d1")
    session.settled()

    unmet = [one for one in notices(session.entries()) if "not ruled on" in one]
    assert len(unmet) == 1, notices(session.entries())
    assert "d3" in unmet[0], unmet[0]
    assert "d2" not in unmet[0], f"a ruling backed by its update was reported unruled: {unmet[0]}"

    # The credited one has a change waiting on it; the uncredited one has
    # nothing, which is the whole difference a verdict without an update makes.
    waiting = {one["target"] for one in session.board()["pending"] if one["kind"] == "invalidate"}
    assert waiting == {"d2"}, session.board()["pending"]


def test_a_ruling_that_a_decision_stands_is_credited_and_says_so_on_that_decision(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a turn ruling that both decisions in question stand, with a line of
         why on each and no update at all
    When the human takes the marked option
    Then nothing is reported unruled, each decision carries a notice minted from
         its own ruling and stamped with the verdict it was minted for, and the
         human reads that reasoning on the decision itself.

    A `stands` has no update behind it by design, so its `why` would otherwise
    be a judgement nothing recorded.
    """
    session = launcher(handoff=handoff(MARKED))
    session.script_claude(
        turn(
            document(
                text="",
                rulings=[ruling("d2", "stands", DEAD_WITH_IT), ruling("d3", "stands", SURVIVES)],
            )
        )
    )
    page = board(session)

    answer(page, "d1")
    session.settled()

    assert not [one for one in notices(session.entries()) if "not ruled on" in one], notices(
        session.entries()
    )
    spoke = agent_turns(session.entries())[-1]
    minted = {
        one["target"]: one for one in spoke.payload["updates"] if one["kind"] == "informational"
    }
    assert set(minted) == {"d2", "d3"}, spoke.payload["updates"]
    assert minted["d3"]["verdict"] == "stands", minted["d3"]
    assert minted["d3"]["why"] == SURVIVES, minted["d3"]
    assert minted["d3"]["text"] == f"d3 stands: {SURVIVES}", minted["d3"]

    # And the human reads it where the decision is, not on a lane somewhere else.
    page.wait_for_timeout(1200)
    assert SURVIVES in page.locator("#col-d3").inner_text(), page.locator("#col-d3").inner_text()
