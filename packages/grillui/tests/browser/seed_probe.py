"""What a decision's seed prompts do on the page, measured in a browser.

A seed is text the handoff wrote for the human to say. What is measured here is
that it reaches the human as a control and that pressing one puts those exact
words into the log as their turn -- neither of which the source can answer,
because whether a button is on screen and whether a click lands on it are a
layout engine's answers.

    uv run --with playwright python tests/browser/seed_probe.py

It is deliberately outside `make ci-grillui`: the gate would have to carry a
browser and its binaries. It seeds its own session rather than taking a
directory, because the shape it needs is specific -- a decision carrying two
seeds, one carrying a single seed with a tag inside it, and one carrying none --
and it asserts that shape reached the board before it clicks anything, so a
board that could not have failed does not pass quietly.
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

WHY = "Recovery rests on it."
ZOOM = "Consider a crash mid-write."
TAGGED = "Why not <img src=x onerror=\"document.title='markup ran'\"> instead?"
NEVER_STARTED = "the backend never started"

HANDOFF = {
    "handoff_version": 1,
    "session": {
        "id": "seed-probe",
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
                "talk": {"why": WHY, "zoom": ZOOM},
            },
            {
                "id": "d2",
                "short": "Compaction",
                "title": "When is the log compacted?",
                "prereqs": [],
                "body": "Say when, or say never.",
                "options": [{"id": "a", "text": "Never"}, {"id": "b", "text": "On restart"}],
            },
            {
                "id": "d3",
                "short": "Fsync",
                "title": "How durable is an append?",
                "prereqs": [],
                "body": "Say what an accepted write promises.",
                "options": [{"id": "a", "text": "fsync each"}, {"id": "b", "text": "Batch"}],
                "talk": {"why": TAGGED},
            },
        ],
    },
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(directory: Path, port: int) -> uvicorn.Server:
    """A backend on loopback, and nothing the launch path does around it.

    The briefing is laid onto the board through the log rather than through the
    handoff door, because the door insists a seed object carry both of the
    fields it knows the names of. The board's own node shape does not, and
    neither does the node an agent mints mid-session -- so a decision carrying a
    single seed is a board state that happens and is unreachable from a file.
    """
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


def human_turns(base: str) -> list[tuple[str, str]]:
    """Every word the log holds as the human's, on any thread."""
    status = httpx.get(base + "/status").json()
    entries = httpx.get(base + "/updates", params={"epoch": status["epoch"], "cursor": 0}).json()
    said = []
    for entry in entries["entries"]:
        for turn in entry.get("payload", {}).get("turns", []) or []:
            if turn.get("who") == "human":
                said.append((entry["channel"], turn.get("text", "")))
    return said


def open_pane(page, decision):
    """The threads control on one decision's block: what a human presses to get
    at that decision's thread pane, whether or not a thread exists yet."""
    page.click(f'#col-{decision} [data-act="threads"]')
    page.wait_for_timeout(500)


def seeds(page):
    """The seed controls on the pane the board has open."""
    return page.locator('.slide [data-act="seed"]')


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-seed-probe-"))
    directory = scratch / "session"
    directory.mkdir(parents=True)
    port = free_port()
    server = serve(directory, port)
    base = f"http://127.0.0.1:{port}"

    board = httpx.get(base + "/state").json()["image1"]
    carried = {d["id"]: d.get("talk") for d in board["decisions"]}
    assert carried.get("d1") == {"why": WHY, "zoom": ZOOM}, carried
    assert carried.get("d3") == {"why": TAGGED}, carried
    assert not carried.get("d2"), f"the seedless decision carries seeds: {carried}"
    for one in ("d1", "d2", "d3"):
        assert one in board["frontier"], f"{one} is not open, so its pane is not the live one"

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(base + "/")
        page.wait_for_timeout(1200)
        if page.locator('[data-act="takeover"]').count():
            page.click('[data-act="takeover"]')
            page.wait_for_timeout(800)
        page.wait_for_selector("#col-d1", timeout=10000)

        # 1. Two seeds, two controls -- on a decision nothing has been said on
        #    yet, which is the pane a seed is written for.
        open_pane(page, "d1")
        assert seeds(page).count() == 2, f"d1 offers {seeds(page).count()} controls, not two"
        assert seeds(page).nth(0).inner_text().strip().endswith(WHY)
        seeds(page).nth(0).click()
        page.wait_for_timeout(1200)
        said = human_turns(base)
        assert any(text == WHY for _, text in said), f"the seed said nothing: {said}"
        channel = next(c for c, text in said if text == WHY)

        # 2. The thread now exists, and the pane still offers both seeds. Saying
        #    the second one lands on the same channel as the first.
        assert seeds(page).count() == 2, "the seeds went away once the thread existed"
        seeds(page).nth(1).click()
        page.wait_for_timeout(1200)
        said = human_turns(base)
        assert (channel, ZOOM) in said, f"the second seed missed the thread: {said}"

        # 3. A decision carrying no seeds offers no control, and one carrying a
        #    single seed offers exactly one.
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        open_pane(page, "d2")
        assert seeds(page).count() == 0, "a decision with no seeds rendered a seed control"
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        open_pane(page, "d3")
        assert seeds(page).count() == 1, f"d3 offers {seeds(page).count()} controls, not one"

        # 4. A tag inside a seed is words on a button, not markup on the page.
        assert "<img" in seeds(page).nth(0).inner_text(), "the tag is not on screen as text"
        assert page.locator("#col-d3 img").count() == 0, "the seed's tag became an element"
        assert page.title() != "markup ran", "the seed's markup ran"

        # 5. The popped-out thread is the same pane, so it offers the same
        #    seeds, and pressing one there says it on the same thread.
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        open_pane(page, "d1")
        with page.expect_popup() as popped:
            page.click('.slide [data-act="popout"]')
        window = popped.value
        window.wait_for_timeout(1500)
        offered = window.locator('[data-act="seed"]')
        assert offered.count() == 2, f"the popped window offers {offered.count()} controls"
        offered.nth(0).click()
        window.wait_for_timeout(1500)
        said = human_turns(base)
        assert len([1 for c, text in said if c == channel and text == WHY]) == 2, (
            f"the popped window's seed did not reach the thread: {said}"
        )

        browser.close()
    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("seed probe: clean")


if __name__ == "__main__":
    main()
