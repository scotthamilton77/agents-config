"""The header and the help thread, measured in a browser.

Two rendered facts live here and nowhere else. Whether the session's own name
is what a human reads at the top of the board, and whether a title carrying a
tag arrives as words rather than as an element, are a layout engine's answers --
the source can only say which string was passed to which sink. So is whether the
help control is on screen at all, and whether pressing it opens a thread the
human can say something into.

    uv run --with playwright python tests/browser/help_probe.py

It is deliberately outside `make ci-grillui`: the gate would have to carry a
browser and its binaries, and what this pins is pinned in the suite as the
source invariant and the wire behaviour that produce it.

It seeds three sessions rather than taking a directory, because the shapes it
needs are specific: one briefed with a plain title and reference material, one
whose title carries markup, and one briefed with neither a title nor material. Each is
asserted to have reached the board before anything is clicked, so a session that
could not have failed does not pass quietly.
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
from grillui.dispatch import DISPATCH_DIR, record_dispatch
from grillui.log import SessionLog
from grillui.persistence import project_and_persist
from grillui.schemas import SESSION_START_KIND, DispatchContext

NEVER_STARTED = "the backend never started"

TITLE = "Session store design"
MARKUP_TITLE = "Store <img src=x onerror=\"document.title='markup ran'\"> design"
GENERIC = "Grilling session"
# What the orchestrator ships about driving the board. One distinctive sentence
# is enough: what is measured is that these bytes reached the agent's recorded
# context, not that the whole reference is quoted here.
REFERENCE = "Park a thread to set it aside; folding hands its conclusion to the map agent."
ASKED = "What does the map doctor do?"
# The prose that used to sit under the header, telling every human who owns the
# log on their way to the first decision.
OWNERSHIP = "The backend owns this session"


def handoff(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "handoff_version": 1,
        "session": {
            "id": "help-probe",
            "title": TITLE,
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
    return {**document, **overrides}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(directory: Path, document: dict[str, Any]) -> tuple[uvicorn.Server, str, SessionLog]:
    """A backend on loopback, and nothing the launch path does around it.

    The briefing is laid onto the board through the log rather than through the
    handoff door, so a title the door would refuse -- an empty one -- is a board
    state this can reach.
    """
    directory.mkdir(parents=True, exist_ok=True)
    log = SessionLog(directory)
    log.record(SESSION_START_KIND, document)
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


def board(base: str) -> dict[str, Any]:
    read: dict[str, Any] = httpx.get(base + "/state").json()["image1"]
    return read


def open_board(play: Any, base: str) -> Any:
    page = play.chromium.launch(headless=True).new_page(viewport={"width": 1280, "height": 900})
    page.goto(base + "/")
    page.wait_for_timeout(1200)
    if page.locator('[data-act="takeover"]').count():
        page.click('[data-act="takeover"]')
        page.wait_for_timeout(800)
    page.wait_for_selector("#col-d1", timeout=10000)
    return page


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-help-probe-"))
    named, tagged, bare = (
        serve(scratch / "named", handoff(help_reference=REFERENCE)),
        serve(
            scratch / "tagged",
            handoff(session={**handoff()["session"], "title": MARKUP_TITLE}),
        ),
        serve(scratch / "bare", handoff(session={**handoff()["session"], "title": ""})),
    )

    # Preconditions, before a single click: each board is up, and each carries
    # the briefing this arm is about.
    for _server, base, _log in (named, tagged, bare):
        assert board(base)["decisions"], f"{base} served an empty board"

    with sync_playwright() as play:
        # 1. The header is the session's own name, and the ownership paragraph
        #    that used to sit under it is gone.
        page = open_board(play, named[1])
        header = page.locator(".intro h1")
        assert header.inner_text().strip() == TITLE, header.inner_text()
        assert page.locator(".intro p").count() == 0, "the header still carries a paragraph"
        assert OWNERSHIP not in page.locator("#shell").inner_text()

        # 2. The help control is on screen, in the upper right of the top row.
        help_control = page.locator('[data-act="help"]')
        assert help_control.count() == 1, f"{help_control.count()} help controls"
        chip = page.locator("#indicator").bounding_box()
        spot = help_control.bounding_box()
        assert spot["x"] > chip["x"], "the help control is not to the right of the top row"

        # 3. Pressing it opens a thread pane that has not created a thread, and
        #    saying something in it opens one anchored to no decision.
        assert not board(named[1])["threads"], "a thread existed before anything was said"
        help_control.click()
        page.wait_for_timeout(500)
        assert page.locator(".slide.left.pane").count() == 1, "no help pane opened"
        assert not board(named[1])["threads"], "opening the help pane created a thread"
        page.fill(".slide #ft-say", ASKED)
        page.click('.slide [data-act="draftsay"]')
        page.wait_for_timeout(1500)

        threads = board(named[1])["threads"]
        assert len(threads) == 1, threads
        assert threads[0]["decision"] is None, threads[0]
        assert [one["text"] for one in threads[0]["turns"]] == [ASKED], threads[0]

        # 4. The recorded dispatch for that thread carries the material the
        #    handoff shipped -- read off the backend's own record, not the page.
        recorded = record_dispatch(named[2], channel=threads[0]["id"]).read_text(encoding="utf-8")
        context = DispatchContext.model_validate_json(recorded)
        assert context.help_reference == REFERENCE, context.help_reference
        assert (scratch / "named" / DISPATCH_DIR).is_dir()

        # 5. A title carrying a tag is words at the top of the page, not an
        #    element, and its script does not run.
        tagged_page = open_board(play, tagged[1])
        assert tagged_page.locator(".intro h1").inner_text().strip() == MARKUP_TITLE
        assert tagged_page.locator(".intro h1 img").count() == 0, (
            "the title's tag became an element"
        )
        assert tagged_page.title() != "markup ran", "the title's markup ran"

        # 6. A briefing that named the session nothing opens under the generic
        #    header rather than under a blank one, and one that shipped no
        #    reference material offers no help control -- and is otherwise a
        #    working board.
        bare_page = open_board(play, bare[1])
        assert bare_page.locator(".intro h1").inner_text().strip() == GENERIC
        assert bare_page.locator('[data-act="help"]').count() == 0, "help was offered unprimed"
        assert bare_page.locator('[data-act="endsession"]').count() == 1, "the board is not live"

    for server, _base, _log in (named, tagged, bare):
        server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("help probe: clean")


if __name__ == "__main__":
    main()
