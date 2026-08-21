"""Parking and closing a thread, measured in a browser.

Three rendered facts live here and nowhere else. Whether the two gestures are
actually side by side in the pane's foot, so the human is offered the choice
rather than one half of it; whether a closed thread is still readable and still
takes a turn that opens it again; and whether an ended session takes both
controls away. The source can say which branch builds which button -- it cannot
say that a human saw two of them, that a click on one reached the log, or that
the turn typed into a closed thread came back as an open one.

    uv run --with playwright python tests/browser/lifecycle_probe.py

It is deliberately outside `make ci-grillui`: the gate would have to carry a
browser and its binaries, and what this pins is pinned in the suite as the
source invariant and the wire behaviour that produce it.

One session driven through the whole arc, because the arc is the subject. Every
stage asserts the board it is acting on before it acts, so a stage that could
not have failed does not pass quietly.
"""

from __future__ import annotations

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

NEVER_STARTED = "the backend never started"
PARK = '[data-act="park"]'
CLOSE = '[data-act="closethread"]'
END = '[data-act="endsession"]'
PARKED_ASKED = "What backs the session directory up?"
CLOSED_ASKED = "What are the log files called?"
REOPENED = "Actually — are they named for the session id?"


def handoff() -> dict[str, Any]:
    return {
        "handoff_version": 1,
        "session": {
            "id": "lifecycle-probe",
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
                    "options": [
                        {"id": "a", "text": "Append-only log"},
                        {"id": "b", "text": "Table"},
                    ],
                }
            ],
        },
    }


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(directory: Path) -> tuple[uvicorn.Server, str, SessionLog]:
    """A backend on loopback, and nothing the launch path does around it."""
    directory.mkdir(parents=True, exist_ok=True)
    log = SessionLog(directory)
    log.record(SESSION_START_KIND, handoff())
    project_and_persist(log)
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(log), host="127.0.0.1", port=port, log_level="error")
    )
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server, f"http://127.0.0.1:{port}", log
        time.sleep(0.1)
    raise AssertionError(NEVER_STARTED)


def threads(base: str) -> dict[str, dict[str, Any]]:
    board: dict[str, Any] = httpx.get(base + "/state").json()["image1"]
    return {one["id"]: one for one in board["threads"]}


def open_board(play: Any, base: str) -> Any:
    page = play.chromium.launch(headless=True).new_page(viewport={"width": 1280, "height": 900})
    page.goto(base + "/")
    page.wait_for_timeout(1200)
    if page.locator('[data-act="takeover"]').count():
        page.click('[data-act="takeover"]')
        page.wait_for_timeout(800)
    page.wait_for_selector("#col-d1", timeout=10000)
    return page


def start_thread(page: Any, base: str, said: str) -> str:
    """Open a thread on d1 by saying the first thing in it, and return its id."""
    before = set(threads(base))
    # The frontier decision is already expanded; a decision that is not has to
    # be opened before its ⑂ is on screen at all.
    if not page.locator('[data-act="newthread"][data-id="d1"]').count():
        page.click('[data-act="toggle"][data-id="d1"]')
        page.wait_for_timeout(300)
    page.click('[data-act="newthread"][data-id="d1"]')
    page.wait_for_timeout(400)
    page.fill(".slide #ft-say", said)
    page.click('.slide [data-act="draftsay"]')
    fresh: set[str] = set()
    for _ in range(50):
        fresh = set(threads(base)) - before
        if fresh:
            page.wait_for_timeout(400)
            break
        page.wait_for_timeout(200)
    assert fresh, f"no thread was opened by {said!r}"
    return fresh.pop()


def open_pane(page: Any, tid: str) -> None:
    page.click(f'[data-act="openthread"][data-tid="{tid}"]')
    page.wait_for_timeout(400)


