"""A failed ruling holds its decision until the human retries it, through the
real launch path.

The expert sends a document naming a decision this board has never had, twice,
so the appender refuses the turn and the ladder runs out. The decision the
ruling was about stays waiting, with the failure named on it and a control to
ask again. The retry is the same ruling asked over the board as it now stands,
and when it lands the decision takes its new shape and is answerable again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conftest import BOARD_TIMEOUT, decision, document, handoff, option, ruling, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

PLAN = [
    decision(
        "d1",
        "Which storage?",
        options=[option("a", "Append-only log", ["d2"]), option("b", "Table")],
    ),
    decision("d2", "How is it compacted?"),
    decision("d3", "What is retained?"),
]

RETITLED = "How is the append-only log compacted?"

# A schema-valid document the appender refuses: it revises a decision this
# board has never had.
UNKNOWN = document(
    "Ruled.",
    updates=[{"kind": "revise", "target": "d9", "title": "Nowhere", "why": "moved"}],
    rulings=[ruling("d2", "revise")],
)
RULED = document(
    "Ruled.",
    updates=[{"kind": "revise", "target": "d2", "title": RETITLED, "why": "the log moved it"}],
    rulings=[ruling("d2", "revise")],
)


def test_pnd_a5_a_refused_ruling_holds_its_decision_until_the_retry_lands(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given an option marking d2, and an expert whose document the appender
         refuses on both of its asks
    When the human takes that option, and then presses retry on d2
    Then d2 waits with the failure named on it -- the seat, the board's reason,
         and when -- and no answer control; the retry is seated on the expert
         and its document retitles d2, which then takes an answer again with
         history naming the retry's task.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_claude(turn(UNKNOWN), turn(UNKNOWN), turn(RULED))
    page = board(session)

    page.click('#col-d1 [data-act="pick"][data-opt="a"]')
    session.settled()
    page.wait_for_selector("#col-d2 .task-notice.failed", timeout=BOARD_TIMEOUT)

    held = next(one for one in session.board()["decisions"] if one["id"] == "d2")
    failed = held["waiting"]["failed"]
    assert failed["seat"] == "heavy", failed
    assert "unknown node" in failed["cause"], failed
    column = page.locator("#col-d2")
    assert column.locator('[data-act="pick"]').count() == 0, column.inner_html()
    said = column.locator(".task-notice").inner_text()
    assert "heavy" in said, said
    assert "unknown node" in said, said

    column.locator('[data-act="retry"]').click()
    session.settled()
    page.wait_for_selector('#col-d2 [data-act="pick"]', timeout=BOARD_TIMEOUT)

    retried = [
        item
        for entry in session.entries()
        if entry.kind == "status"
        for item in entry.payload.get("tasks") or []
        if item.get("retries") == held["waiting"]["task"]
    ]
    assert len(retried) == 1, retried
    assert retried[0]["seat"] == "heavy"
    d2 = next(one for one in session.board()["decisions"] if one["id"] == "d2")
    assert d2["title"] == RETITLED, d2
    assert "waiting" not in d2, d2
    history = session.image2()["history"]["d2"]
    assert history[-1]["task"] == retried[0]["id"], history[-1]
    assert len(session.claude_calls()) == 3
