"""The human's way out of a lock a blocking alert took.

An alert that declares itself blocking shuts its decision, and until the human
has a gesture that lifts it the board can reach a state no action of theirs
finishes: the decision is unanswerable, and the only thing that reopens it is a
second turn from the seat that shut it.

The gesture is the queue's own dismiss, so what is checked here is the whole
chain rather than any link of it -- the control is on the alert, the click puts
a `dismiss` in the log, and the fold that reads that log hands back a decision
on the frontier. A unit test can pin any one of those and still leave a button
that renders nowhere the human can press it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from conftest import RENDER, decision, document, handoff, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

PLAN = [decision("d1", "Which store?"), decision("d2", "Which licence?")]

ALERTS_ON_D2 = document(
    "The licence question rests on something nobody has supplied.",
    updates=[
        {
            "kind": "elicit-alert",
            "target": "d2",
            "text": "nobody has read the vendor's licence terms",
            "blocking": True,
        }
    ],
)


def node(session: Session, id: str) -> dict[str, Any]:
    return next(one for one in session.board()["decisions"] if one["id"] == id)


def alert_id(session: Session) -> str:
    return next(one["id"] for one in session.board()["pending"] if one["kind"] == "elicit-alert")


def test_the_human_dismisses_a_blocking_alert_and_gets_the_decision_back(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a decision the grill-master locked with a blocking alert
    When the human dismisses that alert from the block it is read on
    Then the lock is explained as the alert rather than as a thread, the
         dismissal reaches the log, and the decision is answerable again.

    The explanation is asserted before the click because it is what tells the
    human the press is theirs to make: a lock captioned "a thread must conclude"
    over a decision with no thread sends them looking for something that is not
    there, and the control below it goes unpressed.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(ALERTS_ON_D2), turn(document("Noted.")))
    page = board(session)

    page.click('#col-d1 [data-act="pick"][data-opt="a"]')
    session.settled()
    page.wait_for_timeout(RENDER)
    assert node(session, "d2")["locked"] is True, session.board()["decisions"]

    # Lower-cased because the pill is upper-cased in the stylesheet, and what is
    # asserted is the words the human reads rather than the casing they arrive in.
    caption = page.locator("#col-d2 .pill.locked").inner_text().lower()
    assert "alert" in caption, caption
    assert "thread" not in caption, caption

    uid = alert_id(session)
    page.click(f'#col-d2 [data-act="dismissone"][data-uid="{uid}"]')
    page.wait_for_timeout(RENDER)

    assert [one.kind for one in session.entries() if one.actor == "human"].count("dismiss") == 1
    # The alert alone: whatever else the seats put on the queue in the meantime
    # is not what this press was about, and asserting an empty queue would make
    # the scenario fail on a notice it never mentioned.
    assert not [one for one in session.board()["pending"] if one["kind"] == "elicit-alert"]
    assert node(session, "d2")["locked"] is False
    assert "d2" in session.board()["frontier"], session.board()["frontier"]
