"""Taking a thread's converged answer, measured in a browser.

A thread agent may end a turn by offering the answer its thread reached. The
offer rides that turn, and the page puts one control under it: pressing the
control arms the anchor decision's own answer controls -- the proposed words
into the box, after anything the human has already written, and a mark on the
option the offer builds on -- and appends nothing at all. The human then presses
one of the two controls that were always there, and that answer carries where it
came from, settling the decision and closing the thread in one entry.

    uv run --with playwright python tests/browser/apply_decision_probe.py

None of that is a question the source can answer. Whether the control is under
the turn that made it and under no other, whether a box the human was typing in
survives the arming, whether an inert control says what is holding its decision,
and -- the one this exists for -- whether arming the board writes nothing while
answering from it writes exactly once, are the browser's answers.

It is deliberately outside `make ci-grillui`: the gate would have to carry a
browser and its binaries. It seeds its own session, because the shapes it needs
are specific -- a thread whose offer a later one retired, a thread whose human
spoke last, one anchored to a decision the board will not take an answer on, one
anchored to a decision already settled -- and it asserts each shape reached the
board before it presses anything, so a board that could not have failed does not
pass quietly.
"""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from playwright.sync_api import sync_playwright

from grillui.api import create_app
from grillui.log import SessionLog
from grillui.persistence import project_and_persist
from grillui.schemas import SESSION_START_KIND

# Where the two shots this probe takes land. The screenshots are for a human
# reading the surface rather than for an assertion, so the directory is the
# caller's to name and the temp directory is what it defaults to.
SHOTS = Path(os.environ.get("GRILLUI_PROBE_SHOTS", tempfile.gettempdir()))

NEVER_STARTED = "the backend never started"

# What the human is in the middle of writing when the offer arrives. The arming
# must leave it standing: a draft of theirs discarded by an agent's sentence is
# the failure the appending rule exists to stop.
OWN_WORDS = "My own words, written before the offer arrived."
TAKEN = "Keep the append-only log, but only once compaction is designed."
RETIRED = "Take the mutable table and be done with it."
LATER = "Name it after what the human said, not after the field it sets."
BECAUSE = "The thread reached it and the human said as much."

DECISIONS: list[dict[str, Any]] = [
    {
        "id": "d1",
        "short": "Store",
        "title": "Which storage?",
        "prereqs": [],
        "body": "Pick the storage layer.",
        "options": [
            {"id": "a", "text": "Append-only log"},
            {"id": "b", "text": "Mutable table"},
        ],
    },
    {
        "id": "d2",
        "short": "Naming",
        "title": "Whose words name a decision?",
        "prereqs": [],
        "body": "Pick whose vocabulary the board keeps.",
        "options": [
            {"id": "a", "text": "The human's own words"},
            {"id": "b", "text": "The agent's shorthand"},
        ],
    },
    {
        "id": "d3",
        "short": "Rollout",
        "title": "How does this roll out?",
        "prereqs": ["d4"],
        "body": "Nothing here can be answered until the cutover is.",
        "options": [{"id": "a", "text": "All at once"}, {"id": "b", "text": "One team first"}],
    },
    {
        "id": "d4",
        "short": "Cutover",
        "title": "When is the cutover?",
        "prereqs": [],
        "body": "The one nobody answers in this probe.",
        "options": [{"id": "a", "text": "Before the freeze"}],
    },
    {
        "id": "d5",
        "short": "Retention",
        "title": "How long is a session kept?",
        "prereqs": [],
        "body": "A thread is holding this one.",
        "options": [{"id": "a", "text": "Forever"}, {"id": "b", "text": "Ninety days"}],
    },
    {
        "id": "d6",
        "short": "Budget",
        "title": "What does a session cost?",
        "prereqs": [],
        "body": "Not a real question until the cutover settles.",
        "fogUntil": "d4",
        "options": [{"id": "a", "text": "Whatever it costs"}],
    },
    {
        "id": "d7",
        "short": "Escalation",
        "title": "Who is escalated to?",
        "prereqs": [],
        "body": "Answered early, and revisited once a thread converges.",
        "options": [{"id": "a", "text": "The expert tier"}, {"id": "b", "text": "Nobody"}],
    },
    {
        "id": "d8",
        "short": "Compaction",
        "title": "What compacts the log?",
        "prereqs": [],
        "body": "Two threads hang off this one.",
        "options": [{"id": "a", "text": "A scheduled sweep"}, {"id": "b", "text": "Nothing yet"}],
    },
]

