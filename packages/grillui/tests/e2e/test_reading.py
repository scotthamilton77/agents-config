"""A thread seat that cannot answer without reading asks, and the channel hands up.

The first rung on a thread is an OpenRouter seat with no tools, and it is never
given any. What it can do is name what it would have to read; the backend takes
that as a fourth escalation condition and routes the conversation to the seat
above, which is a CLI and can read.

Two scenarios, one per policy. Under the default the human decides, so the claim
is on the page: the transfer control on that one thread offers the expert and
says what was asked for. Under `autonomous` the backend decides, so the claim is
on the lane and on the expert's own prompt -- and on the cap, because a seat that
could buy an expert turn by asking for one every turn would be spending the
human's subscription on its own say-so.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from conftest import BOARD_TIMEOUT, decision, document, handoff, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

PLAN = [decision("d1", "Which storage?"), decision("d2", "How long is it kept?")]

ASKED = "How does compaction decide what to drop?"
SAID = "That is decided by the retention window, and I have not been shown it."
WANTED = ["src/grillui/projector.py", "the vendor's retention note"]
# The seat's whole reply: its prose, and the closed key naming what it would
# have to read. Scripted as the bytes the transport returns, so what the backend
# reads is what a seat would really have sent.
ASKING = json.dumps({"text": SAID, "needs_to_read": WANTED})
SAID_AGAIN = "The window is still the thing I cannot see."
ASKING_AGAIN = json.dumps({"text": SAID_AGAIN, "needs_to_read": WANTED})
EXPERT_SAID = "Thirty days. The window is in the retention note, and it drops on age."

CONDITION = "the seat asked to read something it was not given"
# How the request reaches the seat above: its own line in the channel's
# conversation, spelled out here rather than imported, so the scenario asserts
# against the bytes an expert really receives.
REQUEST_LINE = "thread-agent: I asked to read, having no way to read it from this seat: "


def transferred(session: Session, channel: str) -> list[str]:
    """Every entry saying the policy moved this one channel to the expert."""
    return [
        str(one.payload.get("detail"))
        for one in session.entries()
        if one.kind == "status"
        and one.channel == channel
        and one.payload.get("phase") == "transferred"
    ]


def conversation(prompt: str, channel: str) -> str:
    """One channel's own turns out of a composed prompt.

    Sliced out rather than searched for whole. The board travels in the same
    prompt and carries the thread's turns inside it, so a line found anywhere
    would be found in bytes the seat above reads as the board rather than as the
    conversation it is answering.
    """
    marker = f"## This channel ({channel})"
    assert marker in prompt, "the composer's prompt lost its conversation section"
    return prompt.partition(marker)[2].partition("\n## ")[0]


def composings(session: Session, channel: str) -> list[str | None]:
    """Which tier the lane named for each turn on this channel, in order."""
    return [
        one.payload.get("tier")
        for one in session.entries()
        if one.kind == "status"
        and one.channel == channel
        and one.payload.get("phase") == "composing"
    ]


def start_thread(page: Page, node: str, said: str) -> None:
    """Open a thread on a decision and say the first thing in it."""
    page.click(f'[data-act="threads"][data-id="{node}"]')
    page.wait_for_timeout(400)
    page.fill("#ft-say", said)
    page.click('[data-act="draftsay"]')


def say(page: Page, said: str) -> None:
    """Say the next thing in the thread already open on the page.

    A different control from the one that opened it: `draftsay` starts a thread
    that does not exist yet, and once it does the same box sends into it.
    """
    page.fill("#ft-say", said)
    page.click('[data-act="say"]')


def showing(page: Page, channel: str, mode: str) -> None:
    """Wait until the page's own transfer control says this channel is on `mode`.

    Not a convenience, and not a substitute for a sleep. Every human turn is
    stamped with the tier the page believes its channel is on, and the backend
    reads that stamp as the human's own gesture -- which outranks a transfer the
    policy wrote, because the way back down is theirs. So a turn typed before the
    page has seen the policy move carries `transfer: false` and takes the channel
    straight back to the first rung. Waiting on the control is waiting on the
    exact state the next turn will carry.
    """
    page.wait_for_selector(
        f'[data-act="transfer"][data-channel="{channel}"][data-mode="{mode}"]',
        timeout=BOARD_TIMEOUT,
    )


def thread_id(session: Session) -> str:
    """The channel the human's thread was opened on, off the log."""
    opened = [one for one in session.entries() if one.kind == "thread-created"]
    assert opened, "no thread was created"
    return str(opened[0].channel)


