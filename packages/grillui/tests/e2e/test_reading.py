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

Three more are about the transfer key itself, which is the whole of what a turn
says a tier out of. The backend moves the channel while the page is between
polls, so for a moment the human is typing into a page that still shows the
first rung, and the turn they send then is the very turn the transfer was bought
for. The second puts the human's own press inside that window, because a press
forces the next turn and no turn after it. The third is a turn this page built
and then declined to post, which spends nothing at all.

The last of those has a popped-out window beside it. The scrim lies over the
board and over nothing else, so the window a thread was popped into is where a
held board is easiest to type into without being told it is held.
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

# One exchange that asks for nothing, so a scenario can get the thread onto the
# page and the seat onto the first rung before anything moves it.
ANSWERED = "It drops whatever nothing else refers to."
PRESSED = "And how does it know what refers to what?"
# What the human types into a board that is not going to take it.
DECLINED = "Does the compaction job read the retention note itself?"

# Two ways of saying the same standing condition -- the human rejecting the
# reframing -- said differently, so a scenario about escalating twice cannot
# pass on one turn counted twice. Unlike the seat's request for something to
# read, this condition is uncapped: the human said the thing again.
IRREDUCIBLE = "You keep rewording it -- that is not the question."
IRREDUCIBLE_AGAIN = "The trade-off is what I cannot resolve."
WEIGHED = "Then it comes down to what the retention window costs."
WEIGHED_AGAIN = "It is the window against the archive bill, and nothing else."

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

    Not a convenience, and not a substitute for a sleep. The control is where a
    scenario reads what this page has managed to learn about its channel, which
    is a poll behind the log -- so a scenario asserting against the backend
    instead would be asserting against a state the human never saw.

    A turn typed while the control still names the tier the channel has left is
    not something to wait out. It carries no transfer key at all, so the log's
    own last word stands and the seat the policy bought takes the turn.
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

    # The turn the transfer bought, on the seat that can read. The page is given
    # its poll first, so this scenario is about the ordinary path; the turn typed
    # before that poll lands is the scenario at the end of this file.
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
    assert control.inner_text().strip().endswith("Return to assistant"), control.inner_text()
    control.click()
    showing(page, channel, "fast")
    say(page, "Never mind, tell me what you can.")
    session.settled()

    assert len(transferred(session, channel)) == 1, transferred(session, channel)
    assert len(session.claude_calls()) == 1, session.claude_calls()
    assert composings(session, channel) == ["fast", "heavy", "fast"]
    assert [one["text"] for one in turns_on(session, channel)][-1] == SAID_AGAIN


def freeze(page: Page) -> None:
    """Answer this page's update read with nothing, from here on.

    The stale window is held open rather than raced for. A scenario that typed
    its turn quickly enough to beat the board's poll would pass on a fast
    machine and prove nothing on a loaded one; a page whose update read returns
    an empty batch stays exactly as stale as the scenario needs it to be, and
    its transfer control is checked before the turn is typed to say so.

    Two orderings make that deterministic rather than likely. This goes in
    before the turn whose reply moves the channel, so nothing this page could
    still be reading has the move in it yet. And it returns only once the page
    has no read in flight, so the read that was open when the route went on is
    finished and every read after it is this one.
    """
    page.route(
        "**/updates*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"entries": [], "seq": 0}),
        ),
    )
    page.wait_for_function("() => window.WIRE && !window.WIRE.inflight", timeout=BOARD_TIMEOUT)


def typed_on(session: Session, channel: str) -> list[dict[str, Any]]:
    """Every entry the human spoke on one channel, as the log holds them."""
    return [
        dict(one.payload)
        for one in session.entries()
        if one.actor == "human" and one.channel == channel
    ]


