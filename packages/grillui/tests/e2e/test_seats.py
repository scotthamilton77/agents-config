"""Who takes each channel's turn, and what moves a channel to the expert (GMR-A5).

The seating is configuration, so what these scenarios prove is that the
configuration reaches the transport: a map turn arrives at the `codex`
executable and a thread turn at the OpenRouter endpoint, each carrying the model
and the effort the session was configured with. Both are the *first* rung, which
is what the lane naming `fast` on both is about -- a channel seated on a
reasoning model is not on a third rung, and it still has the same expert above
it.

The transfer is the human's, and pressing the control is not the gesture: the
page arms the channel and the flag rides on their next turn, which is what makes
a transfer something the log records rather than something a browser remembers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conftest import agent_turns, decision, document, handoff, lane, option, turn

from grillui.tiers import (
    DEFAULT_FAST_MODEL,
    DEFAULT_HEAVY_EFFORT,
    DEFAULT_HEAVY_MODEL,
    DEFAULT_MAP_EFFORT,
    DEFAULT_MAP_MODEL,
    MAP_TRANSPORT_ENV,
    OPENROUTER_TRANSPORT,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

PLAN = [
    decision(
        "d1", "Which storage?", options=[option("a", "Append-only log"), option("b", "Table")]
    ),
    decision("d2", "How is it compacted?"),
]

MAP_SAID = "The store is settled; compaction is the next question."
THREAD_SAID = "Retention is what that turns on."
ASKED = "What does compaction cost us here?"


def answer(page: Page, node: str, chosen: str, note: str = "") -> None:
    """Answer a decision the way the human does: a note in its own box, then the
    option, which records both in one entry."""
    if note:
        page.fill(f"#ft-{node}", note)
        page.wait_for_timeout(150)
    page.click(f'#col-{node} [data-act="pick"][data-opt="{chosen}"]')


def start_thread(page: Page, node: str, said: str) -> None:
    """Open a thread on a decision and say the first thing in it.

    Through the decision's own thread control, which is in its header whatever
    state the decision is in. The `newthread` control says the same thing but
    only inside an expanded decision, so a scenario driving it is driving the
    expansion as well as the gesture it is about.
    """
    page.click(f'[data-act="threads"][data-id="{node}"]')
    page.wait_for_timeout(400)
    page.fill("#ft-say", said)
    page.click('[data-act="draftsay"]')


def test_each_channel_takes_its_turn_on_the_seat_the_session_configured(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a session on the shipped seating
    When the human answers a decision and then opens a thread
    Then the map's turn went to the `codex` executable on the map model at the
         map effort, the thread's went to the OpenRouter endpoint on the fast
         model with no effort, both turns are attributed to the `fast` rung, and
         the map's transfer control offers the expert at first paint.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document(MAP_SAID)))
    session.stub.script(THREAD_SAID)
    page = board(session)

    # Before a gesture: the map is on the first rung and the control offers the
    # rung above it.
    control = page.locator('[data-act="transfer"][data-channel="map"]')
    assert control.count() == 1, f"{control.count()} map transfer controls"
    assert control.inner_text().strip().endswith("Transfer to expert"), control.inner_text()

    answer(page, "d1", "a", "Append-only log, for recovery.")
    session.settled()
    start_thread(page, "d2", ASKED)
    session.settled()

    # The map's turn: one process, and the seat it was configured with.
    calls = session.codex_calls()
    assert len(calls) == 1, f"the map seat was called {len(calls)} times"
    assert calls[0]["model"] == DEFAULT_MAP_MODEL, calls[0]["model"]
    assert calls[0]["effort"] == DEFAULT_MAP_EFFORT, calls[0]["effort"]
    assert calls[0]["violations"] == [], calls[0]["violations"]
    assert not session.claude_calls(), "the expert took a turn nobody asked for"

    # The thread's turn: the endpoint the session was configured with, on the
    # fast model, and no effort was sent at all -- the transport takes none.
    assert len(session.stub.calls) == 1, session.stub.calls
    body = session.stub.calls[0]["body"]
    assert body["model"] == DEFAULT_FAST_MODEL, body["model"]
    assert "reasoning" not in body and "effort" not in body, body

    # Both rungs are the first one, and both replies carry the seat beside it.
    entries = session.entries()
    spoke = agent_turns(entries)[-1]
    assert (spoke.payload["tier"], spoke.payload["model"]) == ("fast", DEFAULT_MAP_MODEL)
    assert spoke.payload["effort"] == DEFAULT_MAP_EFFORT, spoke.payload
    threads = [one for one in entries if one.actor == "thread-agent"]
    assert len(threads) == 1, threads
    assert (threads[0].payload["tier"], threads[0].payload["model"]) == (
        "fast",
        DEFAULT_FAST_MODEL,
    )
    assert "effort" not in threads[0].payload, (
        "the threads' seat was attributed an effort its transport never sent"
    )
    assert ("composing", "fast") in lane(entries, "map")
    assert ("composing", "fast") in lane(entries, threads[0].channel)


def test_reseating_the_map_puts_its_first_turn_on_the_threads_seat(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a session that seats the map on the threads' transport
    When the human answers a decision
    Then the map's very first turn goes to the OpenRouter endpoint rather than
         to `codex`, and it is attributed to that model carrying no effort --
         the transport is sent none, whatever the map effort is configured to be.
    """
    session = launcher(handoff=handoff(PLAN), config={MAP_TRANSPORT_ENV: OPENROUTER_TRANSPORT})
    session.stub.script(document(MAP_SAID))
    page = board(session)

    answer(page, "d1", "a")
    session.settled()

    assert not session.codex_calls(), "the map turn reached `codex` on a reseated map"
    assert len(session.stub.calls) == 1, session.stub.calls
    spoke = agent_turns(session.entries())[-1]
    assert (spoke.payload["tier"], spoke.payload["model"]) == ("fast", DEFAULT_MAP_MODEL)
    assert "effort" not in spoke.payload, spoke.payload


