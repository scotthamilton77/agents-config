"""The map's Codex thread across a session's turns (GMR-A11).

One turn is one process, so the conversation only exists because its identity is
written into the session directory and read back on the next turn. What that
buys is the provider's cache, and what it costs is arithmetic: `turn.completed`
reports the thread's input *so far*, not this turn's, so a driver recording it
raw would warn about a filling window on the third turn of a small conversation.

The two ways that arithmetic goes wrong are both driven here. An attempt that
spent tokens and produced no turn has to move the baseline anyway, or the next
accepted turn is billed for it; and a total belonging to a different thread has
to start the count again, because subtracting one conversation's total from
another's is arithmetic about two different windows.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from conftest import agent_turns, decision, document, handoff

from grillui.drivers import CODEX_RESUME_FILE

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

PLAN = [decision(f"d{index}", f"Question {index}?") for index in range(1, 6)]

COLD = "th-A"
REPLACED = "th-B"


def answer(page: Page, node: str) -> None:
    page.click(f'#col-{node} [data-act="pick"][data-opt="a"]')


def spoke(session: Session) -> list[int | None]:
    """What each map turn recorded as the tokens it was given."""
    return [one.payload.get("prompt_tokens") for one in agent_turns(session.entries())]


def test_the_map_keeps_one_codex_thread_and_bills_each_turn_its_own_share(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a map seated on Codex, answering five decisions in a row
    When the first turn opens a thread cold, the second resumes it, the third
         spends tokens and produces no turn at all, the fourth resumes again and
         the fifth comes back on a different thread
    Then every turn after the first reads `exec resume <thread>`, the identity is
         in the session directory rather than in memory, and each turn records
         the delta of the running total -- including across the failed attempt,
         which moves the baseline it did not produce a turn for, and across the
         replacement, which starts the count again.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(
        {"reply": document("Cold."), "thread_id": COLD, "usage_input": 1000},
        {"reply": document("Resumed."), "thread_id": COLD, "usage_input": 2500},
        # Tokens spent, nothing said: the stream carries the total and no agent
        # message. The turn fails, and the baseline still has to move.
        {"reply": "", "thread_id": COLD, "usage_input": 4000, "no_message": True},
        {"reply": document("Resumed again."), "thread_id": COLD, "usage_input": 4500},
        {"reply": document("On another thread."), "thread_id": REPLACED, "usage_input": 300},
    )
    page = board(session)

    answer(page, "d1")
    session.settled()
    # The identity is on disk after the first turn, keyed by channel, which is
    # what lets the next process resume rather than pay for a cold open.
    chains = json.loads((session.directory / CODEX_RESUME_FILE).read_text(encoding="utf-8"))
    assert chains == {"map": COLD}, chains

    for node in ("d2", "d3", "d4", "d5"):
        answer(page, node)
        session.settled()

    calls = session.codex_calls()
    assert len(calls) == 5, f"{len(calls)} turns reached the seat"
    assert calls[0]["resume"] is None, "the first turn was not opened cold"
    assert [one["resume"] for one in calls[1:]] == [COLD, COLD, COLD, COLD], [
        one["resume"] for one in calls
    ]
    assert calls[1]["argv"][:3] == ["exec", "resume", COLD], calls[1]["argv"][:4]
    assert all(one["violations"] == [] for one in calls), [one["violations"] for one in calls]

    # Four turns landed and one did not, and each landed one is billed its own
    # share of a total that only ever grows.
    assert spoke(session) == [1000, 1500, 500, 300], spoke(session)
    errors = [
        one.payload["detail"]
        for one in session.entries()
        if one.kind == "status" and one.payload.get("phase") == "error"
    ]
    assert len(errors) == 1, errors
    assert "printed no turn" in errors[0], errors[0]

    # The replacement is what the channel now resumes, so nothing goes on
    # subtracting against a conversation that has been left behind.
    chains = json.loads((session.directory / CODEX_RESUME_FILE).read_text(encoding="utf-8"))
    assert chains == {"map": REPLACED}, chains
