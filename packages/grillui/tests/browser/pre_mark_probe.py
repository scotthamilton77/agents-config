"""What the option in hand marks, measured in a browser.

An option may name the decisions it is expected to put in question downstream.
While the human has that option in hand the named decisions wear a provisional
mark, on the map and on their own blocks -- and the mark is the page's alone: it
crosses no wire, appends nothing, and a reload with nothing in hand comes back
to a board without it.

None of that is a question the source can answer. Which of several sources holds
an option -- a pointer that has not moved, a caret that just did, an option
armed some turns ago -- is settled by real pointer and focus events in a real
document, and whether one mark is told apart from another is a stylesheet's
answer rather than a class list's.

    uv run --with playwright python tests/browser/pre_mark_probe.py

It is deliberately outside `make ci-grillui`: the gate would have to carry a
browser and its binaries. It seeds and then drives its own session, because the
board it needs carries one of each state the mark could be confused with -- a
decision with a change waiting on it, and a stale one -- alongside the two
decisions an option names and a third it does not. Every one of those is
asserted off the board before anything is hovered, so a fixture that could not
have failed does not pass quietly.
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

# What the first option of `d1` says it would put in question, and what its
# second option says. The second names nothing that exists: an id resolving to
# no node has to mark nothing and raise nothing, and a fixture carrying only
# resolvable ids would pass whichever way that went.
NAMED = ["d4", "d5"]
NOWHERE = ["no-such-decision"]
# On the board and never named by any option: what "marks no third" is measured
# against.
UNNAMED = "d6"

PLAIN = [{"id": "a", "text": "One way of answering it"}, {"id": "b", "text": "Another way"}]


def decision(node_id: str, short: str, prereqs: list[str], options: list[dict]) -> dict:
    return {
        "id": node_id,
        "short": short,
        "title": f"{short}?",
        "prereqs": prereqs,
        "body": f"The question behind {short}.",
        "options": options,
    }


HANDOFF = {
    "handoff_version": 1,
    "session": {
        "id": "pre-mark-probe",
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
            decision(
                "d1",
                "Store",
                [],
                [
                    {"id": "a", "text": "Append-only log", "puts_in_question": NAMED},
                    {"id": "b", "text": "Mutable table", "puts_in_question": NOWHERE},
                ],
            ),
            decision("d2", "Retention", [], PLAIN),
            decision("d4", "Backups", [], PLAIN),
            decision("d5", "Migration", [], PLAIN),
            decision(UNNAMED, "Naming", [], PLAIN),
            decision("db", "Format", [], PLAIN),
            decision("ds", "Encoding", ["db"], PLAIN),
        ],
    },
}


class SilentDriver:
    """No agent at all. Every entry in this session is one the probe wrote, so
    nothing arrives between a gesture and the assertion about it."""

    tier = "fast"

    def run(self, _log: SessionLog, _dispatch: Path, /) -> None:
        return None


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
        uvicorn.Config(
            create_app(log, SilentDriver()), host="127.0.0.1", port=port, log_level="error"
        )
    )
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.1)
    raise AssertionError(NEVER_STARTED)


def entry(kind: str, key: str, actor: str = "grill-master", **payload) -> dict:
    return {
        "kind": kind,
        "actor": actor,
        "channel": "map",
        "idempotency_key": key,
        "payload": payload,
    }


def post(base: str, *events: dict) -> None:
    """One batch, every receipt accepted -- a refused entry would take the state
    this probe is measuring out of the board silently."""
    epoch = httpx.get(base + "/status").json()["epoch"]
    receipts = httpx.post(base + "/events", json={"epoch": epoch, "events": list(events)}).json()
    for receipt in receipts:
        assert receipt["status"] == "accepted", receipt


def board(base: str) -> dict:
    payload: dict = httpx.get(base + "/state").json()["image1"]
    return payload


def stage_the_board(base: str) -> None:
    """Put one of each state the mark could be read as onto the board.

    `d2` takes a change nobody has applied, which locks it. `ds` is made stale
    the only way a decision becomes stale -- by the answer it rested on being
    withdrawn -- and `db` is then answered again, so what is left is a stale
    decision rather than one merely waiting on an open prereq.
    """
    post(base, entry("settle", "s-db", target="db", answer={"option": "a"}, why="the format"))
    post(base, entry("settle", "s-ds", target="ds", answer={"option": "a"}, why="the encoding"))
    post(base, entry("unsettle", "u-db", target="db", why="the format was never settled"))
    waiting = [item["id"] for item in board(base)["pending"] if item["kind"] == "unsettle"]
    assert len(waiting) == 1, f"the unsettle did not queue: {board(base)['pending']}"
    post(base, entry("apply", "ap-db", actor="human", pending=waiting))
    post(base, entry("settle", "s-db2", target="db", answer={"option": "b"}, why="settled again"))
    post(base, entry("invalidate", "inv-d2", target="d2", why="retention is premature"))

    now = board(base)
    status = {node["id"]: node["status"] for node in now["decisions"]}
    assert status["ds"] == "stale", f"the fixture has no stale decision: {status}"
    assert [(one["kind"], one["target"]) for one in now["pending"]] == [("invalidate", "d2")], (
        f"the fixture has no change waiting on d2: {now['pending']}"
    )
    marks = {
        option["id"]: option.get("puts_in_question") for option in now["decisions"][0]["options"]
    }
    assert marks == {"a": NAMED, "b": NOWHERE}, f"d1 does not carry the pre-marks: {marks}"
    assert UNNAMED in now["frontier"], "the unnamed control is not answerable"
    assert {"d4", "d5"} <= set(now["frontier"]), "a named decision is not answerable to begin with"


def marked(page) -> tuple[list[str], list[str]]:
    """Which decisions wear the mark, on the map and on their own blocks."""
    return (
        sorted(page.eval_on_selector_all(".mnode.premark", "els => els.map(e => e.dataset.id)")),
        sorted(page.eval_on_selector_all(".item.premark", "els => els.map(e => e.dataset.id)")),
    )


def classes(page, selector: str) -> list[str]:
    found = page.eval_on_selector_all(selector, "els => els.map(e => e.className)")
    assert len(found) == 1, f"{selector} matched {len(found)} elements"
    return str(found[0]).split()


def option(node_id: str, label: str) -> str:
    return f'#col-{node_id} [data-act="pick"][data-opt="{label}"]'


def mnode(node_id: str) -> str:
    return f'.mnode[data-id="{node_id}"]'


def away(page) -> None:
    """Off every option control, with nothing focused."""
    page.mouse.move(3, 3)
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    page.wait_for_timeout(250)


def bubbles(page):
    """The toast stack, with its clock paused under the pointer so counting it
    is not a race against the seconds a toast lives."""
    stack = page.locator("#bubbles")
    if stack.count():
        box = stack.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    return page.locator("#bubbles .bubble")


def unread(page) -> int:
    return int(page.locator('[data-act="notifications"]').get_attribute("data-unread"))


def wait_for(page, predicate, what: str, limit: float = 6.0) -> None:
    deadline = time.time() + limit
    while time.time() < deadline:
        if predicate():
            return
        page.wait_for_timeout(200)
    raise AssertionError(what)


def open_page(play, base: str):
    page = play.new_page(viewport={"width": 1400, "height": 950})
    page.goto(base + "/")
    page.wait_for_timeout(1200)
    if page.locator('[data-act="takeover"]').count():
        page.click('[data-act="takeover"]')
        page.wait_for_timeout(800)
    page.wait_for_selector("#col-d1", timeout=10000)
    return page


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-pre-mark-probe-"))
    directory = scratch / "session"
    directory.mkdir(parents=True)
    port = free_port()
    server = serve(directory, port)
    base = f"http://127.0.0.1:{port}"
    stage_the_board(base)

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = open_page(browser, base)

        # 1. Nothing in hand, nothing marked. Without this every check below
        #    would pass on a page that marked everything all the time.
        away(page)
        assert marked(page) == ([], []), f"a board with nothing in hand is marked: {marked(page)}"
        quiet = (bubbles(page).count(), unread(page))

        # 2. Holding the option that names two decisions marks exactly those
        #    two, on the map and on their own blocks, and marks no third.
        page.hover(option("d1", "a"))
        page.wait_for_timeout(250)
        assert marked(page) == (NAMED, NAMED), (
            f"the named pair is not what is marked: {marked(page)}"
        )

        # 3. The mark is told apart from the two states it could be read as: a
        #    change waiting on a decision, and a decision already undermined.
        #    Neither of those decisions is marked, and the marked ones are
        #    neither of those -- so the three never render as the same thing.
        assert "pendlocked" in classes(page, mnode("d2")), "the fixture's locked node lost its lock"
        assert "premark" not in classes(page, mnode("d2"))
        stale = classes(page, mnode("ds"))
        assert any(name.startswith("stale") for name in stale), f"ds is not drawn stale: {stale}"
        assert "premark" not in stale
        for named in NAMED:
            worn = classes(page, mnode(named))
            assert "premark" in worn, f"{named} is not marked: {worn}"
            assert "pendlocked" not in worn, f"{named} reads as a waiting change: {worn}"
            assert not any(name.startswith("stale") for name in worn), (
                f"{named} reads stale: {worn}"
            )

        # 4. A decision wearing only the mark is on the frontier and answers as
        #    it did. The mark is a warning about a choice, not a hold.
        assert page.locator(option("d4", "a")).is_enabled(), "a marked decision stopped answering"
        assert {"d4", "d5"} <= set(board(base)["frontier"]), "a marked decision left the frontier"

        # 5. Nothing was raised for the human. The mark arrives before an answer
        #    and is gone after one; a notification would outlive both.
        assert (bubbles(page).count(), unread(page)) == quiet, "the mark raised a notification"

        # 6. An id naming no node marks nothing at all, and raises nothing.
        away(page)
        page.hover(option("d1", "b"))
        page.wait_for_timeout(250)
        assert marked(page) == ([], []), f"an id naming no node marked something: {marked(page)}"

        # 7. The sources rank. The caret on one option, then the pointer onto
        #    another: the pointer's option is in hand and its marks replace,
        #    rather than union with, the ones the caret's option had.
        away(page)
        page.locator(option("d1", "b")).focus()
        page.wait_for_timeout(200)
        page.hover(option("d1", "a"))
        page.wait_for_timeout(250)
        assert marked(page) == (NAMED, NAMED), (
            f"the higher source did not take over: {marked(page)}"
        )

        # 8. And a lower source arriving under a held pointer changes nothing:
        #    the caret moves to the option naming nothing, the pointer has not
        #    moved, and the pointer's marks stand.
        page.locator(option("d1", "b")).focus()
        page.wait_for_timeout(250)
        assert marked(page) == (NAMED, NAMED), f"a lower source took the hand: {marked(page)}"

        # 9. Leaving nothing in hand clears them.
        away(page)
        assert marked(page) == ([], []), f"the marks outlived the hand: {marked(page)}"

        # 10. A caret on an option is a hand the page keeps across a render. Any
        #     entry arriving redraws the whole board, which replaces every
        #     control on it including the one the human is standing on -- so the
        #     control is taken back, and the marks it raises stand. The pointer
        #     is nowhere near the board here, so the caret is the only source
        #     holding anything.
        away(page)
        page.locator(option("d1", "a")).focus()
        page.wait_for_timeout(250)
        assert marked(page) == (NAMED, NAMED), "the caret alone did not take the option"
        before = unread(page)
        post(base, entry("informational", "note-1", target=UNNAMED, text="A note on naming."))
        wait_for(page, lambda: unread(page) > before, "the arriving entry never redrew the board")
        page.wait_for_timeout(250)
        held = page.evaluate(
            "() => [document.activeElement.dataset.id, document.activeElement.dataset.opt]"
        )
        assert held == ["d1", "a"], f"the render took the caret off the option: {held}"
        assert marked(page) == (NAMED, NAMED), f"the render dropped the marks: {marked(page)}"

        # 11. And a reload taken while an option is in hand comes back to a
        #     board without them: the mark is page state and is in nothing the
        #     next page reads.
        page.hover(option("d1", "a"))
        page.wait_for_timeout(250)
        assert marked(page) == (NAMED, NAMED)
        page.reload()
        page.wait_for_timeout(1200)
        page.wait_for_selector("#col-d1", timeout=10000)
        assert marked(page) == ([], []), f"a reload came back marked: {marked(page)}"

        # 12. A marked decision really does still answer -- pressed while it is
        #     marked, it settles like any other.
        page.hover(option("d1", "a"))
        page.wait_for_timeout(250)
        assert "premark" in classes(page, mnode("d4"))
        page.click(option("d4", "a"))
        wait_for(
            page,
            lambda: {n["id"]: n["status"] for n in board(base)["decisions"]}["d4"] == "settled",
            "a marked decision did not settle when it was answered",
        )

        # 13. The answer landing clears the marks. After an answer the board
        #     says what the board says: the named decisions are not invalidated,
        #     and nothing is marked by an option nobody is holding any more.
        away(page)
        page.hover(option("d1", "a"))
        page.wait_for_timeout(250)
        assert marked(page)[0], "nothing was marked going into the answer"
        page.click(option("d1", "a"))
        wait_for(
            page,
            lambda: {n["id"]: n["status"] for n in board(base)["decisions"]}["d1"] == "settled",
            "the answer never landed",
        )
        page.wait_for_timeout(400)
        assert marked(page) == ([], []), f"the marks survived the answer: {marked(page)}"
        after = {node["id"]: node["status"] for node in board(base)["decisions"]}
        assert after["d5"] == "open", f"a pre-marked decision was moved by the answer: {after}"

        browser.close()
    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("pre-mark probe: clean")


if __name__ == "__main__":
    main()
