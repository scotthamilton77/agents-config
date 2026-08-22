"""Whether the diagnostic's per-channel clock actually runs, measured in a browser.

    uv run --with playwright python tests/browser/diag_timer_probe.py

Whether a number on screen advances is not a property of the source. A row drawn
once and a row ticked every second are the same markup at the instant they are
written and differ only later, so the only way to tell them apart is to open the
diagnostic, wait, and look again -- while nothing else happens, because the board
re-renders when the log moves and a wait is exactly a log that is not moving.

The header's clock is read on the same two beats. What the row has to do is not
merely advance: it has to advance in step with the header, since the two are the
same wait told twice and a human reading them side by side is reading them for
the disagreement.

It seeds its own session and opens one turn nothing ever answers, because a real
session directory is not guaranteed to be mid-turn when it is handed over. Like
the other probes here it is outside `make ci-grillui`, which would have to carry
a browser to run it.
"""

from __future__ import annotations

import re
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

from grillui.api import create_app
from grillui.log import SessionLog
from grillui.persistence import project_and_persist
from grillui.schemas import MAP_CHANNEL, SESSION_START_KIND, STATUS_PHASE_COMPOSING

# Long enough that a stopped clock and a running one cannot be confused for one
# another by a scheduling wobble, short enough to stay a probe.
WAITED = 4
NEVER_STARTED = "the backend never started"

HANDOFF = {
    "handoff_version": 1,
    "session": {
        "id": "diag-timer-probe",
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


def enter(page, base: str) -> None:
    page.goto(base + "/")
    page.wait_for_timeout(1200)
    if page.locator('[data-act="takeover"]').count():
        page.click('[data-act="takeover"]')
        page.wait_for_timeout(800)
    page.wait_for_selector("#col-d1", timeout=10000)


def header_seconds(page) -> int:
    """The seconds the header's own clock is showing, off its text."""
    text = page.locator("#lanetimer").inner_text()
    found = re.search(r"(\d+)s", text)
    assert found, f"the header is showing no clock at all: {text!r}"
    return int(found.group(1))


def row_seconds(page) -> int:
    return int(page.locator(f'.diagrow[data-channel="{MAP_CHANNEL}"]').get_attribute("data-waited"))


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-diag-timer-probe-"))
    directory = scratch / "session"
    directory.mkdir()
    port = free_port()
    server, log = serve(directory, port)

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        enter(page, f"http://127.0.0.1:{port}")

        # One turn opened and never closed: the channel owes a reply, and from
        # here nothing further reaches the log.
        log.emit_status(STATUS_PHASE_COMPOSING, "the probe's turn", MAP_CHANNEL, tier="fast")
        page.wait_for_selector("#lanetimer", timeout=10000)
        page.click("#indicator")
        page.wait_for_selector(f'.diagrow[data-channel="{MAP_CHANNEL}"][data-waited]', timeout=5000)

        first = (row_seconds(page), header_seconds(page))
        page.wait_for_timeout(WAITED * 1000)
        second = (row_seconds(page), header_seconds(page))

        # The whole row rather than the clock's own element: what a human reads
        # is the line, and a probe that could only find a row already carrying
        # the fix's markup would fail on the markup instead of on the clock.
        clock = page.locator(f'.diagrow[data-channel="{MAP_CHANNEL}"]').inner_text()
        browser.close()

    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)

    print(f"  on opening: row {first[0]}s, header {first[1]}s")
    print(f"  {WAITED}s later: row {second[0]}s, header {second[1]}s — row reads {clock!r}")
    grew = second[0] - first[0]
    assert grew >= WAITED - 1, f"the row's clock advanced {grew}s over {WAITED}s"
    assert abs(second[0] - second[1]) <= 1, (
        f"the row says {second[0]}s and the header says {second[1]}s about the same wait"
    )
    assert f"{second[0]}s" in clock, f"the row's data and its text disagree: {clock!r}"
    print("diagnostic timer probe: clean")


if __name__ == "__main__":
    main()