HANDOFF = {
    "handoff_version": 1,
    "session": {
        "id": "apply-decision-probe",
        "title": "Session store design",
        "created": "2026-08-18T09:00:00+00:00",
        "author": "probe",
    },
    "impetus": "The store shape is about to be built and nobody has argued against it.",
    "context": "The log is append-only and the page is a renderer.",
    "constraints": ["no new services"],
    "grilling_brief": {
        "posture": "hard on cost and on recovery",
        "stop_when": "every decision is settled or parked with a named blocker",
    },
    "plan": {"statement": "Design the session store.", "decisions": DECISIONS},
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(directory: Path, port: int) -> uvicorn.Server:
    """A backend on loopback, and nothing the launch path does around it."""
    log = SessionLog(directory)
    log.record(SESSION_START_KIND, HANDOFF)
    project_and_persist(log)
    server = uvicorn.Server(
        uvicorn.Config(create_app(log), host="127.0.0.1", port=port, log_level="error")
    )
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.1)
    raise AssertionError(NEVER_STARTED)


def post(base: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One batch, every receipt accepted -- a refused entry would take the shape
    this probe is measuring out of the session silently."""
    epoch = httpx.get(base + "/status").json()["epoch"]
    receipts: list[dict[str, Any]] = httpx.post(
        base + "/events", json={"epoch": epoch, "events": events}
    ).json()
    for receipt in receipts:
        assert receipt["status"] == "accepted", receipt
    return receipts


def entry(kind: str, key: str, actor: str, channel: str, /, **payload: Any) -> dict[str, Any]:
    # Positional-only: a thread-created payload carries a `kind` of its own, and
    # it is the payload's, not the envelope's.
    return {
        "kind": kind,
        "actor": actor,
        "channel": channel,
        "idempotency_key": key,
        "payload": payload,
    }


def opened(thread: str, decision: str, *, alert: bool = False) -> dict[str, Any]:
    return entry(
        "thread-created",
        f"open-{thread}",
        "human",
        thread,
        decision=decision,
        kind="user",
        title=f"On {decision}",
        requires_action=alert,
        turns=[
            {"who": "human", "text": f"Is {decision} really settled by the options as written?"}
        ],
    )


def offered(thread: str, key: str, decision: str, option: str | None, text: str) -> dict[str, Any]:
    return entry(
        "thread-turn",
        key,
        "thread-agent",
        thread,
        turns=[{"who": "thread-agent", "text": "Then this is where the thread lands."}],
        proposed_answer={
            "decision": decision,
            "option": option,
            "text": text,
            "because": BECAUSE,
        },
    )


def log_entries(base: str) -> list[dict[str, Any]]:
    epoch = httpx.get(base + "/status").json()["epoch"]
    read = httpx.get(base + "/updates", params={"epoch": epoch, "cursor": 0}).json()
    entries: list[dict[str, Any]] = read["entries"]
    return entries


def board(base: str) -> dict[str, Any]:
    state: dict[str, Any] = httpx.get(base + "/state").json()["image1"]
    return state


def thread_state(base: str, thread: str) -> str:
    found = [one for one in board(base)["threads"] if one["id"] == thread]
    assert found, f"no thread {thread!r} on the board"
    state: str = found[0]["state"]
    return state


def live_offer(base: str, thread: str) -> dict[str, Any] | None:
    found = [one for one in board(base)["threads"] if one["id"] == thread]
    assert found, f"no thread {thread!r} on the board"
    turns = found[0]["turns"]
    offer: dict[str, Any] | None = turns[-1].get("proposal") if turns else None
    return offer


def decision(base: str, node: str) -> dict[str, Any]:
    found = [one for one in board(base)["decisions"] if one["id"] == node]
    assert found, f"no decision {node!r} on the board"
    return found[0]


def seed(base: str) -> None:
    """The five thread shapes, and the one decision answered before any of them.

    Asserted rather than assumed: every shape below is what makes its own check
    capable of failing.
    """
    post(
        base,
        [
            entry(
                "answer",
                "settle-d7",
                "human",
                "map",
                target="d7",
                answer={"option": "b", "text": "Nobody, for now."},
            ),
            opened("t-d1", "d1"),
            offered("t-d1", "offer-d1", "d1", "a", TAKEN),
            # Two offers on one thread: the later retires the earlier, and only
            # the later may be taken.
            opened("t-d2", "d2"),
            offered("t-d2", "offer-d2-early", "d2", "b", RETIRED),
            offered("t-d2", "offer-d2-late", "d2", None, LATER),
            # Three decisions the board will not take an answer on right now.
            opened("t-d3", "d3"),
            offered("t-d3", "offer-d3", "d3", "a", TAKEN),
            opened("t-d5-alert", "d5", alert=True),
            opened("t-d5", "d5"),
            offered("t-d5", "offer-d5", "d5", "a", TAKEN),
            opened("t-d6", "d6"),
            offered("t-d6", "offer-d6", "d6", "a", TAKEN),
            # A decision already settled: the offer replaces the answer.
            opened("t-d7", "d7"),
            offered("t-d7", "offer-d7", "d7", "a", TAKEN),
            # The two lifecycle shapes: one parked, one closed and reopened.
            opened("t-d8", "d8"),
            offered("t-d8", "offer-d8", "d8", "a", TAKEN),
            opened("t-d8b", "d8"),
            offered("t-d8b", "offer-d8b", "d8", "a", TAKEN),
        ],
    )
    assert decision(base, "d7")["status"] == "settled", "d7 was not settled before the offer"
    assert decision(base, "d6")["status"] == "fogged", "d6 is not in the fog"
    assert "d3" not in board(base)["frontier"], "d3 is answerable, so its hold proves nothing"
    for thread in ("t-d1", "t-d2", "t-d3", "t-d5", "t-d6", "t-d7", "t-d8", "t-d8b"):
        assert live_offer(base, thread), f"{thread} carries no live offer"
    early = board(base)["threads"]
    retired = next(one for one in early if one["id"] == "t-d2")["turns"]
    assert retired[-2].get("proposal"), "the retired offer is not on the board to be read"
    assert retired[-1]["proposal"]["text"] == LATER, "the live offer on t-d2 is the wrong one"


def open_thread(page, thread: str, node: str) -> None:
    """The pane for one thread, reached the way the human reaches it.

    A decision the board is not asking about right now -- blocked, fogged,
    settled -- renders collapsed, and its threads are listed inside the block,
    so the block is opened first exactly as the human would open it.
    """
    control = f'[data-act="openthread"][data-tid="{thread}"]'
    if page.locator(control).count() == 0:
        page.click(f'[data-act="toggle"][data-id="{node}"]')
        page.wait_for_timeout(300)
    page.click(control)
    page.wait_for_timeout(300)
    page.wait_for_selector(".threadpane")


def arm_controls(page):
    return page.locator('.threadpane [data-act="arm"]')


def close_panel(page) -> None:
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-apply-decision-probe-"))
    directory = scratch / "session"
    directory.mkdir(parents=True)
    port = free_port()
    server = serve(directory, port)
    base = f"http://127.0.0.1:{port}"
    seed(base)

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 950})
        page.goto(base + "/")
        page.wait_for_timeout(1200)
        if page.locator('[data-act="takeover"]').count():
            page.click('[data-act="takeover"]')
            page.wait_for_timeout(800)
        page.wait_for_selector("#col-d1", timeout=10000)

        # 1. The control is under the turn that made the live offer, and under
        #    no other. Both offers on t-d2 are readable; one is takeable.
        open_thread(page, "t-d2", "d2")
        offers = page.locator(".threadpane .offer")
        assert offers.count() == 2, f"t-d2 shows {offers.count()} offers, not two"
        assert RETIRED in offers.nth(0).inner_text(), "the retired offer is not readable"
        assert arm_controls(page).count() == 1, "a retired offer carries a control"
        assert offers.nth(1).locator('[data-act="arm"]').count() == 1, (
            "the control is not on the offer that is live"
        )
        turns = page.locator(".threadpane .turn")
        assert turns.last.locator('[data-act="arm"]').count() == 1, (
            "the control is not under the thread's most recent turn"
        )
        close_panel(page)

        # 2. Where the board will not take an answer, the control is inert and
        #    says what is holding the decision.
        for thread, held in (
            ("t-d3", "waiting on d4"),
            ("t-d5", "a thread must conclude first"),
            ("t-d6", "in the fog until d4 settles"),
        ):
            open_thread(page, thread, thread.split("-")[1])
            control = arm_controls(page)
            assert control.count() == 1, f"{thread} shows {control.count()} controls"
            assert control.is_disabled(), f"{thread}'s control is live over a held decision"
            assert held in control.inner_text(), (
                f"{thread}'s control does not name the hold: {control.inner_text()!r}"
            )
            close_panel(page)

        # 3. A settled decision: the control says the answer would be replaced.
        open_thread(page, "t-d7", "d7")
        settled_control = arm_controls(page)
        assert not settled_control.is_disabled(), "a settled decision cannot be re-answered"
        assert "replaces your answer to d7" in settled_control.inner_text(), (
            f"the control does not say it replaces: {settled_control.inner_text()!r}"
        )
        close_panel(page)

        # 4. Arming. The human is mid-sentence in d1's own box when the offer is
        #    taken: the words they wrote stay, the proposal follows them, the
        #    named option is marked, the text is still theirs to edit -- and the
        #    log grew by nothing, because nothing has been answered yet.
        page.fill("#ft-d1", OWN_WORDS)
        page.wait_for_timeout(150)
        open_thread(page, "t-d1", "d1")
        page.screenshot(path=str(SHOTS / "shot-apply.png"), full_page=False)
        before = log_entries(base)
        arm_controls(page).click()
        page.wait_for_timeout(500)

        assert len(log_entries(base)) == len(before), "arming appended to the log"
        assert page.locator(".threadpane").count() == 0, "the panel still covers the decision"
        filled = page.input_value("#ft-d1")
        assert filled == OWN_WORDS + "\n\n" + TAKEN, f"the box does not read as armed: {filled!r}"
        marked = page.locator('#col-d1 [data-act="pick"].armed')
        assert marked.count() == 1, f"{marked.count()} options are marked on d1"
        assert marked.get_attribute("data-opt") == "a", "the wrong option is marked"
        assert "focused" in (page.get_attribute("#col-d1", "class") or ""), (
            "the anchor decision was not brought into view"
        )
        page.screenshot(path=str(SHOTS / "shot-armed.png"), full_page=False)

        # The text is editable, and what the human types is what goes on the wire.
        page.fill("#ft-d1", filled + " Reviewed.")
        page.wait_for_timeout(150)
        assert page.input_value("#ft-d1").endswith("Reviewed."), "the armed text is not editable"

        # 5. Pressing the marked option records option and text together, in one
        #    entry that carries where the answer came from, settles the decision
        #    and closes the thread.
        marked.click()
        page.wait_for_timeout(800)
        after = log_entries(base)
        assert len(after) == len(before) + 1, (
            f"the answer was {len(after) - len(before)} entries, not one"
        )
        answered = after[-1]
        assert answered["kind"] == "answer", answered
        assert answered["payload"]["from_thread"] == "t-d1", answered
        assert answered["payload"]["answer"]["option"] == "a", answered
        assert answered["payload"]["answer"]["text"].endswith("Reviewed."), answered
        assert decision(base, "d1")["status"] == "settled"
        assert thread_state(base, "t-d1") == "closed", "the thread stayed open"
        assert page.locator('#col-d1 [data-act="pick"].armed').count() == 0, (
            "the mark outlived the answer that spent it"
        )

        # 6. The own-words control records the text alone -- which is how an
        #    offer built on an option is taken as the qualification without it.
        #    Here the live offer names no option, and the answer is the words.
        open_thread(page, "t-d2", "d2")
        arm_controls(page).click()
        page.wait_for_timeout(500)
        assert page.input_value("#ft-d2") == LATER, "the empty box was not filled with the offer"
        assert page.locator('#col-d2 [data-act="pick"].armed').count() == 0, (
            "an offer standing on no option marked one"
        )
        before = log_entries(base)
        page.click('#col-d2 [data-act="free"]')
        page.wait_for_timeout(800)
        after = log_entries(base)
        assert len(after) == len(before) + 1, "the own-words answer was not one entry"
        assert after[-1]["payload"]["answer"] == {"option": None, "text": LATER}, after[-1]
        assert after[-1]["payload"]["from_thread"] == "t-d2", after[-1]
        assert thread_state(base, "t-d2") == "closed"

        # 7. Taking an offer onto a settled decision replaces the answer by the
        #    same path -- one entry, and the thread closes with it.
        open_thread(page, "t-d7", "d7")
        arm_controls(page).click()
        page.wait_for_timeout(500)
        before = log_entries(base)
        replacing = page.locator('#col-d7 [data-act="pick"].armed')
        assert replacing.count() == 1, "the settled decision's option was not marked"
        assert not replacing.is_disabled(), "the armed decision's own controls are still locked"
        replacing.click()
        page.wait_for_timeout(800)
        after = log_entries(base)
        assert len(after) == len(before) + 1, "re-answering was not one entry"
        assert after[-1]["payload"]["from_thread"] == "t-d7", after[-1]
        assert decision(base, "d7")["answer"]["option"] == "a", "the answer was not replaced"
        assert thread_state(base, "t-d7") == "closed"

        # 8. Park hides the control while the offer stays live in the log.
        open_thread(page, "t-d8", "d8")
        assert arm_controls(page).count() == 1
        page.click('.threadpane [data-act="park"]')
        page.wait_for_timeout(700)
        assert thread_state(base, "t-d8") == "parked"
        assert live_offer(base, "t-d8"), "parking took the offer out of the log"
        open_thread(page, "t-d8", "d8")
        assert arm_controls(page).count() == 0, "a parked thread still offers to be taken"
        close_panel(page)

        # 9. Closing does the same, and the control comes back when the thread
        #    is open again. The way back from closed is the human speaking,
        #    which is itself a turn that retires the offer it follows -- so the
        #    reopened thread shows a control again once its agent offers again,
        #    and shows none in between.
        open_thread(page, "t-d8b", "d8")
        assert arm_controls(page).count() == 1
        page.click('.threadpane [data-act="closethread"]')
        page.wait_for_timeout(700)
        assert thread_state(base, "t-d8b") == "closed"
        assert live_offer(base, "t-d8b"), "closing took the offer out of the log"
        open_thread(page, "t-d8b", "d8")
        assert arm_controls(page).count() == 0, "a closed thread still offers to be taken"
        page.fill("#ft-say", "Actually, come back to this.")
        page.click('.threadpane [data-act="say"]')
        page.wait_for_timeout(800)
        assert thread_state(base, "t-d8b") == "open", "saying something did not reopen the thread"
        assert arm_controls(page).count() == 0, "the human spoke last and a control is still up"
        post(base, [offered("t-d8b", "offer-d8b-again", "d8", "a", TAKEN)])
        page.wait_for_timeout(1500)
        assert arm_controls(page).count() == 1, "the reopened thread offers no control"

        browser.close()
    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("apply decision probe: clean")


if __name__ == "__main__":
    main()
