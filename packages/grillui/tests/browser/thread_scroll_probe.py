"""Where a thread panel is scrolled to when a turn arrives, measured in a browser.

    uv run --with playwright python tests/browser/thread_scroll_probe.py

A thread's turns live in their own scroller inside the panel, and every re-render
replaces that element -- so whether an arriving turn is on screen is a question
only a layout engine can answer. The source says the panel was drawn; it cannot
say whether the newest turn is above or below the panel's lower edge.

The rule measured here is the one a chat log follows. A human sitting at the
bottom of the thread is reading the conversation as it happens, so the panel
stays at the bottom and the arriving turn is on screen without a gesture. A human
who has scrolled up to re-read something earlier is reading that, so the panel
holds exactly where they left it and the arrival waits below. Both halves are
asserted, because a page that always scrolls to the bottom passes the first and
is a worse bug than the one being fixed.

It seeds its own session rather than taking a directory: the shape it needs is a
thread with more turns than fit the panel, which is a property of the fixture
rather than of any session on disk. Like the other probes here it is outside
`make ci-grillui`, which would have to carry a browser to run it.
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

VIEWPORT = {"width": 1280, "height": 600}
THREAD = "t-probe"
DECISION = "d1"
# Long enough that a dozen of them cannot fit the panel at any plausible height.
FILLER = (
    "The store has to survive a crash between the append and the fsync, and saying "
    "so in one line hides which of the two the reader is promised. Spell out what an "
    "accepted write means for the caller who is about to act on it."
)
ARRIVED = "This one arrives while you are reading."
LATER = "And this one arrives while you are looking further up."
NEVER_STARTED = "the backend never started"
SETTLE_MS = 2500

HANDOFF = {
    "handoff_version": 1,
    "session": {
        "id": "thread-scroll-probe",
        "title": "Session store design",
        "created": "2026-08-18T09:00:00+00:00",
        "author": "probe",
    },
    "impetus": "The store shape is about to be built and nobody has argued against it.",
    "context": "The log is append-only and the page is a renderer.",
    "constraints": ["no new services"],
    "grilling_brief": {"posture": "hard on recovery", "stop_when": "every decision is settled"},
    "plan": {
        "statement": "Design the session store.",
        "decisions": [
            {
                "id": DECISION,
                "short": "Store",
                "title": "Which storage?",
                "prereqs": [],
                "body": "Pick the storage layer.",
                "options": [{"id": "a", "text": "Append-only log"}, {"id": "b", "text": "Table"}],
            }
        ],
    },
}

# The panel's own scroller, the last turn in it, and the two things an arrival
# must not touch: where the board is scrolled to and who holds the caret.
MEASURE = """() => {
  const tb = document.querySelector('#overlay .tbody');
  const col = document.getElementById('column');
  const turns = tb ? tb.querySelectorAll('.turn') : [];
  const last = turns.length ? turns[turns.length - 1] : null;
  const tr = tb ? tb.getBoundingClientRect() : null;
  const lr = last ? last.getBoundingClientRect() : null;
  return {
    panel: !!tb,
    scrollTop: tb ? Math.round(tb.scrollTop) : null,
    scrollHeight: tb ? Math.round(tb.scrollHeight) : null,
    clientHeight: tb ? Math.round(tb.clientHeight) : null,
    turnCount: turns.length,
    lastText: last ? last.innerText.slice(-60) : null,
    lastTop: lr ? Math.round(lr.top - tr.top) : null,
    lastBottom: lr ? Math.round(lr.bottom - tr.top) : null,
    panelHeight: tr ? Math.round(tr.height) : null,
    columnScroll: col ? Math.round(col.scrollTop) : null,
    focused: document.activeElement
      ? document.activeElement.id || document.activeElement.tagName : null,
  };
}"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def post(base: str, kind: str, channel: str, actor: str, payload: dict) -> None:
    """One event, through the door the backend opens to an agent."""
    epoch = httpx.get(base + "/status").json()["epoch"]
    receipt = httpx.post(
        base + "/events",
        json={
            "epoch": epoch,
            "events": [
                {
                    "kind": kind,
                    "actor": actor,
                    "channel": channel,
                    "idempotency_key": f"probe-{kind}-{time.time_ns()}",
                    "payload": payload,
                }
            ],
        },
    ).json()[0]
    assert receipt["status"] == "accepted", receipt


