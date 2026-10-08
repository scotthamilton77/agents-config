"""The human's own words are weighed before anything they open is offered.

An answer written in the human's own words opens the decisions that rested on
the one answered, and each of them waits on an impact task until the expert has
weighed the words against it. The expert takes that task at the task effort,
whatever the heavy effort is set to, and its brief carries the paragraph telling
it not to redesign the map without a significant reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conftest import BOARD_TIMEOUT, decision, document, handoff, lane, ruling, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

PLAN = [
    decision("d1", "Which storage?"),
    decision("d2", "How is it compacted?", prereqs=["d1"]),
    decision("d3", "What is retained?"),
]

WORDS = "An append-only log, but only until the migration lands"

# Held for a few seconds so the board can be read while the task is in flight.
HELD = 3


def test_pnd_a2_a_free_answer_waits_what_it_opens_on_the_expert_at_the_task_effort(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given d2 resting on d1, d3 resting on nothing, and a session whose heavy
         effort is set to xhigh
    When the human answers d1 in their own words
    Then one map turn opens on the expert carrying one impact task, on d2; d2
         waits while d3 stays answerable; the map's first rung is never called;
         the expert is asked at medium effort and its reply is attributed at
         medium; and the dispatch it was given, and the brief composed from it,
         carry the `Backpressure:` paragraph.
    """
    session = launcher(handoff=handoff(PLAN), config={"GRILLUI_HEAVY_EFFORT": "xhigh"})
    session.script_claude(
        turn(
            document("", rulings=[ruling("d2", "stands", "compaction is asked either way")]),
            delay=HELD,
        )
    )
    page = board(session)

    page.fill("#ft-d1", WORDS)
    page.click('[data-act="free"][data-id="d1"]')
    page.wait_for_selector("#col-d2 .task-notice", timeout=BOARD_TIMEOUT)
    assert page.locator('#col-d3 [data-act="pick"]').count() > 0

    session.settled()
    entries = session.entries()

    answer = next(one for one in entries if one.kind == "answer")
    assert answer.payload["answer"] == {"option": None, "text": WORDS}
    assert [tier for phase, tier in lane(entries, "map") if phase == "composing"] == ["heavy"]
    opened = next(
        one
        for one in entries
        if one.kind == "status" and one.channel == "map" and one.payload.get("phase") == "composing"
    )
    assert [item["target"] for item in opened.payload["tasks"]] == ["d2"]
    assert session.codex_calls() == []

    (call,) = session.claude_calls()
    assert call["effort"] == "medium", call["argv"]
    reply = next(one for one in entries if one.actor == "grill-master" and "tier" in one.payload)
    assert reply.payload["effort"] == "medium", reply.payload

    (dispatch,) = [one for one in session.dispatches() if one["channel"] == "map"]
    assert dispatch["tasks"] == [item["id"] for item in opened.payload["tasks"]]
    assert dispatch["backpressure"].startswith("Backpressure:")
    assert "\n\n" + dispatch["backpressure"] + "\n\n" in call["prompt"]
