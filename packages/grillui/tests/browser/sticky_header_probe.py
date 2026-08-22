"""Whether a decision keeps its name in view, measured in a browser.

A decision whose option list runs several screens below the question it answers
leaves the human picking an answer with nothing on the page saying which
question they are answering. The fix is that the block's own header stays at the
top of the pane while any part of the block is in view -- and none of that is a
question the source can answer. Whether a header is where the pane's top edge
is, whether it lets go when the decision leaves, and whether it sits over the
first option when the block is read from its top are a layout engine's answers.

    uv run --with playwright python tests/browser/sticky_header_probe.py

It is deliberately outside `make ci-grillui`: the gate would have to carry a
browser and its binaries. It seeds its own session, because the shape it needs
is specific -- one decision several times taller than the pane, with decisions
after it to scroll into -- and it proves that decision is taller than the pane
before asserting anything about scrolling it, so a board that could not have
failed does not pass quietly.
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

VIEWPORT = {"width": 1280, "height": 700}
NEVER_STARTED = "the backend never started"
TALL = "d1"
TALL_TITLE = "Which shape does the session store take?"
# How far off the pane's top edge a pinned header may sit. It is a tolerance for
# sub-pixel layout, not a band: a header that is merely near the top is a header
# the human has to hunt for.
PINNED_BAND = 2

# Long enough that the block runs several panes deep, so scrolling to its
# options leaves its header far above the top edge rather than just past it.
BODY = (
    "The store is the one thing every other decision here reads from, so the "
    "shape it takes is the shape of the session. It has to survive a restart, "
    "it has to be readable by a human with nothing but a text editor, and it "
    "has to be cheap enough to write on every gesture. "
) * 8
OPTIONS = [
    {
        "id": chr(ord("a") + n),
        "text": f"Option {chr(ord('a') + n)}: " + ("a way of holding the session that costs " * 6),
    }
    for n in range(9)
]

FILLER = [
    {
        "id": f"f{n}",
        "short": f"Filler {n}",
        "title": f"Filler question {n}?",
        "prereqs": [],
        "body": "A question that is here so there is board below the tall one. " * 3,
        "options": [
            {"id": "a", "text": f"One way of answering filler {n}"},
            {"id": "b", "text": f"Another way of answering filler {n}"},
        ],
    }
    for n in range(1, 5)
]

HANDOFF = {
    "handoff_version": 1,
    "session": {
        "id": "sticky-header-probe",
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
                "id": TALL,
                "short": "Store",
                "title": TALL_TITLE,
                "prereqs": [],
                "body": BODY,
                "options": OPTIONS,
            },
            *FILLER,
        ],
    },
}

# Where the header is relative to the pane, and where the block is. Everything
# asserted below is a difference between two boxes the engine laid out.
MEASURE = """(id) => {
  const col = document.getElementById('column');
  const it = document.getElementById('col-' + id);
  const cr = col.getBoundingClientRect(), ir = it.getBoundingClientRect();
  const hd = it.querySelector('.head');
  const hr = hd.getBoundingClientRect();
  const opt = it.querySelector('[data-act="pick"]');
  return {
    headTopRel: Math.round(hr.top - cr.top),
    headBottomRel: Math.round(hr.bottom - cr.top),
    itemTopRel: Math.round(ir.top - cr.top),
    itemBottomRel: Math.round(ir.bottom - cr.top),
    itemHeight: Math.round(ir.height),
    paneHeight: Math.round(cr.height),
    firstOptionTopRel: opt ? Math.round(opt.getBoundingClientRect().top - cr.top) : null,
    headText: hd.innerText.trim(),
    heads: it.querySelectorAll('.head').length,
    collapsed: it.classList.contains('collapsed'),
    scrollTop: Math.round(col.scrollTop),
  };
}"""


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


def scroll_to(page, top: int):
    """Put the pane at an absolute offset and let the layout settle."""
    page.evaluate("(top) => { document.getElementById('column').scrollTop = top; }", top)
    page.wait_for_timeout(250)
    return page.evaluate(MEASURE, TALL)


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-sticky-header-probe-"))
    directory = scratch / "session"
    directory.mkdir(parents=True)
    port = free_port()
    server = serve(directory, port)
    base = f"http://127.0.0.1:{port}"

    board = httpx.get(base + "/state").json()["image1"]
    assert next(d["id"] for d in board["decisions"]) == TALL, board["decisions"]

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport=VIEWPORT)
        page.goto(base + "/")
        page.wait_for_timeout(1200)
        if page.locator('[data-act="takeover"]').count():
            page.click('[data-act="takeover"]')
            page.wait_for_timeout(800)
        page.wait_for_selector(f"#col-{TALL}", timeout=10000)
        page.wait_for_timeout(600)

        # 0. The precondition. Every assertion below is about a block that does
        #    not fit the pane, so a block that fits is not a passing board.
        shape = scroll_to(page, 0)
        assert shape["itemHeight"] > shape["paneHeight"] * 1.5, (
            f"the seeded decision is not taller than the pane: {shape} -- "
            "nothing below this proves anything"
        )
        assert shape["heads"] == 1, f"the block renders {shape['heads']} headers, not one"

        # 1. Read from the top, the header is in the flow above the first
        #    option: nothing pinned is covering what the human is reading, and
        #    there is no second copy of the header to cover it with.
        assert shape["itemTopRel"] <= shape["headTopRel"], (
            f"the header sits above its own block: {shape}"
        )
        assert shape["firstOptionTopRel"] is not None, "the block renders no options"
        assert shape["headBottomRel"] <= shape["firstOptionTopRel"], (
            f"the header overlaps the first option at the block's top: {shape}"
        )

        # 2. Scrolled a pane deep into the block -- where the header's own place
        #    in the flow is well above the top edge -- the id and title are at
        #    the pane's top edge anyway.
        deep = shape["paneHeight"]
        held = scroll_to(page, deep)
        assert held["itemTopRel"] < -PINNED_BAND, (
            f"the block's top is still in view at scrollTop={deep}: {held}"
        )
        assert held["itemBottomRel"] > held["paneHeight"], f"the block already ended: {held}"
        assert abs(held["headTopRel"]) <= PINNED_BAND, (
            f"the header is not at the pane's top edge: {held}"
        )
        assert TALL in held["headText"] and TALL_TITLE in held["headText"], (
            f"the pinned header does not carry the id and title: {held['headText']!r}"
        )
        # And it is still pinned two panes deeper, not merely lagging.
        deeper = scroll_to(page, deep * 2)
        assert deeper["itemBottomRel"] > deeper["paneHeight"], f"the block ended: {deeper}"
        assert abs(deeper["headTopRel"]) <= PINNED_BAND, f"the header let go early: {deeper}"

        # 3. Scrolled past the block entirely, the header goes with it. The
        #    decision below is the one now naming the pane.
        past = scroll_to(page, shape["itemHeight"] + 40)
        assert past["itemBottomRel"] <= 0, f"the block is still in view: {past}"
        assert past["headBottomRel"] <= 0, (
            f"the header outlived its decision at the pane's top: {past}"
        )
        below = page.evaluate(MEASURE, "f1")
        assert abs(below["headTopRel"]) <= PINNED_BAND, (
            f"the next decision did not take the top edge: {below}"
        )

        # 4. Settled and collapsed, it releases: a decision with nothing under
        #    its header to read has no reason to hold the pane's top edge.
        scroll_to(page, 0)
        page.click(f'#col-{TALL} [data-act="pick"]')
        page.wait_for_timeout(2500)
        settled = page.evaluate(MEASURE, TALL)
        assert settled["collapsed"], f"answering did not collapse the block: {settled}"
        assert settled["itemHeight"] < settled["paneHeight"], f"the block is still tall: {settled}"
        # Push its top above the edge with the block still partly in view: a
        # header that pinned would sit at 0, and this one goes with its block.
        offset = page.evaluate("(id) => document.getElementById('col-' + id).offsetTop", TALL)
        moved = scroll_to(page, offset + max(6, settled["itemHeight"] // 2))
        assert moved["itemTopRel"] < -PINNED_BAND, f"the block's top is still in view: {moved}"
        assert moved["itemBottomRel"] > 0, f"the block left the pane entirely: {moved}"
        assert moved["headTopRel"] < -PINNED_BAND, (
            f"a settled, collapsed decision is still pinning its header: {moved}"
        )

        browser.close()
    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("sticky header probe: clean")


if __name__ == "__main__":
    main()