def wait_for_state(base: str, tid: str, state: str) -> None:
    for _ in range(50):
        if threads(base)[tid]["state"] == state:
            return
        time.sleep(0.2)
    assert threads(base)[tid]["state"] == state, f"{tid} never became {state!r}"


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-lifecycle-probe-"))
    server, base, log = serve(scratch / "session")

    # Precondition, before a single click: the board is up and carries no
    # thread at all, so nothing below can pass against a session that arrived
    # with its threads already in some state.
    assert not threads(base), "a thread existed before anything was said"

    with sync_playwright() as play:
        page = open_board(play, base)

        # 1. Two threads, each opened by saying something in it. Both are open,
        #    and both offer the two gestures side by side -- which is the
        #    non-vacuity precondition for every stage below.
        parked = start_thread(page, base, PARKED_ASKED)
        page.click('.slide [data-act="closepanel"]')
        page.wait_for_timeout(300)
        closed = start_thread(page, base, CLOSED_ASKED)
        assert {parked, closed} == set(threads(base)), threads(base)
        assert threads(base)[closed]["state"] == "open", threads(base)[closed]
        assert page.locator(f".slide {PARK}").count() == 1, "the pane offers no park"
        assert page.locator(f".slide {CLOSE}").count() == 1, "the pane offers no close"
        assert page.locator(f".slide {CLOSE}").is_visible(), "the close is not on screen"

        # 2. Closing one. Its turns stay on screen, and the pane says how to
        #    pick it back up rather than going read-only.
        page.click(f".slide {CLOSE}")
        wait_for_state(base, closed, "closed")
        page.wait_for_timeout(600)
        open_pane(page, closed)
        pane = page.locator(".slide").inner_text()
        assert CLOSED_ASKED in pane, "the closed thread's turn is not readable"
        assert "closed" in pane, pane
        assert page.locator(f".slide {PARK}").count() == 0, "a closed thread still offers park"

        # 3. A turn in the closed thread opens it again and is kept, and the
        #    gestures come back with it.
        page.fill(".slide #ft-say", REOPENED)
        page.click('.slide [data-act="say"]')
        wait_for_state(base, closed, "open")
        page.wait_for_timeout(600)
        said = [one["text"] for one in threads(base)[closed]["turns"]]
        assert said[:2] == [CLOSED_ASKED, REOPENED], said
        pane = page.locator(".slide").inner_text()
        assert CLOSED_ASKED in pane and REOPENED in pane, "the re-opened thread lost a turn"
        assert page.locator(f".slide {CLOSE}").count() == 1, "the re-opened thread cannot be closed"

        # 4. The pop-out is the same pane, so it offers the same two gestures
        #    and its close reaches the log.
        page.click('.slide [data-act="popout"]')
        page.wait_for_timeout(800)
        popped = page.context.pages[-1]
        assert popped is not page, "the pop-out did not open a window"
        assert popped.locator(PARK).count() == 1, "the popped window offers no park"
        assert popped.locator(CLOSE).count() == 1, "the popped window offers no close"
        popped.click(CLOSE)
        wait_for_state(base, closed, "closed")

        # 5. Park the other one, so the session ends carrying one of each, and
        #    the result says so.
        page.click(f'[data-act="openthread"][data-tid="{parked}"]')
        page.wait_for_timeout(500)
        assert page.locator(f".slide {PARK}").count() == 1, "the second thread offers no park"
        page.click(f".slide {PARK}")
        wait_for_state(base, parked, "parked")
        assert {tid: one["state"] for tid, one in threads(base).items()} == {
            parked: "parked",
            closed: "closed",
        }

        # 6. Ending the session takes both gestures away -- neither is a click
        #    the ended board swallows.
        page.click(f".topbar {END}")
        page.wait_for_timeout(1500)
        assert not page.is_closed(), "the tab closed -- the ended surface was never seen"
        for control in (PARK, CLOSE):
            live = [one for one in page.locator(control).all() if one.is_enabled()]
            assert not live, f"the ended board still offers {control}"
        assert (scratch / "session" / "result.json").exists(), "no terminal result was written"
        ended = [one for one in log.entries() if one.kind == "session-end"]
        assert len(ended) == 1, f"{len(ended)} session-end entries"

    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("lifecycle probe: clean")


if __name__ == "__main__":
    main()
