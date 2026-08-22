"""Which key sends what is in a composer, measured in a browser.

    uv run --with playwright python tests/browser/chord_probe.py

A chord is not a property of the source. Whether Enter reached the box or the
button, whether a modifier was seen, whether the newline the human asked for is
in the value afterwards -- these are a browser's answers, and the popped-out
thread is a second document that has to give the same ones.

Like the other probes here it is outside `make ci-grillui`, which would have to
carry a browser to run it. It seeds its own session, because the shape it needs
is one open decision with a thread that does not exist yet: the first Enter is
what opens the thread, and every chord after it lands on a thread that does.
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
# Enter mid-composition is the IME committing a candidate. The page cannot be made
# to compose from a test keyboard, so the keystroke is delivered as the event an IME
# would raise -- which is the only thing the page reads.
COMPOSING = """() => {
  const box = document.getElementById('ft-say');
  box.dispatchEvent(new KeyboardEvent('keydown',
    {key: 'Enter', bubbles: true, cancelable: true, isComposing: true}));
}"""

HANDOFF = {
    "handoff_version": 1,
    "session": {
        "id": "chord-probe",
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
            }
        ],
    },
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(directory: Path, port: int) -> uvicorn.Server:
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


def said(base: str) -> list[str]:
    """Every word the log holds as the human's, on any thread."""
    status = httpx.get(base + "/status").json()
    entries = httpx.get(base + "/updates", params={"epoch": status["epoch"], "cursor": 0}).json()
    return [
        turn.get("text", "")
        for entry in entries["entries"]
        for turn in entry.get("payload", {}).get("turns", []) or []
        if turn.get("who") == "human"
    ]


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-chord-probe-"))
    directory = scratch / "session"
    directory.mkdir(parents=True)
    port = free_port()
    server = serve(directory, port)
    base = f"http://127.0.0.1:{port}"

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(base + "/")
        page.wait_for_timeout(1200)
        if page.locator('[data-act="takeover"]').count():
            page.click('[data-act="takeover"]')
            page.wait_for_timeout(800)
        page.wait_for_selector("#col-d1", timeout=10000)
        page.click('#col-d1 [data-act="threads"]')
        page.wait_for_timeout(600)
        page.wait_for_selector("#ft-say")

        # 0. The hint beside the box says which key does what.
        hint = page.locator(".slide .free .hint").first.inner_text()
        assert "↵ send" in hint and "⇧↵" in hint, f"the hint does not state the chord: {hint!r}"

        # 1. Enter sends -- here on a thread that does not exist yet, so the send
        #    is also what opens it.
        page.click("#ft-say")
        page.keyboard.type("opening turn")
        page.keyboard.press("Enter")
        page.wait_for_timeout(1500)
        assert "opening turn" in said(base), f"Enter did not send: {said(base)}"
        page.wait_for_selector("#ft-say")

        # 2. Shift+Enter is a newline and sends nothing.
        before = len(said(base))
        page.click("#ft-say")
        page.keyboard.type("second")
        page.keyboard.press("Shift+Enter")
        page.keyboard.type("line")
        page.wait_for_timeout(400)
        held = page.input_value("#ft-say")
        assert held == "second\nline", f"Shift+Enter left {held!r}"
        assert len(said(base)) == before, f"Shift+Enter sent something: {said(base)}"

        # 3. A backslash right before Enter is a newline too, and is eaten.
        page.keyboard.type("\\")
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
        held = page.input_value("#ft-say")
        assert held == "second\nline\n", f"backslash+Enter left {held!r}"
        assert len(said(base)) == before, f"backslash+Enter sent something: {said(base)}"

        # 4. Enter mid-composition is the IME's, not the board's.
        page.evaluate(COMPOSING)
        page.wait_for_timeout(400)
        assert len(said(base)) == before, f"a composing Enter sent something: {said(base)}"
        assert page.input_value("#ft-say") == held, "a composing Enter changed the box"

        # 5. Cmd/Ctrl+Enter still sends, so the chord fingers already know is kept.
        page.keyboard.press("Control+Enter")
        page.wait_for_timeout(1500)
        assert "second\nline" in said(base), f"Ctrl+Enter did not send: {said(base)}"

        # 6. The popped-out thread is another document, and answers the same keys.
        page.wait_for_selector("#ft-say")
        with page.expect_popup() as popped:
            page.click('.slide [data-act="popout"]')
        window = popped.value
        window.wait_for_timeout(1500)
        window.wait_for_selector("#pop-say")
        before = len(said(base))
        window.click("#pop-say")
        window.keyboard.type("popped")
        window.keyboard.press("Shift+Enter")
        window.keyboard.type("\\")
        window.keyboard.press("Enter")
        window.keyboard.type("turn")
        window.wait_for_timeout(400)
        held = window.input_value("#pop-say")
        assert held == "popped\n\nturn", f"the popped window's newlines left {held!r}"
        assert len(said(base)) == before, f"the popped window sent early: {said(base)}"
        window.keyboard.press("Enter")
        window.wait_for_timeout(1800)
        assert "popped\n\nturn" in said(base), f"Enter did not send in the pop-out: {said(base)}"

        browser.close()
    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("chord probe: clean")


if __name__ == "__main__":
    main()
