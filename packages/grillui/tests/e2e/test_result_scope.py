"""What a ruling may change on its own, through the real launch path.

The human takes an option that puts a decision in question, and the expert
rules on it. What the ruling changes on that decision lands as it arrives, and
the decision comes back answerable in its new shape. Anything else the ruling
proposes waits in the inbox, where its row shows what is there now beside what
would replace it.

A switch on the inbox lets the page apply such a proposal for the human when
every part of it touches a decision they have not answered. It is off unless
they turn it on, and it lives in their browser rather than on the log: what the
log sees is their apply, marked as the switch's.
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
    decision("d3", "What is retained?", body="Everything, for now."),
    decision("d4", "Who reads it?"),
    decision(
        "d5",
        "Where does it live?",
        options=[option("a", "On disk", ["d2"]), option("b", "In memory")],
    ),
]

REVISED_D2 = "How is the append-only log compacted?"
REVISED_D3 = "What does the append-only log retain?"
REVISED_D3_BODY = "A log keeps everything unless something says otherwise."
NEW_NODE = "Who owns the compaction job?"

# The ruling on d2 changes d2, and reaches past it twice: it rewrites d3, which
# nobody has answered, and it adds a decision nobody asked for.
RESULT = document(
    "",
    updates=[
        {"kind": "revise", "target": "d2", "title": REVISED_D2},
        {"kind": "revise", "target": "d3", "title": REVISED_D3, "body": REVISED_D3_BODY},
        {
            "kind": "add-node",
            "title": NEW_NODE,
            "options": [{"id": "a", "text": "The backend"}, {"id": "b", "text": "An operator"}],
        },
    ],
    rulings=[ruling("d2", "revise", "an append-only log is compacted differently")],
)

# How long a page is given to act on what just arrived, when the scenario is
# asserting that it did nothing. Several of the page's polls fit inside it.
QUIET = 1.5


def pick(page: Page, node: str, chosen: str = "a") -> None:
    page.click(f'#col-{node} [data-act="pick"][data-opt="{chosen}"]')


def gesture_on(entries: list[LogEntry], node: str) -> int:
    return next(
        one.seq for one in entries if one.kind == "answer" and one.payload["target"] == node
    )


def applies(entries: list[LogEntry]) -> list[LogEntry]:
    return [one for one in entries if one.kind == "apply"]


def queued(session: Session) -> set[tuple[str, str]]:
    return {(one["kind"], one["target"]) for one in session.board()["pending"]}


def switch_on(page: Page) -> None:
    """Turn the inbox's switch on, the way the human does, and close the inbox."""
    page.click(".pendbtn")
    page.click('[data-act="autoapply"]')
    assert page.locator('[data-act="autoapply"]').is_checked()
    page.click('[data-act="closepanel"]')


def wait_for_apply(session: Session) -> LogEntry:
    deadline = time.monotonic() + TURN_TIMEOUT
    while time.monotonic() < deadline:
        found = applies(session.entries())
        if found:
            return found[0]
        time.sleep(POLL)
    stuck = "the page never applied the proposal"
    raise AssertionError(stuck)


def row_for(page: Page, kind: str, target: str | None = None) -> Any:
    rows = page.locator(".pending-row").filter(has=page.locator(f'.did:text-is("{kind}")'))
    if target is not None:
        rows = rows.filter(has=page.locator(f'strong:text-is("{target}")'))
    assert rows.count() == 1, page.locator(".pending-list").inner_html()
    return rows.first


