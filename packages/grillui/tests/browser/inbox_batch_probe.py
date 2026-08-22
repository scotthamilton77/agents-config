"""Whether the inbox's batch control is on screen when the inbox opens.

    uv run --with playwright python tests/browser/inbox_batch_probe.py

Eight changes queue up over a session that ran for an evening, and the control
that lets them all land renders after the list of them. On a laptop-height
window that puts it below the fold, and a human who does not scroll past eight
rows applies eight rows by hand -- which is what happened. Where a control is
relative to the viewport is not a question the source can answer, so this opens
a real inbox on a short viewport, measures the control's box against the window
before anything is scrolled, and then presses it and watches the queue drain.

It is deliberately outside `make ci-grillui`: the gate would have to carry a
browser and its binaries. It seeds its own session, and asserts the eight
changes reached the queue before it opens anything, so an inbox that could not
have failed does not pass quietly.
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

# Eight, because eight is what the live session queued. The number is the whole
# point: at one or two the foot control is on screen anyway.
QUEUED = 8

# Short enough to be a laptop window with a browser's chrome taken off it.
VIEWPORT = {"width": 1400, "height": 700}

DECISIONS: list[dict[str, Any]] = [
    {
        "id": f"d{n}",
        "short": f"Q{n}",
        "title": f"Question {n} of the store design?",
        "prereqs": [],
        "body": "One of the eight the grill-master went on to invalidate.",
        "options": [{"id": "a", "text": "Yes"}, {"id": "b", "text": "No"}],
    }
    for n in range(1, QUEUED + 1)
]

HANDOFF = {
    "handoff_version": 1,
    "session": {
        "id": "inbox-batch-probe",
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


def pending(base: str) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = httpx.get(base + "/state").json()["image1"]["pending"]
    return [item for item in queue if not item["superseded"]]


def seed(base: str) -> None:
    """Eight invalidates from the grill-master, each waiting on the human."""
    epoch = httpx.get(base + "/status").json()["epoch"]
    receipts = httpx.post(
        base + "/events",
        json={
            "epoch": epoch,
            "events": [
                {
                    "kind": "invalidate",
                    "actor": "grill-master",
                    "channel": "map",
                    "idempotency_key": f"kill-{n}",
                    "payload": {"target": f"d{n}", "why": "the thread moved past it"},
                }
                for n in range(1, QUEUED + 1)
            ],
        },
    ).json()
    for receipt in receipts:
        assert receipt["status"] == "accepted", receipt
    assert len(pending(base)) == QUEUED, f"{len(pending(base))} changes wait, not {QUEUED}"


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-inbox-batch-probe-"))
    directory = scratch / "session"
    directory.mkdir(parents=True)
    port = free_port()
    server = serve(directory, port)
    base = f"http://127.0.0.1:{port}"
    seed(base)

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport=VIEWPORT)
        page.goto(base + "/")
        page.wait_for_timeout(1200)
        if page.locator('[data-act="takeover"]').count():
            page.click('[data-act="takeover"]')
            page.wait_for_timeout(800)
        page.wait_for_selector("#col-d1", timeout=10000)

        # The inbox, opened the way the human opens it, and nothing scrolled.
        page.click(".pendbtn")
        page.wait_for_timeout(400)
        page.wait_for_selector(".slide .pending-list")
        rows = page.locator(".slide .pending-row")
        assert rows.count() == QUEUED, f"the inbox shows {rows.count()} rows, not {QUEUED}"

        controls = page.locator('.slide [data-act="applyall"]')
        assert controls.count(), "the inbox offers no way to let the whole queue land"

        # The one this probe exists for: a live control inside the window, with
        # nothing scrolled and no row pressed.
        height = page.evaluate("window.innerHeight")
        boxes = [controls.nth(index).bounding_box() for index in range(controls.count())]
        on_screen = [
            index
            for index, box in enumerate(boxes)
            if not controls.nth(index).is_disabled()
            and box is not None
            and box["y"] >= 0
            and box["y"] + box["height"] <= height
        ]
        assert on_screen, (
            "no live batch control is in the viewport when the inbox opens: "
            f"boxes {boxes} against a {height}px window"
        )

        # And the copy under the list, which is the one that was always there,
        # is still there -- the head copy is an addition, not a move.
        assert controls.count() == 2, (
            f"{controls.count()} batch controls, not one in the head and one at the foot"
        )
        for index in range(controls.count()):
            assert f"Let all {QUEUED} land" in controls.nth(index).inner_text(), (
                f"batch control {index} does not name the {QUEUED} changes waiting"
            )

        # And it is the whole gesture: pressing it drains the queue.
        controls.nth(on_screen[0]).click()
        page.wait_for_timeout(1500)
        assert not pending(base), f"{len(pending(base))} changes still wait after the batch apply"

        browser.close()
    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("inbox batch probe: clean")


if __name__ == "__main__":
    main()