def test_a_turn_typed_before_the_page_learns_of_the_transfer_composes_on_the_expert(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given an autonomous session whose page can no longer read the log
    When the thread's seat asks to read something, the policy moves that thread
         to the expert, and the human says the next thing while their page still
         shows the first rung
    Then the turn carries no claim about the tier at all, and the expert composes
         it.

    This is the turn the transfer was bought for, and it is the one most likely
    to be typed inside the window: the human has just been answered, so they are
    already writing. A page that stamped every turn with the tier it last read
    would send this one back to the first rung -- the cheap seat would answer,
    and the lane would carry a transfer that changed nothing.
    """
    session = launcher(handoff=handoff(PLAN), config={"GRILLUI_ESCALATION_POLICY": "autonomous"})
    session.script_codex(turn(document("Noted.")))
    session.script_claude(turn(EXPERT_SAID))
    session.stub.script(ANSWERED, ASKING)
    page = board(session)

    start_thread(page, "d2", ASKED)
    session.settled()
    channel = thread_id(session)
    showing(page, channel, "fast")

    # From here the page is blind, so the move below happens entirely behind it.
    freeze(page)
    say(page, PRESSED)
    session.settled()
    assert transferred(session, channel) == [
        f"the escalation policy moved this channel to the expert tier: {CONDITION}"
    ]
    showing(page, channel, "fast")

    say(page, "Then find it.")
    session.settled()

    assert composings(session, channel) == ["fast", "fast", "heavy"]
    calls = session.claude_calls()
    assert len(calls) == 1, calls
    assert REQUEST_LINE + ", ".join(WANTED) in conversation(calls[0]["prompt"], channel)
    # And the turn asked for nothing: the tier above is the log's own word about
    # this channel, not something the blind page claimed on the human's behalf.
    assert "transfer" not in typed_on(session, channel)[-1], typed_on(session, channel)[-1]


def test_a_press_is_spent_by_its_own_turn_and_the_next_one_asks_for_nothing(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given an autonomous session where the policy has moved a thread to the
          expert and the human has pressed the control to take it back
    When their press rides the next turn, that turn's reply meets the condition
         again so the policy moves the thread a second time, and the human says
         one more thing before their page has read any of it
    Then the second turn carries no transfer key, and the expert composes it.

    A press forces the next turn, which is what the control offers. A press that
    stayed live until the page read the log again would ride this turn as well,
    and take the channel down on a gesture the human made before the transfer it
    would be undoing -- the same stale claim as before, wearing their own press.

    The page is held blind across both turns, so the two readings are separated
    by construction: the control goes on showing the press the whole time, and
    only the turns say whether it is still being asked for.
    """
    session = launcher(handoff=handoff(PLAN), config={"GRILLUI_ESCALATION_POLICY": "autonomous"})
    session.script_codex(turn(document("Noted.")))
    session.script_claude(turn(EXPERT_SAID))
    session.stub.script(WEIGHED, WEIGHED_AGAIN)
    page = board(session)

    start_thread(page, "d2", IRREDUCIBLE)
    session.settled()
    channel = thread_id(session)
    showing(page, channel, "expert")

    page.locator(f'[data-act="transfer"][data-channel="{channel}"]').click()
    showing(page, channel, "fast")

    freeze(page)
    say(page, IRREDUCIBLE_AGAIN)
    session.settled()
    assert len(transferred(session, channel)) == 2, transferred(session, channel)
    # The control still shows the press, which is the state the next turn is
    # typed into and the reason it must not be sent a second time.
    showing(page, channel, "fast")

    say(page, "Then find it.")
    session.settled()

    assert composings(session, channel) == ["fast", "fast", "heavy"]
    assert len(session.claude_calls()) == 1, session.claude_calls()
    # The press rode the turn before, and nothing after it said anything.
    typed = typed_on(session, channel)
    assert typed[-2]["transfer"] is False, typed[-2]
    assert "transfer" not in typed[-1], typed[-1]


def hold_board(page: Page, outstanding: bool) -> None:
    """Answer this page's doctor check with the state the scenario needs.

    The page holds the board read-only while a reassessment is outstanding, and
    it asks one endpoint whether one is, on every poll. Answering that endpoint
    is how a scenario keeps the board held for as long as it takes to type into
    it: a real doctor run on a scripted seat is over in milliseconds, so a
    scenario racing one would be timing a shim rather than testing the page.
    Answering it also reaches the held board without pressing the control that
    calls the doctor, which the open thread panel sits on top of. What the
    backend does when the doctor is really called is pinned elsewhere; what is
    pinned here is what this page does with a turn it will not post.
    """
    page.route(
        "**/doctor*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"outstanding": outstanding}),
        ),
    )