def turn(text: str, who: str) -> dict:
    return {"turns": [{"who": who, "text": text}]}


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


def fill_thread(base: str) -> None:
    """A thread longer than any panel: the shape both halves of the rule need."""
    post(
        base,
        "thread-created",
        THREAD,
        "human",
        {
            "decision": DECISION,
            "kind": "question",
            "title": "What an accepted write promises",
            "turns": [{"who": "human", "text": "Say what an append guarantees."}],
        },
    )
    for i in range(12):
        who, actor = ("thread-agent", "thread-agent") if i % 2 else ("human", "human")
        post(base, "thread-turn", THREAD, actor, turn(f"Turn {i}. {FILLER}", who))


def open_thread(page) -> None:
    page.wait_for_selector(f"#col-{DECISION}", timeout=10000)
    if not page.locator(f'[data-act="openthread"][data-tid="{THREAD}"]').count():
        page.click(f"#col-{DECISION} .head")
        page.wait_for_timeout(400)
    page.click(f'[data-act="openthread"][data-tid="{THREAD}"]')
    page.wait_for_timeout(600)


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-thread-scroll-probe-"))
    directory = scratch / "session"
    port = free_port()
    server = serve(directory, port)
    base = f"http://127.0.0.1:{port}"
    fill_thread(base)

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport=VIEWPORT)
        page.goto(base + "/")
        page.wait_for_timeout(1200)
        if page.locator('[data-act="takeover"]').count():
            page.click('[data-act="takeover"]')
            page.wait_for_timeout(800)
        open_thread(page)

        opened = page.evaluate(MEASURE)
        assert opened["panel"], "the thread panel did not open"
        # The board could not have failed if everything fits: assert the shape
        # rather than pass quietly on a thread that never needed scrolling.
        assert opened["scrollHeight"] > opened["clientHeight"] + 100, (
            f"the thread does not overflow its panel: {opened}"
        )
        print(f"  opened: {opened}")
        # A thread opens at its latest turn, which is what makes "at the bottom"
        # the state a human is in unless they have gone looking for something.
        assert opened["lastBottom"] <= opened["panelHeight"] + 2, (
            f"the panel did not open at the newest turn: {opened}"
        )

        # 1. A turn arriving while the human is at the bottom is on screen when
        #    it lands, and nothing else on the board has moved to put it there.
        before = page.evaluate(MEASURE)
        post(base, "thread-turn", THREAD, "thread-agent", turn(ARRIVED, "thread-agent"))
        page.wait_for_timeout(SETTLE_MS)
        after = page.evaluate(MEASURE)
        print(f"  after an arrival: {after}")
        assert after["turnCount"] == before["turnCount"] + 1, f"the turn never arrived: {after}"
        assert ARRIVED[-30:] in (after["lastText"] or ""), (
            f"the last turn is not the new one: {after}"
        )
        assert after["lastTop"] >= 0 and after["lastBottom"] <= after["panelHeight"] + 2, (
            f"the arriving turn is outside the panel: {after}"
        )
        assert after["columnScroll"] == before["columnScroll"], (
            f"the arrival moved the board from {before['columnScroll']} to {after['columnScroll']}"
        )
        assert after["focused"] == before["focused"], (
            f"the arrival moved the caret from {before['focused']} to {after['focused']}"
        )

        # 2. A human who has scrolled up is reading what is up there. An arrival
        #    is not a reason to take it away from them.
        page.evaluate("document.querySelector('#overlay .tbody').scrollTop = 0")
        page.wait_for_timeout(200)
        held = page.evaluate(MEASURE)
        assert held["scrollTop"] == 0, held
        post(base, "thread-turn", THREAD, "thread-agent", turn(LATER, "thread-agent"))
        page.wait_for_timeout(SETTLE_MS)
        stayed = page.evaluate(MEASURE)
        print(f"  after an arrival while reading up the thread: {stayed}")
        assert stayed["turnCount"] == held["turnCount"] + 1, f"the turn never arrived: {stayed}"
        assert stayed["scrollTop"] == 0, (
            f"an arrival yanked the reader from 0 to {stayed['scrollTop']}"
        )
        assert stayed["columnScroll"] == held["columnScroll"], (
            f"the arrival moved the board from {held['columnScroll']} to {stayed['columnScroll']}"
        )

        browser.close()
    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("thread scroll probe: clean")


if __name__ == "__main__":
    main()
