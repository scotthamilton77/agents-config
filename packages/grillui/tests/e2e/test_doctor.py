"""The map doctor proposes and the human applies, through the real launch path.

The doctor is the grill-master sent over the whole board. What it sends back
is a set of proposals: a new decision and a revise of one nobody has answered
-- both of which an ordinary map turn lands at once -- wait in the inbox until
the human lets them land.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conftest import BOARD_TIMEOUT, decision, document, handoff, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

PLAN = [decision("d1", "Which storage?"), decision("d2", "How is it compacted?")]
RETITLED = "How is the log compacted?"
ADDED = {
    "kind": "add-node",
    "target": "d9",
    "short": "d9",
    "title": "Who reads the log?",
    "body": "Decide.",
    "prereqs": [],
    "options": [{"id": "a", "text": "Only the backend"}, {"id": "b", "text": "Anyone"}],
    "why": "nothing on the board asks it",
}


def test_pnd_a8_the_doctors_changes_wait_in_the_inbox_until_the_human_lets_them_land(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a board with two unanswered decisions
    When the human calls the doctor and its document adds a decision and
         retitles d2
    Then neither change is on the board: both wait in the inbox; and once the
         human lets the new decision land, it is on the board.
    """
    session = launcher(handoff=handoff(PLAN))
    revise = {"kind": "revise", "target": "d2", "title": RETITLED, "why": "the log moved it"}
    session.script_claude(turn(document("Reassessed.", updates=[ADDED, revise])))
    page = board(session)

    page.click('[data-act="doctor"]')
    session.settled()

    image = session.board()
    assert "d9" not in {one["id"] for one in image["decisions"]}, "the doctor's add-node landed"
    d2 = next(one for one in image["decisions"] if one["id"] == "d2")
    assert d2["title"] == "How is it compacted?", "the doctor's revise landed"
    waiting = {(one["kind"], one.get("target")): one["id"] for one in image["pending"]}
    assert ("add-node", "d9") in waiting, image["pending"]
    assert ("revise", "d2") in waiting, image["pending"]

    page.click('[data-act="inbox"]')
    page.click(f'[data-act="applyone"][data-uid="{waiting[("add-node", "d9")]}"]')
    session.settled()
    page.wait_for_selector("#col-d9", timeout=BOARD_TIMEOUT)
    assert "d9" in {one["id"] for one in session.board()["decisions"]}
