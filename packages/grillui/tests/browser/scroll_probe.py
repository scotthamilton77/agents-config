"""What the page does to scroll position, measured in a browser.

Three symptoms of one defect are measured here, and they are measured rather
than inspected because scroll position is not a property of the source: only a
layout engine knows whether taking the caret moved the page.

    uv run --with playwright python tests/browser/scroll_probe.py <session-dir>

It is deliberately outside `make ci-grillui`: the gate would have to carry a
browser and its binaries to run it, and what it pins is pinned in the suite as
the source invariant that produces it. Run it by hand against a copy of a real
session directory -- never against one a backend is serving, since it appends to
the log it is pointed at.

The session it is pointed at must have at least one open decision whose block is
taller than the decision column, because that is the shape all three symptoms
need: the caret lands on a box that cannot be revealed without scrolling
something. The probe asserts that precondition rather than passing quietly on a
board that could not have failed.
"""

from __future__ import annotations

import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from playwright.sync_api import sync_playwright

from grillui.api import create_app
from grillui.log import SessionLog

VIEWPORT = {"width": 1280, "height": 600}
# How far below the column's top edge a decision's header may sit once its map
# node is clicked. Zero is the ideal; the anchor leaves a small pad.
HEADER_BAND = 40
NEVER_STARTED = "the backend never started"

MEASURE = """(id) => {
  const col = document.getElementById('column');
  const it = document.getElementById('col-' + id);
  const cr = col.getBoundingClientRect(), ir = it.getBoundingClientRect();
  const hd = it.querySelector('.head').getBoundingClientRect();
  return {headTopRel: Math.round(hd.top - cr.top), itemHeight: Math.round(ir.height),
          colHeight: Math.round(cr.height), windowScrollY: Math.round(window.scrollY)};
}"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(directory: Path, port: int) -> uvicorn.Server:
    """A backend on loopback, and nothing the launch path does around it."""
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(SessionLog(directory)), host="127.0.0.1", port=port, log_level="error"
        )
    )
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.1)
    raise AssertionError(NEVER_STARTED)


def notify(base: str, target: str) -> None:
    """One agent message, arriving while the human is reading something else."""
    status = httpx.get(base + "/status").json()
    posted = httpx.post(
        base + "/events",
        json={
            "epoch": status["epoch"],
            "events": [
                {
                    "kind": "informational",
                    "actor": "grill-master",
                    "channel": "map",
                    "idempotency_key": f"probe-{time.time()}",
                    "payload": {"text": "A message arriving now.", "target": target},
                }
            ],
        },
    )
    receipt = posted.json()[0]
    assert receipt["status"] == "accepted", receipt


def main(source: Path) -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-scroll-probe-"))
    directory = scratch / source.name
    shutil.copytree(source, directory)
    port = free_port()
    server = serve(directory, port)
    base = f"http://127.0.0.1:{port}"
    frontier = httpx.get(base + "/state").json()["image1"]["frontier"]
    assert frontier, "the session has no open decision, so no caret is ever taken"

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport=VIEWPORT)
        page.goto(base + "/")
        page.wait_for_timeout(1200)
        if page.locator('[data-act="takeover"]').count():
            page.click('[data-act="takeover"]')
            page.wait_for_timeout(800)
        page.wait_for_selector(f"#col-{frontier[0]}", timeout=10000)
        page.wait_for_timeout(1200)

        shapes = {one: page.evaluate(MEASURE, one) for one in frontier}
        tall = [one for one, shape in shapes.items() if shape["itemHeight"] > shape["colHeight"]]
        assert tall, f"no open decision is taller than the column: {shapes}"

        # 1. The outbox chip opens the channel drop-down. Nothing about that is
        #    a reason to move the page out from under the thing it just opened.
        page.click(f'.mnode[data-id="{tall[0]}"]')
        page.wait_for_timeout(500)
        page.evaluate("window.scrollTo(0, 0); document.activeElement.blur();")
        page.wait_for_timeout(200)
        assert "outbox" in page.inner_text('[data-signal="outbox"]')
        page.click("#indicator")
        page.wait_for_timeout(500)
        assert page.locator("#diagnostic").count() == 1, "the drop-down did not open"
        moved = page.evaluate("window.scrollY")
        assert moved == 0, f"clicking the outbox chip scrolled the page to {moved}"
        page.click("#indicator")
        page.wait_for_timeout(400)

        # 2. A message arriving is not a reason to move what the human is
        #    reading. Whatever the log was scrolled to is where it stays.
        page.evaluate(
            "document.activeElement.blur(); document.getElementById('column').scrollTop = 350;"
        )
        page.wait_for_timeout(200)
        held = page.evaluate("document.getElementById('column').scrollTop")
        notify(base, frontier[0])
        page.wait_for_timeout(2500)
        after = page.evaluate("document.getElementById('column').scrollTop")
        assert after == held, f"a notification moved the log from {held} to {after}"

        # 3. Clicking a node lands its decision at the top of the log, header
        #    first -- a decision taller than the column included.
        for one in frontier:
            page.evaluate("window.scrollTo(0, 0)")
            page.click(f'.mnode[data-id="{frontier[-1] if one != frontier[-1] else frontier[0]}"]')
            page.wait_for_timeout(400)
            page.click(f'.mnode[data-id="{one}"]')
            page.wait_for_timeout(600)
            shape = page.evaluate(MEASURE, one)
            # The window's own position is reported and not asserted on: a click
            # on a map node low in the map is a click on a button, and bringing
            # a clicked button into view is the browser's, not this page's.
            assert 0 <= shape["headTopRel"] <= HEADER_BAND, f"{one} anchored at {shape}"
            print(f"  {one}: {shape}")

        browser.close()
    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("scroll probe: clean")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