def test_pnd_a4_a_ruling_lands_on_its_target_and_queues_the_rest_with_before_and_after(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given d1's option a marks d2, and an expert seat whose ruling revises d2,
         revises d3 and adds a decision
    When the human takes that option and the ruling lands
    Then d2 carries its new title with no apply, its history names the impact
         task and no proposer, and it is answerable again; the revise of d3 and
         the new decision wait in the inbox; and the inbox row for d3 pairs each
         field's current value with the proposed one, while the row for the new
         decision shows what it proposes with no before side at all.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_claude(turn(RESULT))
    page = board(session)

    pick(page, "d1")
    session.settled()

    entries = session.entries()
    image = session.image2()
    revised = [one for one in image["history"]["d2"] if one["kind"] == "revise"]
    assert len(revised) == 1, image["history"]["d2"]
    assert revised[0]["task"] == f"impact-{gesture_on(entries, 'd1')}-d2", revised
    assert "proposed_by" not in revised[0], revised
    d2 = next(one for one in image["decisions"] if one["id"] == "d2")
    assert d2["title"] == REVISED_D2
    assert "d2" in image["frontier"]
    assert ("revise", "d3") in queued(session)
    assert "add-node" in {kind for kind, _ in queued(session)}
    page.wait_for_selector('#col-d2 [data-act="pick"]', timeout=BOARD_TIMEOUT)

    page.click(".pendbtn")
    page.wait_for_selector(".pending-row", timeout=BOARD_TIMEOUT)
    d3 = row_for(page, "revise", "d3")
    title = d3.locator('.diff [data-field="title"]')
    assert title.locator(".was").inner_text() == "What is retained?"
    assert title.locator(".now").inner_text() == REVISED_D3
    body = d3.locator('.diff [data-field="body"]')
    assert body.locator(".was").inner_text() == "Everything, for now."
    assert body.locator(".now").inner_text() == REVISED_D3_BODY
    assert d3.locator('.diff [data-field="options"]').count() == 0

    added = row_for(page, "add-node")
    assert added.locator('.diff [data-field="title"] .now').inner_text() == NEW_NODE
    assert "The backend" in added.locator('.diff [data-field="options"] .now').inner_text()
    assert added.locator(".diff .was").count() == 0, added.inner_html()


def test_pnd_a12_with_the_switch_off_a_qualifying_proposal_waits_in_the_inbox(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a board on which nobody has touched the inbox's switch
    When a ruling's proposal arrives whose every part touches a decision the
         human has not answered
    Then the switch reads off, nothing applies it, and it waits in the inbox.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_claude(turn(RESULT))
    page = board(session)

    pick(page, "d1")
    session.settled()
    time.sleep(QUIET)

    assert not applies(session.entries())
    assert ("revise", "d3") in queued(session)
    page.click(".pendbtn")
    assert not page.locator('[data-act="autoapply"]').is_checked()


def test_pnd_a12_with_the_switch_on_a_qualifying_proposal_is_applied_as_the_switchs(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given the human has turned the inbox's switch on
    When a ruling's proposal arrives whose every part touches a decision they
         have not answered -- a revise of d3 and a new decision
    Then the log carries one apply naming both, marked `by_preference: true`,
         from the human; both land; and the inbox is empty.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_claude(turn(RESULT))
    page = board(session)
    switch_on(page)

    pick(page, "d1")
    applied = wait_for_apply(session)
    session.settled()

    assert applied.actor == "human"
    assert applied.payload["by_preference"] is True
    kinds = sorted(one["kind"] for one in applied.payload["updates"])
    assert kinds == ["add-node", "revise"], applied.payload
    image = session.board()
    assert next(one for one in image["decisions"] if one["id"] == "d3")["title"] == REVISED_D3
    assert NEW_NODE in {one["title"] for one in image["decisions"]}
    assert not [one for one in image["pending"] if one["kind"] in {"revise", "add-node"}]


def test_pnd_a12_a_proposal_touching_an_answer_or_carrying_an_unsettle_waits_either_way(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given the switch on, and d3 already answered by the human
    When one ruling proposes a revise of d3, and a later one proposes an
         unsettle of d4, which nobody has answered
    Then neither is applied: the first touches an answer, and the second is an
         unsettle, which the switch never applies.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("")))
    session.script_claude(
        turn(
            document(
                "",
                updates=[{"kind": "revise", "target": "d3", "title": REVISED_D3}],
                rulings=[ruling("d2", "stands", "asked either way")],
            )
        ),
        turn(
            document(
                "",
                updates=[{"kind": "unsettle", "target": "d4", "why": "worth asking again"}],
                rulings=[ruling("d2", "stands", "asked either way")],
            )
        ),
    )
    page = board(session)
    switch_on(page)

    pick(page, "d3", "b")
    session.settled()
    pick(page, "d1")
    session.settled()
    page.wait_for_selector('#col-d5 [data-act="pick"]', timeout=BOARD_TIMEOUT)
    pick(page, "d5")
    session.settled()
    time.sleep(QUIET)

    assert not applies(session.entries())
    assert {("revise", "d3"), ("unsettle", "d4")} <= queued(session)