def turns_on(session: Session, channel: str) -> list[dict[str, Any]]:
    found = [one for one in session.board()["threads"] if one["id"] == channel]
    assert found, f"no thread {channel!r} on the board"
    turns: list[dict[str, Any]] = found[0]["turns"]
    return turns


def test_the_default_policy_offers_the_hand_up_and_says_what_was_asked_for(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a session on the default policy
    When the thread's seat answers with the closed key naming two things it
         would have to read
    Then the thread's own transfer control is marked as recommended and says
         what the seat asked to read, the seat's prose is on the board as the
         turn, and nothing moved: no transfer entry, and the expert took no
         turn.

    The control is where the human meets this. A recommendation that reached the
    log and not the button is one they would have to go looking for, on a
    channel whose seat has just told them it is stuck.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    session.stub.script(ASKING)
    page = board(session)

    start_thread(page, "d2", ASKED)
    session.settled()
    channel = thread_id(session)
    page.wait_for_selector(
        f'[data-act="transfer"][data-channel="{channel}"][data-recommended="1"]',
        timeout=BOARD_TIMEOUT,
    )

    control = page.locator(f'[data-act="transfer"][data-channel="{channel}"]')
    assert control.count() == 1, f"{control.count()} transfer controls on {channel}"
    assert control.get_attribute("data-mode") == "fast", control.get_attribute("data-mode")
    offered = control.get_attribute("title") or ""
    for one in WANTED:
        assert one in offered, offered

    assert [one["text"] for one in turns_on(session, channel)] == [ASKED, SAID]
    assert transferred(session, channel) == []
    assert not session.claude_calls(), "the default policy spent an expert turn"


def test_the_autonomous_policy_hands_the_request_to_the_expert_once(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given an autonomous session whose thread seat asks to read two things
    When the human says the next thing on that thread, then takes the thread
         back to the first rung and the seat asks again
    Then the lane carries exactly one transfer on that thread, naming the
         capability condition; the turn it bought ran on the `claude` shim and
         was handed the request as its own line beside the seat's prose; and the
         second ask writes no second transfer.

    The cap is the whole of the second half. The three conditions read off the
    human's own words are standing, because the human saying the thing again is
    new evidence. This one is the seat's own request, and an uncapped version is
    a lever the cheap seat pulls whenever it would rather not answer.
    """
    session = launcher(handoff=handoff(PLAN), config={"GRILLUI_ESCALATION_POLICY": "autonomous"})
    session.script_codex(turn(document("Noted.")))
    session.script_claude(turn(EXPERT_SAID))
    session.stub.script(ASKING, ASKING_AGAIN)
    page = board(session)

    start_thread(page, "d2", ASKED)
    session.settled()
    channel = thread_id(session)
    assert transferred(session, channel) == [
        f"the escalation policy moved this channel to the expert tier: {CONDITION}"
    ]

    # The turn the transfer bought, on the seat that can read. The human types
    # it once their page knows where the channel is, which is what their turn
    # will say.
    showing(page, channel, "expert")
    say(page, "Then find it.")
    session.settled()
    calls = session.claude_calls()
    assert len(calls) == 1, calls
    said_to_the_expert = conversation(calls[0]["prompt"], channel)
    assert f"thread-agent: {SAID}" in said_to_the_expert, said_to_the_expert
    assert REQUEST_LINE + ", ".join(WANTED) in said_to_the_expert, said_to_the_expert

    # The human takes the thread back down, and the same request buys nothing.
    showing(page, channel, "expert")
    control = page.locator(f'[data-act="transfer"][data-channel="{channel}"]')
    assert control.inner_text().strip().endswith("Return to fast agent"), control.inner_text()
    control.click()
    showing(page, channel, "fast")
    say(page, "Never mind, tell me what you can.")
    session.settled()

    assert len(transferred(session, channel)) == 1, transferred(session, channel)
    assert len(session.claude_calls()) == 1, session.claude_calls()
    assert composings(session, channel) == ["fast", "heavy", "fast"]
    assert [one["text"] for one in turns_on(session, channel)][-1] == SAID_AGAIN
