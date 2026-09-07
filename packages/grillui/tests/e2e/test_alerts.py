"""The human's way out of a lock a blocking alert took.

An alert that declares itself blocking shuts its decision, and the gesture that
reopens it is the queue's own dismiss, on the alert itself. What is checked here
is the whole chain rather than any link of it -- the control is on the alert,
the click puts a `dismiss` in the log, and the fold that reads that log hands
back a decision on the frontier. A unit test can pin any one of those and still
leave a button that renders nowhere the human can press it.

The control is offered only where pressing it frees the decision, so the second
scenario is the negative: a decision a queued change also holds is not one an
alert's dismissal reopens, and the alert there carries no button to suggest
otherwise.
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


# One turn that both proposes a change to d2 and raises an alert on it, so the
# decision is held twice over. An `invalidate` is the update that always waits
# for the human, which is what puts a live proposal on the queue beside the
# alert.
# Two alerts on d2 in one turn, and only the second locks it. The board reads
# the last alert on a decision, so the first supplies no lock and dismissing it
# would move nothing -- and once the second is gone the first is what the board
# reads, which is why the decision comes back rather than staying shut.
TWO_ALERTS_ON_D2 = document(
    "d2 rests on two things nobody has supplied.",
    updates=[
        {
            "kind": "elicit-alert",
            "target": "d2",
            "text": "nobody has priced the alternative",
            "blocking": False,
        },
        {
            "kind": "elicit-alert",
            "target": "d2",
            "text": "and nobody has read the vendor's licence terms",
            "blocking": True,
        },
    ],
)

ALERT_UNDER_A_CHANGE = document(
    "d2 may be moot, and it rests on something nobody has supplied.",
    updates=[
        {"kind": "invalidate", "target": "d2", "why": "the export subsumes it"},
        {
            "kind": "elicit-alert",
            "target": "d2",
            "text": "nobody has read the vendor's licence terms",
            "blocking": True,
        },
    ],
)


def node(session: Session, id: str) -> dict[str, Any]:
    return next(one for one in session.board()["decisions"] if one["id"] == id)


def alert_ids(session: Session) -> list[str]:
    """The live alerts on the queue, in the order the board carries them."""
    return [
        one["id"]
        for one in session.board()["pending"]
        if one["kind"] == "elicit-alert" and not one["superseded"]
    ]


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

    uid = alert_ids(session)[-1]
    page.click(f'#col-d2 [data-act="dismissone"][data-uid="{uid}"]')
    page.wait_for_timeout(RENDER)

    assert [one.kind for one in session.entries() if one.actor == "human"].count("dismiss") == 1
    # The alert alone: whatever else the seats put on the queue in the meantime
    # is not what this press was about, and asserting an empty queue would make
    # the scenario fail on a notice it never mentioned.
    assert not [one for one in session.board()["pending"] if one["kind"] == "elicit-alert"]
    assert node(session, "d2")["locked"] is False
    assert "d2" in session.board()["frontier"], session.board()["frontier"]


def test_an_alert_under_a_waiting_change_offers_no_dismissal_that_would_free_nothing(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a decision held by a queued change and an alert at once
    When the human reads the alert on that decision's block
    Then the alert carries no dismissal, and the lock is captioned as the change
         that is waiting.

    The control exists to reopen a decision, so it is offered only where
    pressing it would reopen one. Dismissing this alert leaves the change still
    holding the decision: a button here is one the human presses to no effect,
    and the caption would be sending them at the wrong hold.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(ALERT_UNDER_A_CHANGE), turn(document("Noted.")))
    page = board(session)

    page.click('#col-d1 [data-act="pick"][data-opt="a"]')
    session.settled()
    page.wait_for_timeout(RENDER)
    assert node(session, "d2")["locked"] is True, session.board()["decisions"]

    caption = page.locator("#col-d2 .pill.locked").inner_text().lower()
    assert "change" in caption, caption
    assert "alert" not in caption, caption

    uid = alert_ids(session)[-1]
    assert page.locator(f'#col-d2 [data-act="dismissone"][data-uid="{uid}"]').count() == 0
    assert page.locator(f'#col-d2 [data-act="discussnotice"][data-uid="{uid}"]').count() == 1


def test_only_the_alert_the_board_reads_carries_the_dismissal(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given two alerts on one decision, of which only the later one blocks
    When the human reads both on that decision's block
    Then only the later one carries a dismissal, and pressing it reopens the
         decision.

    The board reads the last alert on a decision, so the earlier one supplies no
    lock and dismissing it would move nothing. Both are still worth reading --
    neither is deleted, and both keep their Discuss -- but a control that frees
    the decision belongs on the alert that is holding it. What the decision comes
    back to is the earlier alert's own verdict, which is the recency rule read
    from the other end.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(TWO_ALERTS_ON_D2), turn(document("Noted.")))
    page = board(session)

    page.click('#col-d1 [data-act="pick"][data-opt="a"]')
    session.settled()
    page.wait_for_timeout(RENDER)
    older, holding = alert_ids(session)
    assert node(session, "d2")["locked"] is True, session.board()["decisions"]

    assert page.locator(f'#col-d2 [data-act="dismissone"][data-uid="{older}"]').count() == 0
    assert page.locator(f'#col-d2 [data-act="discussnotice"][data-uid="{older}"]').count() == 1

    page.click(f'#col-d2 [data-act="dismissone"][data-uid="{holding}"]')
    page.wait_for_timeout(RENDER)

    assert node(session, "d2")["locked"] is False
    assert "d2" in session.board()["frontier"], session.board()["frontier"]
