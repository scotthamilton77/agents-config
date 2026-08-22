"""Whether a thread owed a reply says so in its own body, measured in a browser.

    uv run --with playwright python tests/browser/thread_wait_probe.py

The header's clock sits above the board; a human who has just sent a turn is
inside the thread, reading their own message. Whether the acknowledgement is
where they are looking is a question about a rendered document, and whether its
seconds move is a question only a running page can answer -- a marker drawn once
and a marker ticked every second are the same markup at the instant they are
written and differ only later.

Three things are looked at, in the order a human meets them. Nothing marks a
thread nobody is answering. The moment the lane says a tier has the turn, the
marker is under the last turn with the header's own seconds on it, and both
clocks advance together. When the reply lands the marker is gone -- which is the
half that matters, because a marker that never leaves is a page telling the human
they are still waiting for something they have already read.

It seeds its own session and opens one turn nothing answers until it says so: a
session directory on disk is not guaranteed to be mid-turn when it is handed
over. Like the other probes here it is outside `make ci-grillui`, which would
have to carry a browser to run it.
"""

from __future__ import annotations

import re
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
from grillui.schemas import (
    SESSION_START_KIND,
    STATUS_PHASE_COMPOSING,
    STATUS_PHASE_REPLIED,
)

THREAD = "t-probe"
DECISION = "d1"
NEVER_STARTED = "the backend never started"
# Long enough that a stopped clock and a running one cannot be confused for one
# another by a scheduling wobble, short enough to stay a probe.
WAITED = 4
ASKED = "Say what an append actually guarantees the caller."
ANSWERED = "It guarantees the bytes are in the file and fsynced before you are told."

HANDOFF = {
    "handoff_version": 1,
    "session": {
        "id": "thread-wait-probe",
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


def serve(directory: Path, port: int) -> tuple[uvicorn.Server, SessionLog]:
    log = SessionLog(directory)
    log.record(SESSION_START_KIND, HANDOFF)
    project_and_persist(log)
    server = uvicorn.Server(
        uvicorn.Config(create_app(log), host="127.0.0.1", port=port, log_level="error")
    )
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server, log
        time.sleep(0.1)
    raise AssertionError(NEVER_STARTED)


def open_thread(page) -> None:
    page.wait_for_selector(f"#col-{DECISION}", timeout=10000)
    if not page.locator(f'[data-act="openthread"][data-tid="{THREAD}"]').count():
        page.click(f"#col-{DECISION} .head")
        page.wait_for_timeout(400)
    page.click(f'[data-act="openthread"][data-tid="{THREAD}"]')
    page.wait_for_timeout(600)


def marker(page):
    return page.locator(f'#overlay .tbody .waitmark[data-channel="{THREAD}"]')


def marker_seconds(page) -> int:
    return int(marker(page).get_attribute("data-waited"))


def header_seconds(page) -> int:
    """The seconds the header's own clock is showing, off its text."""
    text = page.locator("#lanetimer").inner_text()
    found = re.search(r"(\d+)s", text)
    assert found, f"the header is showing no clock at all: {text!r}"
    return int(found.group(1))


def below_last_turn(page) -> bool:
    """Whether the marker sits under the turns rather than anywhere in the pane."""
    return bool(
        page.evaluate(
            """() => {
      const body = document.querySelector('#overlay .tbody');
      if (!body) return false;
      const turns = body.querySelectorAll('.turn');
      const mark = body.querySelector('.waitmark');
      if (!turns.length || !mark) return false;
      const last = turns[turns.length - 1];
      return last.compareDocumentPosition(mark) & Node.DOCUMENT_POSITION_FOLLOWING;
    }"""
        )
    )


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-thread-wait-probe-"))
    directory = scratch / "session"
    port = free_port()
    server, log = serve(directory, port)
    base = f"http://127.0.0.1:{port}"
    post(
        base,
        "thread-created",
        THREAD,
        "human",
        {
            "decision": DECISION,
            "kind": "question",
            "title": "What an accepted write promises",
            "turns": [{"who": "human", "text": ASKED}],
        },
    )

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(base + "/")
        page.wait_for_timeout(1200)
        if page.locator('[data-act="takeover"]').count():
            page.click('[data-act="takeover"]')
            page.wait_for_timeout(800)
        open_thread(page)

        quiet = marker(page).count()

        # The lane says a tier has the turn. From here nothing else reaches the
        # log until the reply does.
        log.emit_status(STATUS_PHASE_COMPOSING, "the probe's turn", THREAD, tier="fast")
        page.wait_for_selector(
            f'#overlay .tbody .waitmark[data-channel="{THREAD}"][data-waited]', timeout=5000
        )
        placed = below_last_turn(page)
        first = (marker_seconds(page), header_seconds(page))
        page.wait_for_timeout(WAITED * 1000)
        second = (marker_seconds(page), header_seconds(page))
        # The whole marker rather than its clock element: what a human reads is
        # the line, and a probe that could only find a marker already carrying
        # the fix's markup would fail on the markup instead of on the clock.
        shown = marker(page).inner_text()

        post(
            base,
            "thread-turn",
            THREAD,
            "thread-agent",
            {"turns": [{"who": "thread-agent", "text": ANSWERED}]},
        )
        log.emit_status(STATUS_PHASE_REPLIED, "the probe's reply", THREAD)
        page.wait_for_timeout(2000)
        after = marker(page).count()
        turns = page.locator("#overlay .tbody .turn").count()
        browser.close()

    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)

    print(f"  before the lane spoke: {quiet} marker(s) in the thread")
    print(f"  on arrival: marker {first[0]}s, header {first[1]}s — reads {shown!r}")
    print(f"  {WAITED}s later: marker {second[0]}s, header {second[1]}s")
    print(f"  after the reply: {after} marker(s), {turns} turns")
    assert quiet == 0, "a thread nobody is answering is marked as waiting"
    assert placed, "the marker is not below the last turn"
    grew = second[0] - first[0]
    assert grew >= WAITED - 1, f"the marker's clock advanced {grew}s over {WAITED}s"
    assert abs(second[0] - second[1]) <= 1, (
        f"the thread says {second[0]}s and the header says {second[1]}s about the same wait"
    )
    assert f"{second[0]}s" in shown, f"the marker's data and its text disagree: {shown!r}"
    assert turns == 2, f"the reply never landed in the thread: {turns} turns"
    assert after == 0, "the marker is still waiting on a reply that has arrived"
    print("thread wait probe: clean")


if __name__ == "__main__":
    main()
