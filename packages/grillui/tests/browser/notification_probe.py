"""What reaches the notification lane, measured in a browser.

The board is the primary display of state and the lane carries only what the
board does not. Which surface a message came out on is a rendered fact: the
source says which branch was taken, and only a layout engine says whether a
human standing in front of the page saw one toast or five.

    uv run --with playwright python tests/browser/notification_probe.py

It is deliberately outside `make ci-grillui`: the gate would have to carry a
browser and its binaries, and what this pins is pinned in the suite as the
source invariant that produces it.

It seeds its own session rather than taking a directory, because the shape it
needs is specific and no recorded session is guaranteed to hold it: one entry of
every class the policy sorts, arriving while a page is watching. Each class is
asserted to have reached the log and the board before the lane is counted, so a
session that could not have failed does not pass quietly.
"""

from __future__ import annotations

import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from playwright.sync_api import sync_playwright

from grillui.api import create_app
from grillui.log import SessionLog
from grillui.persistence import project_and_persist
from grillui.schemas import SESSION_START_KIND

NEVER_STARTED = "the backend never started"

# The one message with nowhere on the board to land: the agent talking to the
# human about the session rather than about a decision.
LOOSE = "Two of these questions turn out to be the same question."
# The agent's framing of changes it made in the same breath. It carries a tag,
# because prose the policy routes somewhere new is still untrusted input.
FRAMING = "Settling d1 makes d2 <img src=x onerror=\"document.title='markup ran'\"> moot."
# What the fold's other half did to the board, and the proof it did it.
REVISED = "Question d1, sharpened?"
# A message about one decision, which that decision's block already shows.
ABOUT_D2 = "The cost argument on this one rests on the retry budget."
# A change the human must act on: it would overwrite an answer they gave.
PROPOSED = "The batch size should be sixteen, not four."

HANDOFF = {
    "handoff_version": 1,
    "session": {
        "id": "notification-probe",
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
    "plan": {
        "statement": "Design the session store.",
        "decisions": [
            {
                "id": one,
                "short": one.upper(),
                "title": f"Question {one}?",
                "prereqs": [],
                "body": f"The body of {one}.",
                "options": [{"id": "a", "text": "One way"}, {"id": "b", "text": "The other"}],
            }
            for one in ("d1", "d2", "d3")
        ],
    },
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class SilentDriver:
    """A tier that takes the turn and says nothing.

    A backend with no tier at all writes no status lane, and the lane is one of
    the classes being sorted here -- so a tier has to exist. What it must not do
    is answer: every agent word in this session is posted deliberately below, so
    a model's own reply would put prose in the lane that no assertion accounts
    for.
    """

    tier = "fast"

    def run(self, _log: SessionLog, _dispatch: Path, /) -> None:
        return None


def serve(directory: Path, port: int) -> uvicorn.Server:
    """A backend on loopback, and nothing the launch path does around it."""
    log = SessionLog(directory)
    log.record(SESSION_START_KIND, HANDOFF)
    project_and_persist(log)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(log, SilentDriver()), host="127.0.0.1", port=port, log_level="error"
        )
    )
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.1)
    raise AssertionError(NEVER_STARTED)


def post(base: str, events: list[dict]) -> list[dict]:
    """One batch, and every receipt in it accepted -- a refused entry would take
    the shape this probe is measuring out of the session silently."""
    epoch = httpx.get(base + "/status").json()["epoch"]
    receipts = httpx.post(base + "/events", json={"epoch": epoch, "events": events}).json()
    for receipt in receipts:
        assert receipt["status"] == "accepted", receipt
    return receipts


def entry(kind: str, key: str, actor: str = "grill-master", **payload) -> dict:
    return {
        "kind": kind,
        "actor": actor,
        "channel": "map",
        "idempotency_key": key,
        "payload": payload,
    }


def board(base: str) -> dict:
    return httpx.get(base + "/state").json()["image1"]


def kinds(base: str) -> list[str]:
    epoch = httpx.get(base + "/status").json()["epoch"]
    read = httpx.get(base + "/updates", params={"epoch": epoch, "cursor": 0}).json()
    return [one["kind"] for one in read["entries"]]


def bubbles(page):
    """The toast stack, with its clock paused under the pointer so that counting
    it is not a race against the three seconds a toast lives."""
    stack = page.locator("#bubbles")
    if stack.count():
        box = stack.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    return page.locator("#bubbles .bubble")


def wait_for(page, predicate, what: str, limit: float = 6.0) -> None:
    deadline = time.time() + limit
    while time.time() < deadline:
        if predicate():
            return
        page.wait_for_timeout(200)
    raise AssertionError(what)


def panel(page, act: str) -> str:
    """One side panel's rendered text, opened from the header."""
    page.click(f'[data-act="{act}"]')
    page.wait_for_timeout(500)
    text = page.locator(".slide").inner_text()
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    return text


