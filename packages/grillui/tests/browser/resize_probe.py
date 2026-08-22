"""Whether the board tracks the height of the window it is in, measured in a browser.

    uv run --with playwright python tests/browser/resize_probe.py <session-dir>

Vertical fit is not a property of the source. A pane pinned to a fixed pixel
height and a pane sized to the viewport read the same at one window size and
differ at every other, so the only way to tell them apart is to change the
window and measure again.

Like the other probes here it is outside `make ci-grillui`, which would have to
carry a browser to run it, and it works on a copy of the session directory it is
pointed at rather than on that directory.
"""

from __future__ import annotations

import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

from grillui.api import create_app
from grillui.log import SessionLog

WIDTH = 1280
SHORT = 700
TALL = 1100
# The panes give up some of the delta to chrome that reflows, so the growth is
# compared against the viewport's with a band rather than for equality. A pane
# with a fixed height grows by zero, which is nowhere near this.
TOLERANCE = 60
NEVER_STARTED = "the backend never started"

MEASURE = """() => {
  const box = (id) => {
    const el = document.getElementById(id);
    return el ? Math.round(el.getBoundingClientRect().height) : null;
  };
  return {column: box('column'), map: box('mapscroll'),
          docHeight: Math.round(document.documentElement.scrollHeight),
          viewport: window.innerHeight};
}"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(directory: Path, port: int) -> uvicorn.Server:
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


def main(source: Path) -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-resize-probe-"))
    directory = scratch / source.name
    shutil.copytree(source, directory)
    port = free_port()
    server = serve(directory, port)

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": WIDTH, "height": SHORT})
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_timeout(1200)
        if page.locator('[data-act="takeover"]').count():
            page.click('[data-act="takeover"]')
            page.wait_for_timeout(800)
        page.wait_for_selector("#column", timeout=10000)
        page.wait_for_timeout(600)

        short = page.evaluate(MEASURE)
        assert short["column"] and short["map"], f"the board did not render: {short}"
        page.set_viewport_size({"width": WIDTH, "height": TALL})
        page.wait_for_timeout(800)
        tall = page.evaluate(MEASURE)

        browser.close()

    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)

    print(f"  at {SHORT}px: {short}")
    print(f"  at {TALL}px: {tall}")
    want = TALL - SHORT
    for pane in ("column", "map"):
        grew = tall[pane] - short[pane]
        assert abs(grew - want) <= TOLERANCE, (
            f"the {pane} pane grew by {grew}px while the viewport grew by {want}px"
        )
    # A pane that tracks the viewport is only half of it: the page itself has to
    # stop growing too, or the board fits the window at the cost of a scrollbar.
    assert tall["docHeight"] <= TALL + TOLERANCE, (
        f"the page is {tall['docHeight']}px tall in a {TALL}px window"
    )
    print("resize probe: clean")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
