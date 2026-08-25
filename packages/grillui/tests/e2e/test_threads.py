"""What a thread is, and what its agent is handed (GMR-A7, GUI-D47).

Four threads with four kinds are opened here, and the fact under test is the
same in all of them: the material about *driving the board* crosses to the help
thread and to no other kind. Anchoring no decision is deliberately not the test.
The map thread anchors none either and is about the plan, and a thread opened
from a notice that targeted nothing anchors none while being about what that
notice said -- so the rule is stated positively on the kind, which is what stops
a kind added later from inheriting the material by saying nothing.

The legend is the other half of what a thread agent is given. It is a property
of the role rather than of the channel, so it rides the standing brief every
thread turn carries -- including the sentence about `proposed_by` and `verdict`,
without which an agent asked why the board moved composes a cause out of
`prereqs` while the actual rationale sits unquoted in the same bytes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from conftest import decision, document, handoff, turn

from grillui.tiers import BOARD_LEGEND

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

PLAN = [decision("d1", "Which storage?"), decision("d2", "How is it compacted?")]

REFERENCE = "Park a thread to set it aside; folding hands its conclusion to the map agent."
NOTICED = "The store choice leaves recovery resting on compaction."

# One turn that puts both a notice and a proposal on d1, so there is one of each
# for the human to open a thread from.
SAID = document(
    text="",
    updates=[
        {"kind": "informational", "target": "d1", "text": NOTICED},
        {"kind": "invalidate", "target": "d1", "why": "the store makes this moot"},
    ],
)


def waiting(session: Session, kind: str) -> str:
    """The id of the one queue item of this kind."""
    found = [one for one in session.board()["pending"] if one["kind"] == kind]
    assert len(found) == 1, session.board()["pending"]
    return str(found[0]["id"])


def say(page: Page, text: str) -> None:
    page.fill("#ft-say", text)
    page.click('[data-act="draftsay"]')
    page.wait_for_timeout(600)


def threads_of(session: Session) -> dict[str, dict[str, Any]]:
    return {one["id"]: one for one in session.image2()["threads"]}


def dispatched(session: Session) -> dict[str, dict[str, Any]]:
    """The last context each channel's agent was given."""
    return {one["channel"]: one for one in session.dispatches()}


def test_only_the_help_thread_is_handed_the_material_about_driving_the_board(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a session briefed with reference material about the board
    When the human opens a thread from a notice on a decision, a thread from a
         change waiting on that decision, the thread about the map itself, and
         the help thread
    Then the notice thread is kinded `notice` and anchored to the decision the
         notice targeted, the map thread anchors nothing, none of the three
         carries the reference material, and the help thread -- which anchors
         nothing either -- carries it.
    """
    session = launcher(handoff=handoff(PLAN, help_reference=REFERENCE))
    session.script_codex(turn(SAID))
    session.stub.script("On the notice.", "On the change.", "On the map.", "On the board itself.")
    page = board(session)

    page.click('#col-d2 [data-act="pick"][data-opt="a"]')
    session.settled()

    # A thread from the notice, opened where the human meets it: on the decision
    # it was addressed to. The notifications panel offers the same gesture over
    # the log's notification stream, which numbers its items separately from the
    # queue these ids come from.
    page.click('[data-act="toggle"][data-id="d1"]')
    page.wait_for_timeout(400)
    page.click(
        f'#col-d1 [data-act="discussnotice"][data-uid="{waiting(session, "informational")}"]'
    )
    page.wait_for_timeout(600)
    session.settled()

    # A thread from the change waiting on that same decision.
    page.click('[data-act="inbox"]')
    page.wait_for_timeout(400)
    page.click(f'#overlay [data-act="discuss"][data-uid="{waiting(session, "invalidate")}"]')
    page.wait_for_timeout(600)
    session.settled()

    # The thread about the map itself, and the one about the board.
    page.click('[data-act="mapthread"]')
    page.wait_for_timeout(400)
    say(page, "Change d2 to ask about retention instead.")
    session.settled()
    page.click('[data-act="help"]')
    page.wait_for_timeout(400)
    say(page, "What does folding a thread do?")
    session.settled()

    opened = threads_of(session)
    kinds = {one["kind"]: one for one in opened.values()}
    assert set(kinds) == {"notice", "pending", "map", "help"}, sorted(kinds)
    assert kinds["notice"]["decision"] == "d1", kinds["notice"]
    assert kinds["pending"]["decision"] == "d1", kinds["pending"]
    assert kinds["map"]["decision"] is None, kinds["map"]
    assert kinds["help"]["decision"] is None, kinds["help"]

    # The material crosses to one kind and to no other, whether or not the
    # thread anchors a decision.
    given = dispatched(session)
    for kind in ("notice", "pending", "map"):
        channel = kinds[kind]["id"]
        assert given[channel]["help_reference"] is None, f"{kind} was handed the board's manual"
    assert given[kinds["help"]["id"]]["help_reference"] == REFERENCE, given[kinds["help"]["id"]]
    assert given["map"]["help_reference"] is None, "the grill-master was handed the board's manual"


def test_every_thread_turn_is_briefed_with_the_legend_that_says_who_proposed_a_move(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a thread on a decision
    When its agent takes a turn
    Then the standing brief it was sent carries the board legend whole, including
         the sentence saying that a change in `history` names who proposed it and
         what was ruled -- so an agent asked why the board moved quotes the record
         rather than inferring a cause from the shape of the graph.
    """
    session = launcher(handoff=handoff(PLAN))
    session.stub.script("Retention is what that turns on.")
    page = board(session)

    page.click('[data-act="threads"][data-id="d1"]')
    page.wait_for_timeout(400)
    say(page, "Why did the board move here?")
    session.settled()

    assert len(session.stub.calls) == 1, session.stub.calls
    brief = session.stub.system_of(0)
    assert BOARD_LEGEND in brief, brief
    assert "`proposed_by`, the agent whose queued update the human's apply landed" in brief
    assert "an entry carrying neither is a move nobody proposed and no ruling produced" in brief
