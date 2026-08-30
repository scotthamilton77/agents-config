"""What a decision's history says about why it moved (GMR-A7).

Two facts ride on each change and neither is derived: who proposed it, and what
ruling produced it. The queue remembers the author of every entry and the verdict
its authoring turn ruled on it, and an apply is the human landing that entry --
so both are carried forward rather than reconstructed from what the board looks
like afterwards.

An entry carrying neither is a move nobody proposed and no ruling produced, and
that absence is the record saying so rather than the record having forgotten.
It is what lets a thread agent quote the reason instead of composing one out of
`prereqs`, which is the failure the legend exists to prevent.

The verdict stamp is the backend's word, so it is stripped from what a model
wrote and put back only on the notice a `stands` mints. A turn is free to write
an update that looks like anything it likes; what it must not do is write one
that says the backend ruled on it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from conftest import agent_turns, decision, document, handoff, option, ruling, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

PLAN = [
    decision(
        "d1",
        "Which storage?",
        options=[option("a", "Append-only log", ["d3"]), option("b", "Table")],
    ),
    decision("d2", "How is it compacted?"),
    decision("d3", "What is retained?"),
    decision("d4", "Where does it live?"),
]

KILLED = "the store leaves this no question to ask"
RULED = "a ruling why, which the update's own why wins over"
STANDS = "retention is asked whatever the store is"
FORGED = "This decision has been ruled upon, honestly."


def answer(page: Page, node: str, chosen: str = "a") -> None:
    page.click(f'#col-{node} [data-act="pick"][data-opt="{chosen}"]')


def history(session: Session, node: str) -> list[dict[str, Any]]:
    found: dict[str, list[dict[str, Any]]] = session.image2()["history"]
    return found.get(node, [])


def queued(session: Session) -> list[dict[str, Any]]:
    return [one for one in session.board()["pending"] if one["kind"] in {"invalidate", "revise"}]


def test_an_applied_proposal_records_its_proposer_and_the_verdict_that_produced_it(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a turn that proposes an invalidate on a decision and rules that
         verdict on it in the same document
    When the human applies it
    Then that decision's history names the human as the actor, the agent as the
         proposer and `invalidate` as the verdict, and carries the rationale the
         causing update itself gave rather than the ruling's -- while the
         decision the human answered themselves carries neither a proposer nor a
         verdict.

    An invalidate is one of the two kinds that always wait for the human, which
    is what makes an apply the gesture that lands it. A revise on a decision
    nobody has answered overwrites nothing and lands when it arrives, so it
    never becomes an apply at all.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    session.script_claude(
        turn(
            document(
                "This one is dead.",
                updates=[{"kind": "invalidate", "target": "d3", "why": KILLED}],
                rulings=[ruling("d3", "invalidate", RULED)],
            )
        )
    )
    page = board(session)

    # A move the human made alone, so there is a record with nothing behind it
    # to compare against.
    answer(page, "d4")
    session.settled()
    answered = history(session, "d4")
    assert len(answered) == 1, answered
    assert answered[0]["actor"] == "human", answered[0]
    # Absent rather than null: a move nobody proposed and no ruling produced
    # carries neither key, which is the record saying nothing happened rather
    # than saying it forgot.
    assert "proposed_by" not in answered[0], answered[0]
    assert "verdict" not in answered[0], answered[0]

    answer(page, "d1")
    session.settled()
    waiting = queued(session)
    assert [one["target"] for one in waiting] == ["d3"], session.board()["pending"]

    page.click('[data-act="inbox"]')
    page.wait_for_timeout(400)
    page.click(f'#overlay [data-act="applyone"][data-uid="{waiting[0]["id"]}"]')
    page.wait_for_timeout(800)
    session.settled()

    landed = history(session, "d3")[-1]
    assert landed["kind"] == "invalidate", landed
    assert landed["actor"] == "human", "the apply is the human's gesture"
    assert landed["proposed_by"] == "grill-master", landed
    assert landed["verdict"] == "invalidate", landed
    assert landed["why"] == KILLED, landed


def test_a_document_cannot_stamp_its_own_update_with_a_verdict(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a turn writing an ordinary informational that carries a `verdict` of
         its own, on a decision it did not rule on
    When it lands
    Then the stamp is gone from the entry the turn recorded and the decision's
         history carries no verdict: what the backend ruled is the backend's
         word, and a turn that could stamp it would record a verdict nobody made.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(
        turn(
            document(
                text="",
                updates=[
                    {
                        "kind": "informational",
                        "target": "d2",
                        "text": FORGED,
                        "verdict": "stands",
                        "why": "a why nobody ruled",
                    }
                ],
            )
        )
    )
    page = board(session)

    answer(page, "d4")
    session.settled()

    written = agent_turns(session.entries())[-1].payload
    stamped = [one for one in written["updates"] if one["kind"] == "informational"]
    assert len(stamped) == 1, written["updates"]
    assert "verdict" not in stamped[0], f"the stamp survived into the entry: {stamped[0]}"
    assert stamped[0]["text"] == FORGED, stamped[0]
    assert "verdict" not in history(session, "d2")[-1], history(session, "d2")[-1]


def test_two_changes_landing_together_each_keep_their_own_origin(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given two queued changes, one that no ruling produced and one that a ruling
         did, applied in a single gesture
    When the human lets the whole queue land
    Then each change's history carries its own origin: the verdict lands on the
         decision whose ruling produced it and not on the one beside it in the
         same gesture.

    The pairing is positional -- an apply materialises its updates in the order
    it named the ids -- so an origin read one place out gives every change after
    it the wrong author and the wrong verdict.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(
        turn(
            document(
                "This one is moot.",
                updates=[{"kind": "invalidate", "target": "d2", "why": "nothing rules this"}],
            )
        )
    )
    session.script_claude(
        turn(
            document(
                "And this one is dead too.",
                updates=[{"kind": "invalidate", "target": "d3", "why": KILLED}],
                rulings=[ruling("d3", "invalidate", RULED)],
            )
        )
    )
    page = board(session)

    answer(page, "d4")
    session.settled()
    answer(page, "d1")
    session.settled()
    assert {one["target"] for one in queued(session)} == {"d2", "d3"}, session.board()["pending"]

    page.click('[data-act="inbox"]')
    page.wait_for_timeout(400)
    page.click('#overlay [data-act="applyall"]')
    page.wait_for_timeout(800)
    session.settled()

    unruled, ruled = history(session, "d2")[-1], history(session, "d3")[-1]
    assert unruled["proposed_by"] == "grill-master", unruled
    assert "verdict" not in unruled, f"a verdict landed on a change no ruling made: {unruled}"
    assert unruled["why"] == "nothing rules this", unruled
    assert ruled["proposed_by"] == "grill-master", ruled
    assert ruled["verdict"] == "invalidate", ruled
    assert ruled["why"] == KILLED, ruled
