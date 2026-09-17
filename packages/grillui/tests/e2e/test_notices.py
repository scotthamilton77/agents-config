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

import json
from typing import TYPE_CHECKING

from conftest import BOARD_TIMEOUT, RENDER, decision, document, handoff, option, ruling, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page, Route

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


def open_panel(page: Page) -> list[str]:
    """Open the notification panel and read every note it lists, in order."""
    page.click('[data-act="notifications"]')
    page.wait_for_selector("#overlay .inbox-item", timeout=BOARD_TIMEOUT)
    return page.locator("#overlay .inbox-item").all_inner_texts()


def caught_up(session: Session, page: Page) -> None:
    """Wait until the page has read every entry the log holds.

    What is counted below is counted in two reads -- the bell, and the surfaces
    the bell is a count of -- and a turn closes over several entries. A page
    still taking them in answers the two reads from two different logs, so the
    wait is on the page's own cursor rather than on the turn having landed.
    """
    landed = session.entries()[-1].seq
    page.wait_for_function("at => window.WIRE && WIRE.cursor >= at", arg=landed)


def unread_pill(page: Page) -> str:
    """What the bell says is unread, as the shell renders it."""
    said = page.locator('[data-act="notifications"]').get_attribute("data-unread")
    assert said is not None
    return said


def test_an_untargeted_message_is_still_in_the_panel_after_a_reload(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a turn whose message names no decision, so the panel is the only
         surface it has
    When the human reloads the page
    Then the panel lists exactly what it listed before -- same notes, same text,
         same timestamps, same unread marks -- and the bell says the same number
         as it did; and once they mark everything read, a second reload has the
         panel listing the message as read with nothing unread.

    A list built only from what arrived after this page did loses that message
    on the first reload, while the log goes on carrying it and the bell goes on
    counting it off the queue.
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
                ],
                rulings=[ruling("d2", "revise", COMPACTION)],
            )
        )
    )
    page = board(session)

    page.click('#col-d1 [data-act="pick"][data-opt="a"]')
    session.settled()
    # The bell is the page's own word on having read the turn, so the scenario
    # waits on it rather than on a clock.
    page.wait_for_selector(
        '[data-act="notifications"]:not([data-unread="0"])', timeout=BOARD_TIMEOUT
    )
    caught_up(session, page)
    before = open_panel(page)
    counted = unread_pill(page)
    assert [one for one in before if STORY in one], before
    assert sum(STORY in one for one in before) == 1, before
    # The bell and the panel are counting the same things: every note here is
    # one the board has nowhere to show, so the unread ones are the whole count.
    assert page.locator("#overlay .inbox-item.unread").count() == int(counted), before

    page.reload()
    page.wait_for_selector(
        f'[data-act="notifications"][data-unread="{counted}"]', timeout=BOARD_TIMEOUT
    )
    # Same notes, in the same order, saying the same thing at the same clock and
    # wearing the same unread marks. A note rebuilt some other way would differ
    # here before it differed anywhere the human could name.
    assert open_panel(page) == before

    page.click('#overlay [data-act="markall"]')
    page.wait_for_selector('[data-act="notifications"][data-unread="0"]', timeout=BOARD_TIMEOUT)

    page.reload()
    page.wait_for_selector('[data-act="notifications"][data-unread="0"]', timeout=BOARD_TIMEOUT)
    # Still listed, and listed as something already dealt with: the message does
    # not leave the panel on being read, and does not come back as news.
    after = open_panel(page)
    assert sum(STORY in one for one in after) == 1, after
    assert page.locator("#overlay .inbox-item.unread").count() == 0, after


# A message naming a decision, so the board has somewhere to draw it: on that
# decision's own block.
NOTICED = "Compaction is now a question about the log, and nothing here says what it drops."
# What the board falls back to when it holds a queued notice and not the entry
# that authored it: the kind and the target, in place of the words.
PLACEHOLDER = "informational on d2"
# The page's log read, answered with an empty tail. That is the state the page
# is in for as long as the board image is ahead of the log, and holding it still
# is what lets a scenario read the render it produces: a window that closes on
# its own closes before anything can be asserted about it.
UPDATE_READ = "**/updates*"
HELD_LOG = {"seq": 0, "entries": []}


def accounted(page: Page) -> tuple[int, int]:
    """What the bell says is unread, against the unread messages the human can
    find: the ones drawn on the board, and the ones listed in the panel."""
    page.click('[data-act="notifications"]')
    page.wait_for_selector("#overlay .slide", timeout=BOARD_TIMEOUT)
    found = (
        page.locator("#column .infonote .unreadmark").count()
        + page.locator("#overlay .inbox-item.unread").count()
    )
    page.click('#overlay [data-act="closepanel"]')
    return int(unread_pill(page)), found


def test_a_queued_notice_is_neither_drawn_nor_counted_before_its_words_arrive(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a turn that writes a message on d2 and a message the board has nowhere
          to show, both of which reach the page as queued notices
    When the page comes back with the board image ahead of the log, so the queue
         names notices whose entries the page has not read
    Then none of them is drawn, no placeholder stands in for anyone's words, and
         the bell counts nothing the board and the panel cannot account for --
         and they come back with their own words, and their own count, once the
         log arrives.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_claude(
        turn(
            document(
                STORY,
                updates=[{"kind": "informational", "target": "d2", "text": NOTICED}],
            )
        )
    )
    page = board(session)

    page.click('#col-d1 [data-act="pick"][data-opt="a"]')
    session.settled()
    page.wait_for_selector(f'#col-d2 .infonote:has-text("{NOTICED}")', timeout=BOARD_TIMEOUT)
    page.wait_for_selector(
        '[data-act="notifications"]:not([data-unread="0"])', timeout=BOARD_TIMEOUT
    )
    caught_up(session, page)
    before = accounted(page)
    assert before[0] == before[1], before

    epoch = session.state()["epoch"]

    def empty_tail(route: Route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"epoch": epoch, **HELD_LOG}),
        )

    page.route(UPDATE_READ, empty_tail)
    page.reload()
    page.wait_for_selector("#col-d2", timeout=BOARD_TIMEOUT)
    # The page's own word that it has read a board and a log, which is the
    # render everything below is asserted against.
    page.wait_for_function("() => window.WIRE && WIRE.hydrated", timeout=BOARD_TIMEOUT)

    drawn = page.locator("#column").inner_text()
    assert page.locator(".infonote").count() == 0, drawn
    assert PLACEHOLDER not in drawn, drawn
    assert NOTICED not in drawn, drawn
    assert accounted(page) == (0, 0), drawn

    page.unroute(UPDATE_READ, empty_tail)
    page.wait_for_selector(f'#col-d2 .infonote:has-text("{NOTICED}")', timeout=BOARD_TIMEOUT)
    caught_up(session, page)
    # Nothing was lost by waiting: the same messages, unread the same way, and
    # the bell back on the number it left.
    assert accounted(page) == before
    assert page.locator("#col-d2 .infonote .unreadmark").count() == 1
    listed = open_panel(page)
    assert sum(STORY in one for one in listed) == 1, listed
