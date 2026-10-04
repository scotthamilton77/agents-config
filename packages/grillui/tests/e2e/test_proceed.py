"""The seat toggle and *Proceed with expert*, driven in a browser.

The toggle chooses who the next send goes to and writes nothing until a turn
carries the choice. *Proceed with expert* sends the expert in on a thread at
once: with nothing typed it is a text-less turn saying only that the human
asked, and with text it is the very send the toggle makes after the expert is
chosen. Every scenario reads the log for what landed and the page for what the
human was shown, because each claim here is about one of the two agreeing with
the other.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

import httpx
from conftest import BOARD_TIMEOUT, decision, document, handoff, turn
from test_reading import (
    ANSWERED,
    ASKED,
    ASKING,
    EXPERT_SAID,
    IRREDUCIBLE,
    PLAN,
    PRESSED,
    SAID,
    WANTED,
    composings,
    conversation,
    say,
    start_thread,
    thread_id,
    typed_on,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

# The line the expert is handed when the human proceeded without a turn, spelled
# out here so the scenario asserts against the bytes the expert really receives.
PROCEED_LINE = (
    "human: I asked the expert to proceed on this thread as it stands, without adding a turn."
)
# What the page says in its own words, whatever any seat said.
PROCEED_MARK = "You asked the expert to proceed with the thread as it stands."
HINT = (
    "The assistant asked to read something it was not given. "
    "The next step is Proceed with expert, which hands this thread to the expert."
)
# Long enough that the scenario reads the page while the expert is still on it.
SLOW = 4
EXPERT_AGAIN = "Then it is ninety days, because the archive is cold."
TYPED = "Weigh the retention window against the archive bill."
AGAIN = "And what about the cold tier?"


def seats(channel: str) -> str:
    return f'.seats[data-channel="{channel}"]'


def marked(page: Page, channel: str) -> str:
    """The seat this channel's toggle marks, as the human reads it."""
    return page.locator(f'{seats(channel)} [aria-pressed="true"]').inner_text().strip()


def choose(page: Page, channel: str, seat: str) -> None:
    """Choose a seat on the toggle, and wait for the page to show it."""
    page.click(f'{seats(channel)} [data-seat="{seat}"]')
    page.wait_for_selector(
        f'{seats(channel)} [data-seat="{seat}"][aria-pressed="true"]', timeout=BOARD_TIMEOUT
    )


def proceed(channel: str) -> str:
    return f'[data-act="proceed"][data-tid="{channel}"]'


def spoken(session: Session, channel: str) -> list[dict[str, Any]]:
    """The agents' replies on one channel, as the log holds them."""
    return [
        dict(one.payload)
        for one in session.entries()
        if one.channel == channel and one.actor in {"thread-agent", "grill-master"}
    ]


