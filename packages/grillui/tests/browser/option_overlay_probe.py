"""What an option's trade-off costs the human to read, measured in a browser.

An option may carry three statements -- what it buys, what it costs, what it
forces later. They reach the human behind a small icon beside that option, and
that icon is the whole of the target: a target the size of the option itself
fires on every pass of the pointer towards the option, so the overlay covers
the answers at the moment the human is reaching for one. None of that is a
question the source can answer. Whether a target is only the icon, whether an
overlay lands on screen rather than off the bottom of it, and whether raising
one moves the board are a layout engine's answers.

    uv run --with playwright python tests/browser/option_overlay_probe.py

It is deliberately outside `make ci-grillui`: the gate would have to carry a
browser and its binaries. It seeds its own session, because the shape it needs
is specific -- one option carrying the trio and its neighbour carrying none, and
a decision long enough that its last option sits at the bottom edge of the pane
-- and it asserts that shape reached the board before it hovers anything, so a
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

BUYS = "Every answer ever given stays readable."
COSTS = "The session directory grows without bound."
FORCES = "Compaction has to be designed before launch."
# Long on purpose. The overlay is placed against its own measured height, and a
# short one would clear the bottom of the window whether it was measured or
# guessed -- so a check written against a short one proves nothing.
DEEP = [
    "The whole argument behind the name is recoverable months later without "
    "asking anyone who was in the room, because the words the human chose are "
    "the words the record keeps.",
    "Two people have to agree on the wording before either of them can move on, "
    "and that agreement is a conversation nobody has budgeted for on a day the "
    "decision looked obvious.",
    "Every downstream tool has to learn the vocabulary this pins, and each one "
    "that already shipped a different word for the same thing has to be "
    "migrated or left contradicting the board.",
]
NEVER_STARTED = "the backend never started"

# One decision the trio hangs off, one option beside it carrying none, and a run
# of decisions long enough that the pane scrolls and the last one's options sit
# at its bottom edge.
FILLER = [
    {
        "id": f"f{n}",
        "short": f"Filler {n}",
        "title": f"Filler question {n}?",
        "prereqs": [],
        "body": "A question that is here to make the pane taller than the window. " * 3,
        "options": [
            {"id": "a", "text": f"One way of answering filler {n}"},
            {"id": "b", "text": f"Another way of answering filler {n}"},
        ],
    }
    for n in range(1, 7)
]

HANDOFF = {
    "handoff_version": 1,
    "session": {
        "id": "option-overlay-probe",
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
                    {"id": "a", "text": "Append-only log", "pcr": [BUYS, COSTS, FORCES]},
                    {"id": "b", "text": "Mutable table"},
                ],
            },
            *FILLER,
            {
                "id": "d9",
                "short": "Naming",
                "title": "Whose words name a decision?",
                "prereqs": [],
                "body": "The last decision in the pane, so its options sit at the bottom edge. "
                * 4,
                "options": [
                    {"id": "a", "text": "The human's own words"},
                    {"id": "b", "text": "The agent's shorthand", "pcr": DEEP},
                ],
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


def overlay(page):
    """The overlay's text if one is on screen, and None if none is.

    Absent and present-but-hidden are the same answer to the only question
    asked here, and the element does not exist at all until the first one is
    raised -- so both have to read as nothing rather than as an error.
    """
    card = page.locator(".hovercard")
    if card.count() == 0:
        return None
    if card.evaluate("el => getComputedStyle(el).display") == "none":
        return None
    return card.inner_text()


def away(page):
    """Off every zone that owns an overlay, and settled."""
    page.mouse.move(3, 3)
    page.wait_for_timeout(200)


def board_position(page):
    """Where the board is and what holds the caret -- the two things raising an
    overlay must not touch."""
    return page.evaluate(
        "() => [document.getElementById('column').scrollTop, window.scrollY,"
        " document.activeElement ? document.activeElement.className : '']"
    )


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-option-overlay-probe-"))
    directory = scratch / "session"
    directory.mkdir(parents=True)
    port = free_port()
    server = serve(directory, port)
    base = f"http://127.0.0.1:{port}"

    board = httpx.get(base + "/state").json()["image1"]
    carried = {d["id"]: [o.get("pcr") for o in d["options"]] for d in board["decisions"]}
    assert carried.get("d1") == [[BUYS, COSTS, FORCES], None], carried
    assert carried.get("d9") == [None, DEEP], carried

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(base + "/")
        page.wait_for_timeout(1200)
        if page.locator('[data-act="takeover"]').count():
            page.click('[data-act="takeover"]')
            page.wait_for_timeout(800)
        page.wait_for_selector("#col-d1", timeout=10000)

        # 1. The option carrying the trio wears an icon; the one beside it does
        #    not. One icon on the decision, and it is in the first option's row.
        icons = page.locator("#col-d1 .pcricon")
        assert icons.count() == 1, f"d1 renders {icons.count()} icons, not one"
        rows = page.locator("#col-d1 .optrow")
        assert rows.count() == 2, f"d1 renders {rows.count()} option rows, not two"
        assert rows.nth(0).locator(".pcricon").count() == 1, "option (a) carries no icon"
        assert rows.nth(1).locator(".pcricon").count() == 0, "option (b) grew an icon"

        # 2. Hovering the icon raises the three statements, all of them.
        away(page)
        assert overlay(page) is None, "an overlay is up before anything was hovered"
        icons.first.hover()
        page.wait_for_timeout(250)
        raised = overlay(page)
        assert raised is not None, "hovering the icon raised nothing"
        for line in (BUYS, COSTS, FORCES):
            assert line in raised, f"the overlay is missing a statement: {raised!r}"

        # 3. The icon is the whole of the target. The option itself raises
        #    nothing, and neither does the decision block anywhere else.
        away(page)
        page.locator('#col-d1 [data-act="pick"][data-opt="a"]').hover()
        page.wait_for_timeout(250)
        assert overlay(page) is None, "the option itself is a hover target"
        away(page)
        page.locator("#col-d1 .q-body").hover()
        page.wait_for_timeout(250)
        assert overlay(page) is None, "the decision block is a hover target"

        # 4. Raising and dropping an overlay moves neither the board nor the
        #    caret -- the human reaching for an option keeps their place.
        away(page)
        before = board_position(page)
        icons.first.hover()
        page.wait_for_timeout(250)
        assert overlay(page) is not None
        assert board_position(page) == before, f"showing moved the board: {before}"
        away(page)
        assert overlay(page) is None, "the overlay stayed up after the pointer left"
        assert board_position(page) == before, f"hiding moved the board: {before}"

        # 5. The keyboard gets the same overlay: the icon takes focus and focus
        #    raises what hover raises.
        away(page)
        icons.first.focus()
        page.wait_for_timeout(250)
        focused = overlay(page)
        assert focused is not None, "focusing the icon raised nothing"
        assert BUYS in focused, f"focus raised a different overlay: {focused!r}"
        page.evaluate("() => document.activeElement.blur()")
        page.wait_for_timeout(250)
        assert overlay(page) is None, "the overlay outlived the focus that raised it"

        # 6. The last option of the pane, at the pane's bottom edge, still gets
        #    a readable overlay -- fixed to the window, so the pane's overflow
        #    never clips it and the window's own bottom edge never cuts it off.
        away(page)
        last = page.locator("#col-d9 .pcricon")
        assert last.count() == 1, "the last decision lost its icon"
        last.evaluate("el => el.scrollIntoView({block: 'end'})")
        page.wait_for_timeout(300)
        window_height = page.evaluate("() => window.innerHeight")
        spot = last.bounding_box()
        assert spot["y"] > window_height * 0.85, (
            f"the icon is not near the bottom edge ({spot['y']} of {window_height}), "
            "so this proves nothing -- the seeded pane is not tall enough"
        )
        last.hover()
        page.wait_for_timeout(250)
        deep = overlay(page)
        assert deep is not None, "the icon at the bottom edge raised nothing"
        for line in DEEP:
            assert line in deep, f"the overlay is missing a statement: {deep!r}"
        box = page.locator(".hovercard").bounding_box()
        width = page.evaluate("() => window.innerWidth")
        assert box["y"] >= 0 and box["y"] + box["height"] <= window_height, (
            f"the overlay runs off the window vertically: {box} of {window_height}"
        )
        assert box["x"] >= 0 and box["x"] + box["width"] <= width, (
            f"the overlay runs off the window horizontally: {box} of {width}"
        )

        # 7. It hides on a click and returns only on a fresh entry of the icon.
        away(page)
        icons.first.hover()
        page.wait_for_timeout(250)
        assert overlay(page) is not None
        icons.first.click()
        page.wait_for_timeout(400)
        assert overlay(page) is None, "the overlay survived a click"
        # A twitch inside the icon the click dismissed it on is not a fresh
        # entry, and the card the human just put away must stay away.
        held = icons.first.bounding_box()
        page.mouse.move(held["x"] + held["width"] / 2, held["y"] + held["height"] / 2 + 2)
        page.wait_for_timeout(250)
        assert overlay(page) is None, "the dismissed overlay came back without a fresh entry"
        away(page)
        icons.first.hover()
        page.wait_for_timeout(250)
        assert overlay(page) is not None, "a fresh entry did not bring the overlay back"

        browser.close()
    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("option overlay probe: clean")


if __name__ == "__main__":
    main()