def test_a_press_survives_a_turn_this_page_declined_to_post(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a thread whose transfer control the human has pressed
    When the board goes read-only, they send into the thread anyway from the
         keyboard, and the page builds that turn without posting it
    Then the box still holds what they typed, their press is still on the next
         turn they really send, and the expert composes it.

    The keyboard is the way in. The scrim over a held board stops a control
    being clicked and stops nothing that is typed: a caret already in the say
    box sends on Enter, and the page builds the turn before it decides not to
    post it. A press spent at that moment would be spent by a turn that never
    existed, and nothing would give it back -- the control would go on offering
    a press no turn could carry.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    session.script_claude(turn(EXPERT_SAID))
    session.stub.script(ANSWERED)
    page = board(session)

    start_thread(page, "d2", ASKED)
    session.settled()
    channel = thread_id(session)
    page.locator(f'[data-act="transfer"][data-channel="{channel}"]').click()
    showing(page, channel, "expert")

    hold_board(page, True)
    page.wait_for_selector(".scrim", timeout=BOARD_TIMEOUT)
    page.fill("#ft-say", DECLINED)
    page.press("#ft-say", "Enter")
    assert DECLINED not in json.dumps([one.payload for one in session.entries()]), (
        "the page posted a turn while the board was held"
    )
    assert page.input_value("#ft-say") == DECLINED, (
        "the box was emptied by a turn the page never posted"
    )

    hold_board(page, False)
    page.wait_for_selector(".scrim", state="detached", timeout=BOARD_TIMEOUT)
    showing(page, channel, "expert")
    say(page, PRESSED)
    session.settled()

    assert composings(session, channel) == ["fast", "heavy"], composings(session, channel)
    assert len(session.claude_calls()) == 1, session.claude_calls()
    typed = typed_on(session, channel)
    assert typed[-1]["transfer"] is True, typed[-1]


def test_a_popped_window_keeps_what_was_typed_into_a_board_that_is_held(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a thread the human has popped out into its own window
    When the board goes read-only and they send into that window anyway
    Then the window still holds what they typed, and nothing reached the log.

    The scrim lies over the board and over nothing else. A window already popped
    out stays a live pane with its own box and its own Send, and the turn that
    Send makes goes back through the opener -- which will not post it. A box
    emptied on the way out is emptied for nothing, and this window is where that
    is hardest to notice, because the thing saying the board is held is in
    another window entirely.
    """
    session = launcher(handoff=handoff(PLAN))
    session.stub.script(ANSWERED)
    page = board(session)

    start_thread(page, "d2", ASKED)
    session.settled()
    with page.expect_popup() as popped:
        page.click('.slide [data-act="popout"]')
    window = popped.value
    window.wait_for_selector("#pop-say", timeout=BOARD_TIMEOUT)

    hold_board(page, True)
    page.wait_for_selector(".scrim", timeout=BOARD_TIMEOUT)
    window.fill("#pop-say", DECLINED)
    window.click('[data-act="say"]')

    assert window.input_value("#pop-say") == DECLINED, (
        "the popped window emptied a box the board would not post from"
    )
    window.wait_for_timeout(300)
    assert DECLINED not in json.dumps([one.payload for one in session.entries()]), (
        "the popped window posted a turn while the board was held"
    )