def test_gui_a112_proceed_with_the_box_empty_sends_the_expert_in_over_the_thread(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a gated session whose assistant has answered on a thread
    When the human presses *Proceed with expert* with only spaces in the box
    Then the toggle marks the expert from the press onward, the thread shows the
         line saying they asked with the wait beneath it, the log gains one
         text-less turn carrying `proceed` and `transfer`, and the expert takes
         the turn over the thread so far and the line saying why.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    session.script_claude(turn(EXPERT_SAID, delay=SLOW))
    session.stub.script(ANSWERED)
    page = board(session)

    start_thread(page, "d2", ASKED)
    session.settled()
    channel = thread_id(session)
    page.wait_for_selector(f".turn.thread-agent >> text={ANSWERED}", timeout=BOARD_TIMEOUT)
    assert marked(page, channel) == "assistant"

    page.fill("#ft-say", "   ")
    page.click(proceed(channel))
    assert marked(page, channel) == "expert", "the toggle did not follow the press"
    page.wait_for_selector(f".proceedmark >> text={PROCEED_MARK}", timeout=BOARD_TIMEOUT)
    wait = page.wait_for_selector(f'.waitmark[data-channel="{channel}"]', timeout=BOARD_TIMEOUT)
    line = page.locator(".proceedmark").bounding_box()
    below = wait.bounding_box() if wait else None
    assert line and below and below["y"] >= line["y"] + line["height"], (line, below)
    assert len(spoken(session, channel)) == 1, "the expert replied before the page was read"
    session.settled()

    assert typed_on(session, channel)[-1] == {"proceed": True, "transfer": True}
    assert composings(session, channel) == ["fast", "heavy"]
    calls = session.claude_calls()
    assert len(calls) == 1, calls
    said = conversation(calls[0]["prompt"], channel)
    assert f"human: {ASKED}" in said, said
    assert f"thread-agent: {ANSWERED}" in said, said
    assert said.strip().endswith(PROCEED_LINE), said
    reply = spoken(session, channel)[-1]
    assert reply["followed_transfer"] is True, reply
    assert "transfer_source" not in reply, reply
    page.wait_for_selector(f".turn.thread-agent >> text={EXPERT_SAID}", timeout=BOARD_TIMEOUT)
    assert marked(page, channel) == "expert"
    assert page.input_value("#ft-say") == "   ", "the human typed nothing, and nothing was taken"


def test_gui_a112_proceed_on_a_thread_the_policy_moved_keeps_the_policys_attribution(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given an autonomous session whose thread the policy moved on a read request
    When the human presses *Proceed with expert* with the box empty
    Then the text-less turn carries no transfer key, and the expert's reply says
         the policy is what moved the channel.
    """
    session = launcher(handoff=handoff(PLAN), config={"GRILLUI_ESCALATION_POLICY": "autonomous"})
    session.script_codex(turn(document("Noted.")))
    session.script_claude(turn(EXPERT_SAID))
    session.stub.script(ASKING)
    page = board(session)

    start_thread(page, "d2", ASKED)
    session.settled()
    channel = thread_id(session)
    page.wait_for_selector(
        f'{seats(channel)} [data-seat="heavy"][aria-pressed="true"]', timeout=BOARD_TIMEOUT
    )

    page.click(proceed(channel))
    session.settled()

    assert typed_on(session, channel)[-1] == {"proceed": True}
    assert composings(session, channel) == ["fast", "heavy"]
    reply = spoken(session, channel)[-1]
    assert reply["followed_transfer"] is True, reply
    assert reply["transfer_source"] == "policy", reply


def test_gui_a113_proceed_with_text_writes_the_entry_the_toggle_and_send_write(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a thread the assistant has answered
    When the human chooses the expert and sends a turn, returns the thread to
         the assistant and says something, then types the same turn and presses
         *Proceed with expert*
    Then the two expert-bound entries are equal but for their sequence, time and
         key; the box empties; the expert takes the turn; the toggle marks the
         expert; and no line saying the human asked to proceed is drawn.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    session.script_claude(turn(EXPERT_SAID), turn(EXPERT_AGAIN))
    session.stub.script(ANSWERED, ANSWERED)
    page = board(session)

    start_thread(page, "d2", ASKED)
    session.settled()
    channel = thread_id(session)

    choose(page, channel, "heavy")
    say(page, TYPED)
    session.settled()
    choose(page, channel, "fast")
    say(page, PRESSED)
    session.settled()

    page.fill("#ft-say", TYPED)
    page.click(proceed(channel))
    assert marked(page, channel) == "expert"
    session.settled()

    human = [one for one in session.entries() if one.actor == "human" and one.channel == channel]
    sent, pressed = human[1], human[-1]
    assert (sent.kind, sent.channel, sent.payload) == (
        pressed.kind,
        pressed.channel,
        pressed.payload,
    )
    assert pressed.payload["transfer"] is True
    assert "proceed" not in pressed.payload
    assert composings(session, channel) == ["fast", "heavy", "fast", "heavy"]
    assert page.input_value("#ft-say") == ""
    page.wait_for_selector(f".turn.thread-agent >> text={EXPERT_AGAIN}", timeout=BOARD_TIMEOUT)
    assert page.locator(".proceedmark").count() == 0
    assert page.locator(f".turn.human >> text={TYPED}").count() == 2


def test_gui_a113_proceed_with_text_on_a_draft_writes_the_entry_the_toggle_and_send_write(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a decision nobody has opened a thread on
    When the human chooses the expert on a draft and sends a first turn, then
         types the same turn into a second draft and presses *Proceed with
         expert*
    Then both open a thread with entries equal but for their minted names,
         sequence, time and key; the choice on the draft appended nothing; and
         the expert takes each first turn.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    session.script_claude(turn(EXPERT_SAID), turn(EXPERT_AGAIN))
    page = board(session)

    page.click('#col-d2 [data-act="newthread"][data-id="d2"]')
    page.wait_for_selector("#ft-say", timeout=BOARD_TIMEOUT)
    before = len(session.entries())
    choose(page, "draft:d2", "heavy")
    page.wait_for_timeout(1500)
    assert len(session.entries()) == before, "choosing a seat on a draft wrote to the log"
    page.fill("#ft-say", TYPED)
    page.click('[data-act="draftsay"]')
    session.settled()

    page.click('[data-act="closepanel"]')
    page.click('#col-d2 [data-act="newthread"][data-id="d2"]')
    page.wait_for_selector("#ft-say", timeout=BOARD_TIMEOUT)
    assert marked(page, "draft:d2") == "assistant"
    page.fill("#ft-say", TYPED)
    page.click(proceed("draft:d2"))
    session.settled()

    opened = [one for one in session.entries() if one.kind == "thread-created"]
    assert len(opened) == 2, opened
    assert opened[0].payload == opened[1].payload
    assert opened[1].payload["transfer"] is True
    assert "proceed" not in opened[1].payload
    for one in opened:
        assert composings(session, one.channel) == ["heavy"], one.channel


def test_gui_a114_the_action_is_inactive_and_says_why_where_there_is_nothing_to_proceed_on(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a draft, a thread whose expert reply is still on its way, and a thread
          whose latest turn is the expert's
    When each is shown with the box empty
    Then the action is inactive in each and a reason is shown, and pressing it
         anyway writes nothing.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    session.script_claude(turn(EXPERT_SAID, delay=SLOW))
    session.stub.script(ANSWERED)
    page = board(session)

    page.click('#col-d2 [data-act="newthread"][data-id="d2"]')
    page.wait_for_selector("#ft-say", timeout=BOARD_TIMEOUT)
    inactive(page, session, "draft:d2", "Nothing has been said here yet")
    page.fill("#ft-say", ASKED)
    page.click('[data-act="draftsay"]')
    session.settled()
    channel = thread_id(session)

    page.click(proceed(channel))
    page.wait_for_selector(f'.waitmark[data-channel="{channel}"]', timeout=BOARD_TIMEOUT)
    page.wait_for_selector(f".proceedmark >> text={PROCEED_MARK}", timeout=BOARD_TIMEOUT)
    inactive(page, session, channel, "A reply is still on its way")
    session.settled()

    page.wait_for_selector(f".turn.thread-agent >> text={EXPERT_SAID}", timeout=BOARD_TIMEOUT)
    inactive(page, session, channel, "The expert's reply is the latest turn")
    assert len(session.claude_calls()) == 1


def inactive(page: Page, session: Session, channel: str, why: str) -> None:
    """The action is on the row, inactive, with the reason under it, and a press
    that gets through anyway writes nothing."""
    page.wait_for_selector(
        f'.proceedwhy[data-channel="{channel}"] >> text={why}', timeout=BOARD_TIMEOUT
    )
    action = page.locator(proceed(channel))
    assert action.count() == 1, f"{action.count()} proceed actions on {channel}"
    assert action.get_attribute("data-blocked") == "1"
    assert action.evaluate("el => getComputedStyle(el).pointerEvents") == "none"
    before = len(session.entries())
    action.click(force=True)
    page.wait_for_timeout(1000)
    assert len(session.entries()) == before, (
        f"a press on {channel} wrote {session.entries()[before:]}"
    )
    # A box holding only spaces is an empty one, so it renders the same way.
    page.fill("#ft-say", "   ")
    reason = page.locator(f'.proceedwhy[data-channel="{channel}"]')
    assert reason.is_visible(), f"the reason is hidden on {channel} with only spaces typed"
    assert action.evaluate("el => getComputedStyle(el).pointerEvents") == "none", (
        f"the action looks active on {channel} with only spaces typed"
    )
    page.fill("#ft-say", "")


def posted(session: Session, channel: str) -> dict[str, Any]:
    """A text-less proceed posted straight to the backend, as any client could,
    and the receipt it gets back."""
    epoch = httpx.get(session.url + "status").json()["epoch"]
    event = {
        "kind": "thread-turn",
        "actor": "human",
        "channel": channel,
        "idempotency_key": f"direct-{len(session.entries())}-{channel}",
        "payload": {"proceed": True, "transfer": True},
    }
    receipts = httpx.post(session.url + "events", json={"epoch": epoch, "events": [event]}).json()
    receipt: dict[str, Any] = receipts[0]
    return receipt


def refused(session: Session, channel: str, reason: str, state: str) -> None:
    """The backend refuses the posted proceed with this reason, naming the state
    where it has one to name, and nobody is dispatched."""
    before = (len(session.entries()), len(session.claude_calls()))
    receipt = posted(session, channel)
    assert receipt["status"] == "rejected", receipt
    assert receipt["reason"] == reason, receipt
    assert state in receipt["detail"], receipt
    assert (len(session.entries()), len(session.claude_calls())) == before, receipt


def test_gui_a114_the_backend_refuses_a_textless_proceed_posted_directly_in_each_state(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a session driven from the page into each state with nothing to
          proceed on
    When a text-less proceed is posted straight to the backend in each one
    Then it is refused every time and appends nothing: naming no thread on a
         thread nothing created, and *nothing to proceed on* with the state in
         its detail while a reply is outstanding, after the expert spoke last,
         and on a parked and on a closed thread.

    Posted rather than pressed, because the page will not send a press it has
    already rendered inactive, so only a direct post reaches the refusal.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    session.script_claude(turn(EXPERT_SAID, delay=SLOW))
    session.stub.script(ANSWERED, ANSWERED)
    page = board(session)

    refused(session, "t-nobody-opened", "unknown thread id", "no thread has been created")

    start_thread(page, "d2", ASKED)
    session.settled()
    channel = thread_id(session)
    choose(page, channel, "heavy")
    say(page, TYPED)
    # Read off the log rather than the page, so the post lands after the expert's
    # turn was announced and before it replied.
    deadline = time.monotonic() + SLOW
    while composings(session, channel) != ["fast", "heavy"] and time.monotonic() < deadline:
        time.sleep(0.05)
    assert composings(session, channel) == ["fast", "heavy"], composings(session, channel)
    refused(session, channel, "nothing to proceed on", "outstanding")
    session.settled()
    refused(session, channel, "nothing to proceed on", "the thread's latest turn is the expert's")

    page.click(f'[data-act="park"][data-tid="{channel}"]')
    session.settled()
    refused(session, channel, "nothing to proceed on", "the thread is parked")

    if page.locator('[data-act="closepanel"]').count():
        page.click('[data-act="closepanel"]')
    start_thread(page, "d1", ASKED)
    session.settled()
    other = [one.channel for one in session.entries() if one.kind == "thread-created"][-1]
    page.click(f'[data-act="closethread"][data-tid="{other}"]')
    session.settled()
    refused(session, other, "nothing to proceed on", "the thread is closed")


def test_gui_a114_a_set_aside_thread_the_map_and_an_ended_session_offer_no_action(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a thread the human parked, the board's header, and then an ended
          session
    Then the parked thread carries no proceed action, the map carries none
         anywhere, and after the ending every action left on screen is inert.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    session.stub.script(ANSWERED, ANSWERED)
    page = board(session)

    start_thread(page, "d2", ASKED)
    session.settled()
    channel = thread_id(session)
    page.wait_for_selector(proceed(channel), timeout=BOARD_TIMEOUT)
    assert page.locator('.topbar [data-act="proceed"]').count() == 0
    assert page.locator(f".topbar {seats('map')}").count() == 1

    page.click(f'[data-act="park"][data-tid="{channel}"]')
    session.settled()
    page.wait_for_selector(".parked-note >> text=parked", timeout=BOARD_TIMEOUT)
    assert page.locator(proceed(channel)).count() == 0

    if page.locator('[data-act="closepanel"]').count():
        page.click('[data-act="closepanel"]')
    start_thread(page, "d1", ASKED)
    session.settled()
    other = [one.channel for one in session.entries() if one.kind == "thread-created"][-1]
    page.wait_for_selector(proceed(other), timeout=BOARD_TIMEOUT)
    page.click('[data-act="closepanel"]')
    page.click('.topbar [data-act="endsession"]')
    page.wait_for_timeout(500)
    if page.locator("#confirm").count():
        page.click('#confirm [data-act="confirm-end"]')
    page.wait_for_selector('.topbar [data-act="endsession"]:disabled', timeout=BOARD_TIMEOUT)
    page.click('[data-act="threads"][data-id="d1"]')
    page.wait_for_selector(proceed(other), timeout=BOARD_TIMEOUT)
    assert page.locator(proceed(other)).is_disabled(), "an ended session still offers the action"


def test_gui_a116_a_reply_that_asked_to_read_carries_the_hint_while_it_is_latest_and_open(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given an assistant reply that asked to read two things
    When it lands, the human says the next thing, the assistant answers without
         asking, the expert answers asking to read, and a second thread's
         asking reply is then parked
    Then the hint is beneath the asking reply in the page's own words while it
         is the latest turn, and beneath nothing after that: not the ordinary
         reply, not the expert's asking one, and not the parked thread's.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    session.script_claude(turn(json.dumps({"text": EXPERT_SAID, "needs_to_read": WANTED})))
    session.stub.script(ASKING, ANSWERED, ASKING)
    page = board(session)

    start_thread(page, "d2", ASKED)
    session.settled()
    channel = thread_id(session)
    hint = page.wait_for_selector(
        f'.turn .readhint[data-channel="{channel}"]', timeout=BOARD_TIMEOUT
    )
    assert hint and hint.inner_text().strip() == HINT
    assert SAID not in HINT
    last = page.locator(".threadpane .turn").last
    assert last.locator(".readhint").count() == 1, "the hint is not beneath the asking reply"

    say(page, PRESSED)
    session.settled()
    page.wait_for_selector(f".turn.thread-agent >> text={ANSWERED}", timeout=BOARD_TIMEOUT)
    assert page.locator(".readhint").count() == 0

    choose(page, channel, "heavy")
    say(page, "Then find it.")
    session.settled()
    page.wait_for_selector(f".turn.thread-agent >> text={EXPERT_SAID}", timeout=BOARD_TIMEOUT)
    assert spoken(session, channel)[-1].get("needs_to_read") == WANTED
    assert page.locator(".readhint").count() == 0

    page.click('[data-act="closepanel"]')
    start_thread(page, "d1", ASKED)
    session.settled()
    other = [one.channel for one in session.entries() if one.kind == "thread-created"][-1]
    page.wait_for_selector(f'.readhint[data-channel="{other}"]', timeout=BOARD_TIMEOUT)
    assert page.locator(f'{proceed(other)}[data-recommended="1"]').count() == 1
    page.click(f'[data-act="park"][data-tid="{other}"]')
    session.settled()
    page.wait_for_selector(".parked-note >> text=parked", timeout=BOARD_TIMEOUT)
    assert page.locator(".readhint").count() == 0
    # A parked thread carries no action, so the recommendation lights nothing.
    assert page.locator('[data-recommended="1"]').count() == 0


def test_gui_a33_the_recommendation_lights_the_way_to_the_expert_on_its_thread_and_nothing_else(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a gated session
    When the human opens a thread saying the question is not the one, and then
         says something plain on it
    Then the thread's *Proceed with expert* action is lit after the first reply
         and unlit after the second, the assistant seat is never lit, and
         nothing moved.
    """
    session = launcher(
        handoff=handoff([decision("d1", "Which storage?"), decision("d2", "How long?")])
    )
    session.stub.script("Noted.", "Noted again.")
    page = board(session)

    start_thread(page, "d1", IRREDUCIBLE)
    session.settled()
    channel = thread_id(session)
    lit = f'{proceed(channel)}[data-recommended="1"]'
    page.wait_for_selector(lit, timeout=BOARD_TIMEOUT)
    assert page.locator('[data-seat="fast"][data-recommended="1"]').count() == 0
    assert marked(page, channel) == "assistant"

    say(page, AGAIN)
    session.settled()
    page.wait_for_selector(lit, state="detached", timeout=BOARD_TIMEOUT)
    assert composings(session, channel) == ["fast", "fast"]


def test_gui_a63_the_toggle_marks_the_next_send_and_sits_where_that_send_is_made(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given the map, a draft and an open thread
    Then each toggle shows both seats under its caption and marks exactly one,
         a choice is marked the moment it is made and before anything reaches
         the log, the map's is in the header, and a thread's or a draft's sits
         in the row of the send it governs.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    session.stub.script(ANSWERED)
    page = board(session)

    header = page.locator(f".topbar {seats('map')}")
    assert header.count() == 1
    shows(page, "map")

    page.click('#col-d2 [data-act="newthread"][data-id="d2"]')
    page.wait_for_selector("#ft-say", timeout=BOARD_TIMEOUT)
    shows(page, "draft:d2")
    beside_send(page, "draft:d2", '[data-act="draftsay"]')
    page.fill("#ft-say", ASKED)
    page.click('[data-act="draftsay"]')
    session.settled()
    channel = thread_id(session)
    page.wait_for_selector(f".turn.thread-agent >> text={ANSWERED}", timeout=BOARD_TIMEOUT)
    shows(page, channel)
    beside_send(page, channel, '[data-act="say"]')

    before = len(session.entries())
    page.click(f'{seats(channel)} [data-seat="heavy"]')
    assert marked(page, channel) == "expert"
    page.wait_for_timeout(1500)
    assert len(session.entries()) == before, "choosing a seat wrote to the log"
    assert marked(page, channel) == "expert"
    page.click(f'{seats(channel)} [data-seat="fast"]')
    assert marked(page, channel) == "assistant"
    page.wait_for_timeout(1500)
    assert len(session.entries()) == before


def shows(page: Page, channel: str) -> None:
    toggle = page.locator(seats(channel))
    assert toggle.count() == 1, f"{toggle.count()} toggles on {channel}"
    assert toggle.locator(".cap").inner_text().strip() == "Next send goes to"
    names = [one.inner_text().strip() for one in toggle.locator("[data-seat]").all()]
    assert names == ["assistant", "expert"], names
    assert toggle.locator('[aria-pressed="true"]').count() == 1


def beside_send(page: Page, channel: str, send: str) -> None:
    """The toggle's box overlaps the send control's vertically."""
    toggle = page.locator(seats(channel)).bounding_box()
    sent = page.locator(f".threadpane {send}").bounding_box()
    assert toggle and sent, (toggle, sent)
    assert (
        toggle["y"] < sent["y"] + sent["height"] and sent["y"] < toggle["y"] + toggle["height"]
    ), (
        toggle,
        sent,
    )


def test_gui_a35_every_channel_has_an_active_toggle_and_assistant_returns_the_next_turn(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given the map and two open threads, one of them idle, and one thread the
          human moved to the expert
    When the human selects the assistant on that thread and says the next thing
    Then every channel shows an active toggle throughout, and the assistant
         takes the turn.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    session.script_claude(turn(EXPERT_SAID))
    session.stub.script(ANSWERED, ANSWERED, ANSWERED)
    page = board(session)

    start_thread(page, "d1", ASKED)
    session.settled()
    idle = thread_id(session)
    page.click('[data-act="closepanel"]')
    start_thread(page, "d2", ASKED)
    session.settled()
    channel = [one.channel for one in session.entries() if one.kind == "thread-created"][-1]

    choose(page, channel, "heavy")
    say(page, TYPED)
    session.settled()
    page.wait_for_selector(f".turn.thread-agent >> text={EXPERT_SAID}", timeout=BOARD_TIMEOUT)
    assert marked(page, channel) == "expert"
    choose(page, channel, "fast")
    say(page, AGAIN)
    session.settled()

    assert composings(session, channel) == ["fast", "heavy", "fast"]
    assert typed_on(session, channel)[-1]["transfer"] is False
    active(page, "map")
    active(page, channel)
    page.click('[data-act="closepanel"]')
    page.click('[data-act="threads"][data-id="d1"]')
    page.wait_for_selector(seats(idle), timeout=BOARD_TIMEOUT)
    active(page, idle)


def active(page: Page, channel: str) -> None:
    """The toggle is there, and its unmarked seat is a live control."""
    toggle = page.locator(seats(channel))
    assert toggle.count() == 1, f"{toggle.count()} toggles on {channel}"
    control = toggle.locator('[data-act="transfer"]')
    assert control.count() == 1 and control.is_enabled(), channel


def test_gui_a115_with_no_input_after_a_read_request_the_page_writes_nothing(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a gated session whose assistant asked to read something
    When the page sits through several polls with nobody touching it, and the
         human then says the next thing with the toggle on the assistant
    Then the log gained nothing on that thread while nobody acted, nobody
         called the expert, and the assistant takes the turn they said.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("Noted.")))
    session.stub.script(ASKING, ANSWERED)
    page = board(session)

    start_thread(page, "d2", ASKED)
    session.settled()
    channel = thread_id(session)
    page.wait_for_selector(f'{proceed(channel)}[data-recommended="1"]', timeout=BOARD_TIMEOUT)
    before = [one.seq for one in session.entries() if one.channel == channel]
    page.wait_for_timeout(3000)
    assert [one.seq for one in session.entries() if one.channel == channel] == before
    assert marked(page, channel) == "assistant"

    say(page, PRESSED)
    session.settled()
    assert composings(session, channel) == ["fast", "fast"]
    assert "transfer" not in typed_on(session, channel)[-1]
    assert not session.claude_calls()