def test_the_human_moves_a_channel_up_and_back_down_by_their_own_gesture(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a session on the shipped seating
    When the human presses the map's transfer control, answers, presses it
         again, and answers again
    Then the first answer carries the transfer and is composed by the `claude`
         executable at the expert seat, the control then offers the way back,
         and the second answer returns the channel to the seat it started on.

    Pressing is not the gesture and must not be: the flag rides on the human's
    own next turn, so what moved the channel is in the log rather than in a
    browser's memory.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_claude(turn(document("The expert took this one.")))
    session.script_codex(turn(document("And the first rung took this one.")))
    page = board(session)

    page.click('[data-act="transfer"][data-channel="map"]')
    page.wait_for_timeout(300)
    answer(page, "d1", "a")
    session.settled()

    moved = next(one for one in session.entries() if one.kind == "answer")
    assert moved.payload["transfer"] is True, moved.payload
    assert len(session.claude_calls()) == 1, session.claude_calls()
    assert session.claude_calls()[0]["model"] == DEFAULT_HEAVY_MODEL
    assert session.claude_calls()[0]["effort"] == DEFAULT_HEAVY_EFFORT
    assert not session.codex_calls(), "the first rung took a turn on an escalated channel"
    spoke = agent_turns(session.entries())[-1]
    assert spoke.payload["tier"] == "heavy", spoke.payload
    assert spoke.payload["followed_transfer"] is True, spoke.payload

    # The control now offers the way back, and the way back is theirs.
    page.wait_for_timeout(600)
    control = page.locator('[data-act="transfer"][data-channel="map"]')
    assert control.inner_text().strip().endswith("Return to fast agent"), control.inner_text()
    control.click()
    page.wait_for_timeout(300)
    answer(page, "d2", "a")
    session.settled()

    back = [one for one in session.entries() if one.kind == "answer"][-1]
    assert back.payload["transfer"] is False, back.payload
    assert len(session.claude_calls()) == 1, "the expert took a turn after the way back"
    assert len(session.codex_calls()) == 1, session.codex_calls()