def unread(page) -> int:
    return int(page.locator('[data-act="notifications"]').get_attribute("data-unread"))


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-notification-probe-"))
    directory = scratch / "session"
    directory.mkdir(parents=True)
    port = free_port()
    server = serve(directory, port)
    base = f"http://127.0.0.1:{port}"

    opened = board(base)
    for one in ("d1", "d2", "d3"):
        assert one in opened["frontier"], f"{one} is not open: {opened['frontier']}"

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(base + "/")
        page.wait_for_timeout(1200)
        if page.locator('[data-act="takeover"]').count():
            page.click('[data-act="takeover"]')
            page.wait_for_timeout(800)
        page.wait_for_selector("#col-d1", timeout=10000)
        assert bubbles(page).count() == 0, "the lane was not empty before anything arrived"
        assert unread(page) == 0, "the page opened with something unread"

        # The human answers d3, so the agent's change to it is one that would
        # overwrite a decision they made -- which is what puts it in the inbox
        # rather than on the board.
        page.click('#col-d3 [data-act="pick"][data-opt="a"]')
        wait_for(
            page,
            lambda: any(s["id"] == "d3" for s in board(base)["settled"]),
            "the human's answer never reached the board",
        )

        # The answer put the status lane's own entries into the session -- they
        # are the backend's to write and no client may post one, which is why
        # they arrive this way rather than in the batch below.
        assert "status" in kinds(base), f"the answer wrote no status entry: {kinds(base)}"

        # One batch carrying the rest of what the policy sorts: a fold speaking
        # and changing the board together, a message about a decision, a message
        # about none, and a change that has to wait for the human.
        post(
            base,
            [
                entry(
                    "fold",
                    "probe-fold",
                    updates=[
                        {"kind": "informational", "text": FRAMING},
                        {"kind": "revise", "target": "d1", "title": REVISED, "why": "cost"},
                    ],
                ),
                entry("informational", "probe-about-d2", text=ABOUT_D2, target="d2"),
                entry("informational", "probe-loose", text=LOOSE),
                entry("revise", "probe-proposal", target="d3", title="Question d3?", why=PROPOSED),
            ],
        )
        wait_for(
            page,
            lambda: bubbles(page).count() > 0 or unread(page) > 0,
            "nothing arrived at the page at all",
        )
        page.wait_for_timeout(900)

        # --- non-vacuity: every class really is in this session ---
        arrived = kinds(base)
        for kind in ("status", "fold", "informational", "revise"):
            assert kind in arrived, f"no {kind} entry in the session: {arrived}"
        queued = {one["id"]: one for one in board(base)["pending"]}
        assert "probe-fold#0" in queued, f"the fold's prose is not on the board: {queued}"
        assert "probe-about-d2" in queued, f"the targeted message is not on the board: {queued}"
        assert "probe-loose" in queued, f"the loose message is not on the board: {queued}"
        assert "probe-proposal" in queued, f"the change never became an inbox item: {queued}"
        changed = {one["id"]: one for one in board(base)["decisions"]}
        assert changed["d1"]["title"] == REVISED, f"the fold never changed d1: {changed['d1']}"

        # --- the lane carries the one message the board cannot show ---
        toasts = bubbles(page)
        assert toasts.count() == 1, (
            f"{toasts.count()} toasts for one message the board cannot show: "
            f"{[toasts.nth(i).inner_text() for i in range(toasts.count())]}"
        )
        assert LOOSE in toasts.nth(0).inner_text(), toasts.nth(0).inner_text()

        listed = panel(page, "notifications")
        assert LOOSE in listed, f"the loose message is not in the list: {listed}"
        for hidden, why in (
            (FRAMING[:40], "framing that arrived with board changes"),
            (ABOUT_D2, "a message the decision's own block shows"),
            (PROPOSED, "a change waiting in the inbox"),
            ("composing", "the status lane's own mechanics"),
        ):
            assert hidden not in listed, f"{why} reached the notification lane: {listed}"

        # --- what the board shows instead ---
        d1 = page.locator("#col-d1").inner_text()
        assert FRAMING[:40] in d1, f"the fold's framing is not on the decision it changed: {d1}"
        d2 = page.locator("#col-d2").inner_text()
        assert ABOUT_D2 in d2, f"the message about d2 is not on d2: {d2}"
        assert page.locator("#col-d1 img").count() == 0, "the framing's tag became an element"
        assert page.title() != "markup ran", "the framing's markup ran"

        inbox = panel(page, "inbox")
        assert PROPOSED in inbox, f"the actionable change is not in the inbox: {inbox}"
        assert LOOSE not in inbox, "a message the human cannot act on is in the inbox"

        # --- read-state, over the smaller set ---
        # Three messages, counted once each wherever the policy routed them --
        # the framing on d1, the message on d2, the loose one in the lane. A
        # change waiting in the inbox is not a message and is not counted here.
        assert unread(page) == 3, f"the unread count is {unread(page)}, not one per message"
        page.click('[data-act="notifications"]')
        page.wait_for_timeout(400)
        page.click('[data-act="markall"]')
        page.wait_for_timeout(600)
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        assert unread(page) == 0, f"mark-all-read left {unread(page)} unread"
        assert bubbles(page).count() == 0, "a read message is still toasting"
        assert page.locator("#col-d2 .mail").count() == 0, "a read message still marks its decision"

        page.reload()
        page.wait_for_timeout(1800)
        page.wait_for_selector("#col-d1", timeout=10000)
        assert unread(page) == 0, f"the reload restored {unread(page)} unread markers"
        assert ABOUT_D2 in page.locator("#col-d2").inner_text(), "the reload lost a board message"
        assert FRAMING[:40] in page.locator("#col-d1").inner_text(), "the reload lost the framing"
        assert bubbles(page).count() == 0, "the reload announced the session's own history"

        browser.close()
    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("notification probe: clean")


if __name__ == "__main__":
    main()
