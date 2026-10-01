"""What the page says about which tier answered, measured in a browser.

Nothing pinned here is a property of the source. Whether a label is on screen,
whether it is still there after a reload, and whether choosing the other seat
rewrote history are all questions only a rendered page answers.

    uv run --with playwright python tests/browser/tier_label_probe.py

It is deliberately outside `make ci-grillui`: the gate would have to carry a
browser and its binaries, and what it pins is pinned in the suite as the source
invariant that produces it.

It seeds its own session rather than taking a directory, because the shape it
needs is specific -- one fast-tier agent turn and one heavy one on the same channel,
on a thread and on the map channel alike -- and no real session is guaranteed to
have been transferred. It asserts that shape reached the board before it reads
anything off the page, so a board that could not have failed does not pass.
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

FAST_SAID = "The fast tier answered this one."
HEAVY_SAID = "The expert tier answered this one."
FAST_LABEL = "assistant"
HEAVY_LABEL = "expert"
THREAD = "t-probe"
NEVER_STARTED = "the backend never started"

HANDOFF = {
    "handoff_version": 1,
    "session": {
        "id": "tier-label-probe",
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
                "id": "d1",
                "short": "Store",
                "title": "Which storage?",
                "prereqs": [],
                "body": "Pick the storage layer.",
                "options": [{"id": "a", "text": "Append-only log"}, {"id": "b", "text": "Table"}],
            },
        ],
    },
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


def say(base: str, *events: dict) -> None:
    """Put turns into the log the way a driver does: attributed, on a channel."""
    status = httpx.get(base + "/status").json()
    posted = httpx.post(base + "/events", json={"epoch": status["epoch"], "events": list(events)})
    for receipt in posted.json():
        assert receipt["status"] == "accepted", receipt


def turn(kind: str, channel: str, text: str, tier: str | None, target: str | None = None) -> dict:
    """One entry, attributed as `record_reply` attributes an agent's reply: the
    tier is a payload key on the entry rather than a field of the envelope."""
    payload: dict = {"text": text}
    if tier is not None:
        payload["tier"] = tier
        payload["model"] = f"{tier}-model"
    if target is not None:
        payload["target"] = target
    return {
        "kind": kind,
        "actor": "grill-master" if channel == "map" else "thread-agent",
        "channel": channel,
        "idempotency_key": f"probe-{tier}-{channel}-{time.time()}",
        "payload": payload,
    }


def human_turn(channel: str, text: str) -> dict:
    return {
        "kind": "thread-turn",
        "actor": "human",
        "channel": channel,
        "idempotency_key": f"probe-human-{channel}-{text[:6]}-{time.time()}",
        "payload": {"turns": [{"who": "human", "text": text}]},
    }


def open_thread(base: str) -> None:
    say(
        base,
        {
            "kind": "thread-created",
            "actor": "human",
            "channel": THREAD,
            "idempotency_key": "probe-thread",
            "payload": {
                "decision": "d1",
                "kind": "clarify",
                "title": "Storage, at length",
                "text": "Why the append-only log?",
            },
        },
    )


def enter(page, base: str) -> None:
    page.goto(base + "/")
    page.wait_for_timeout(1200)
    if page.locator('[data-act="takeover"]').count():
        page.click('[data-act="takeover"]')
        page.wait_for_timeout(800)
    page.wait_for_selector("#col-d1", timeout=10000)


def thread_labels(page) -> list[str]:
    """Every `who` line in the open thread pane, as the DOM holds it.

    `textContent` rather than the rendered text: the line is uppercased by the
    stylesheet, the same as `YOU` and `BACKEND` beside it, and what is being
    measured is which words the page chose, not how the sheet cased them.
    """
    return page.eval_on_selector_all(
        ".threadpane .tbody .turn .who",
        "els => els.map(e => e.childNodes[0].textContent.trim())",
    )


def open_pane(page) -> None:
    page.click('#col-d1 [data-act="threads"]')
    page.wait_for_timeout(400)
    page.click(f'[data-act="openthread"][data-tid="{THREAD}"]')
    page.wait_for_timeout(600)


def map_notes(page) -> list[list[str]]:
    """Every note on the decision column, as `[label, text]`, so a label is
    judged against the turn it sits on and not merely counted."""
    return page.eval_on_selector_all(
        "#col-d1 .infonote",
        """els => els.map(e => [e.querySelector("strong").textContent.trim(),
                              e.textContent])""",
    )


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-tier-label-probe-"))
    directory = scratch / "session"
    directory.mkdir(parents=True)
    port = free_port()
    server = serve(directory, port)
    base = f"http://127.0.0.1:{port}"

    open_thread(base)
    say(base, turn("thread-turn", THREAD, FAST_SAID, "fast"))
    say(base, human_turn(THREAD, "Take that to the expert."))
    say(base, turn("thread-turn", THREAD, HEAVY_SAID, "heavy"))
    say(base, turn("informational", "map", FAST_SAID, "fast", target="d1"))
    say(base, turn("informational", "map", HEAVY_SAID, "heavy", target="d1"))

    # The projection is what a rejoining page reads, so the tier has to be in it
    # before anything about a reload is claimed.
    projected = httpx.get(base + "/state").json()["image1"]["threads"][0]["turns"]
    assert [t.get("tier") for t in projected] == [None, "fast", None, "heavy"], projected

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1360, "height": 900})
        enter(page, base)

        # 1. Each agent turn on a thread wears the tier that took it, and the
        #    human's wears no tier at all.
        open_pane(page)
        labels = thread_labels(page)
        assert labels == ["You", FAST_LABEL, "You", HEAVY_LABEL], (
            f"the thread's turns are not labelled by their own tier: {labels}"
        )

        # 2. The map channel's turns are labelled the same way. They reach the
        #    page as queue items rather than as projected turns, which is a
        #    second read path and so a second place the label can go missing.
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        notes = map_notes(page)
        fast_note = next((n for n in notes if FAST_SAID in n[1]), None)
        heavy_note = next((n for n in notes if HEAVY_SAID in n[1]), None)
        assert fast_note and fast_note[0].startswith(FAST_LABEL), (
            f"the fast tier's map note is not labelled {FAST_LABEL}: {notes}"
        )
        assert heavy_note and heavy_note[0].startswith(HEAVY_LABEL), (
            f"the expert tier's map note is not labelled {HEAVY_LABEL}: {notes}"
        )

        # 3. Choosing the other seat does not rewrite what already happened. A
        #    page reading the channel's mode instead of the turn would relabel
        #    the whole transcript here, which is exactly the evidence the human
        #    needs. The seat toggle lives in the pane, so the pane is opened first.
        open_pane(page)
        page.click(f'.threadpane .seats[data-channel="{THREAD}"] [data-seat="heavy"]')
        page.wait_for_timeout(400)
        after_toggle = thread_labels(page)
        assert after_toggle == labels, f"choosing the expert seat rewrote history: {after_toggle}"
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        #    The map channel has a seat toggle of its own, and its notes are the
        #    other transcript a mode-reading page would relabel.
        page.click('.seats[data-channel="map"] [data-seat="heavy"]')
        page.wait_for_timeout(400)
        map_after_toggle = map_notes(page)
        assert map_after_toggle == notes, (
            f"choosing the map's expert seat rewrote its notes: {map_after_toggle}"
        )

        # 4. A page that reloads -- and so was never there for the turns -- reads
        #    the same labels off the projection, on the thread and on the map
        #    channel alike. The map's notes are hydrated from the queue rather
        #    than arriving live, which is a third place the label can go missing.
        enter(page, base)
        open_pane(page)
        reloaded = thread_labels(page)
        assert reloaded == labels, f"the reload lost the thread labels: {reloaded}"
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        rehydrated = map_notes(page)
        assert rehydrated == notes, f"the reload lost the map labels: {rehydrated}"
        print(f"  thread: {labels}")
        print(f"  map: {[n[0] for n in notes]}")

        browser.close()
    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("tier label probe: clean")


if __name__ == "__main__":
    main()
