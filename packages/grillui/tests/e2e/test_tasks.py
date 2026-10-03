"""A ruling in flight holds what it rules on, through the real launch path.

The human takes an option that puts other decisions in question, and the
expert seat is sent to rule on them. Until it does, those decisions are
waiting: the board names what they wait on and offers no answer to them, while
everything the ruling is not about stays answerable. A later answer marking one
of them takes the ruling over, and the earlier turn's result for it is dropped.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from conftest import BOARD_TIMEOUT, decision, document, handoff, option, ruling, turn
from harness import POLL, TURN_TIMEOUT

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

    from grillui.schemas import LogEntry

PLAN = [
    decision(
        "d1",
        "Which storage?",
        options=[option("a", "Append-only log", ["d2"]), option("b", "Table")],
    ),
    decision("d2", "How is it compacted?"),
    decision("d3", "What is retained?"),
    decision(
        "d4",
        "Who reads it?",
        options=[option("a", "Only the backend", ["d2"]), option("b", "Anyone")],
    ),
]

# Long enough for a scenario to look at the board and make a gesture while the
# expert is still weighing, and well inside the harness's turn budget.
HELD = 4


def pick(page: Page, node: str, chosen: str = "a") -> None:
    page.click(f'#col-{node} [data-act="pick"][data-opt="{chosen}"]')


def tasks_named(entries: list[LogEntry]) -> list[tuple[LogEntry, dict[str, Any]]]:
    return [
        (entry, item)
        for entry in entries
        if entry.kind == "status"
        for item in entry.payload.get("tasks") or []
    ]


def map_turns_closed(session: Session, count: int) -> list[LogEntry]:
    """Wait until the map has closed this many turns, and return the log.

    The harness's own wait reads the lane's latest announcement per channel, and
    two map turns in flight at once close in either order, so it can call the
    map quiet while one of them is still running.
    """
    deadline = time.monotonic() + TURN_TIMEOUT * 2
    while time.monotonic() < deadline:
        entries = session.entries()
        closed = [
            one
            for one in entries
            if one.kind == "status"
            and one.channel == "map"
            and one.payload.get("phase") in {"replied", "error"}
        ]
        if len(closed) >= count:
            return entries
        time.sleep(POLL)
    stuck = f"the map never closed {count} turns"
    raise AssertionError(stuck)


def test_pnd_a1_a_decision_a_ruling_is_weighing_waits_on_the_board_and_says_on_what(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a board whose d1 option marks d2, and an expert seat that takes a few
         seconds over its ruling
    When the human takes that option
    Then while the ruling is in flight image 1 lists d2 as waiting on that
         gesture and seat, the frontier leaves it out, and the page shows d2
         waiting on a ruling with no answer control on it while its history and
         threads stay open; d3, which nothing is weighing, stays answerable; an
         answer to d2 from a tab that has not redrawn is refused and the page
         says so; and once the ruling lands, d2 takes an answer again.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_claude(
        turn(
            document("", rulings=[ruling("d2", "stands", "compaction is asked either way")]),
            delay=HELD,
        )
    )
    page = board(session)

    pick(page, "d1")
    page.wait_for_selector("#col-d2 .task-notice", timeout=BOARD_TIMEOUT)

    gesture = next(one.seq for one in session.entries() if one.kind == "answer")
    image = session.board()
    held = next(one for one in image["decisions"] if one["id"] == "d2")
    assert held["waiting"]["gesture"] == gesture, held
    assert held["waiting"]["seat"] == "heavy", held
    assert "d2" not in image["frontier"]
    assert "d3" in image["frontier"]

    column = page.locator("#col-d2")
    assert column.locator('[data-act="pick"]').count() == 0, column.inner_html()
    said = column.locator(".task-notice").inner_text()
    assert f"#{gesture}" in said, said
    assert "heavy" in said, said
    assert column.locator(".task-notice").get_attribute("data-task") == held["waiting"]["task"]
    assert page.locator('#col-d3 [data-act="pick"]').count() > 0
    column.locator('[data-act="history"]').click()
    page.wait_for_selector("#col-d2 .hist", timeout=BOARD_TIMEOUT)
    assert column.locator('[data-act="newthread"]').count() == 1

    # A tab that has not redrawn since the first answer still offers d2, and
    # sends exactly what its answer control would. The backend refuses it, and
    # the page says so in the banner it gives every refused gesture.
    page.evaluate('send(ev("answer", MAP, { target: "d2", answer: { option: "a", text: null } }))')
    page.wait_for_selector(".banner.refusal", timeout=BOARD_TIMEOUT)
    banner = page.locator(".banner.refusal").inner_text()
    assert "decision is waiting on a ruling" in banner, banner
    assert "not recorded" in banner, banner
    assert (
        next(one for one in session.board()["decisions"] if one["id"] == "d2")["status"] == "open"
    )

    session.settled()
    page.wait_for_selector('#col-d2 [data-act="pick"]', timeout=BOARD_TIMEOUT)
    assert "waiting" not in next(one for one in session.board()["decisions"] if one["id"] == "d2")


def test_pnd_a3_a_later_answer_takes_the_ruling_over_and_the_earlier_result_is_dropped(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given d1's marked answer in flight with its ruling on d2 still to land
    When the human answers d4, whose option also marks d2, and d1's turn then
         rules d2 invalidated
    Then d4's accepted entry supersedes d1's task on d2, d1's result for d2 never
         reaches the inbox and leaves a history line naming that task, the task
         reads superseded and is named by no closing entry, and d2 is held by
         d4's task until d4's ruling lands.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_claude(
        turn(
            document(
                "",
                updates=[
                    {"kind": "invalidate", "target": "d2", "why": "the log needs no compaction"}
                ],
                rulings=[ruling("d2", "invalidate", "the log needs no compaction")],
            ),
            delay=HELD,
        ),
        turn(document("", rulings=[ruling("d2", "stands", "a reader still needs it compacted")])),
    )
    page = board(session)

    pick(page, "d1")
    page.wait_for_selector("#col-d2 .task-notice", timeout=BOARD_TIMEOUT)
    pick(page, "d4")
    entries = map_turns_closed(session, 2)

    answers = {one.payload["target"]: one.seq for one in entries if one.kind == "answer"}
    stale = f"impact-{answers['d1']}-d2"
    fresh = f"impact-{answers['d4']}-d2"
    named = [
        (entry.payload["phase"], item["phase"])
        for entry, item in tasks_named(entries)
        if item["id"] == stale
    ]
    assert named[0] == ("composing", "composing"), named
    assert named[1] == ("accepted", "superseded"), named
    assert {phase for _, phase in named[1:]} == {"superseded"}, named
    closed = [
        (entry.payload["phase"], item["phase"])
        for entry, item in tasks_named(entries)
        if item["id"] == fresh
    ]
    assert closed == [("composing", "composing"), ("replied", "replied")], closed

    image = session.image2()
    dropped = [
        one for one in image["pending"] if one["target"] == "d2" and one["kind"] == "invalidate"
    ]
    assert not dropped, image["pending"]
    assert any(stale in one["why"] for one in image["history"]["d2"]), image["history"]["d2"]
    assert "waiting" not in next(one for one in image["decisions"] if one["id"] == "d2")
