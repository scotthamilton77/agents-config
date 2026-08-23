"""The board's next-open control, measured in a browser.

Three rendered facts live here and nowhere else. Whether pressing the control
actually walks the focus along the frontier in the frontier's own order and
wraps back to its head; whether the decision column scrolls far enough that the
decision it landed on is on screen; and whether a board with nothing answerable
left says which kind of nothing it is -- a board that is finished, or a board
whose remaining decisions are all waiting on something that will never settle.
The source can say which branch builds which string. It cannot say that the
column moved, because only a layout engine knows where a decision sits, and it
cannot say that a human was told two different things in the two cases.

    uv run --with playwright python tests/browser/next_open_probe.py

It is deliberately outside `make ci-grillui`: the gate would have to carry a
browser and its binaries, and what this pins is pinned in the suite as the
source invariant that produces it.

One session, driven through the whole arc, because the arc is the subject: the
stalled board and the finished board are the same board at two moments, and a
control that told them apart on a board seeded into each state separately would
not have been asked the question this exists to answer. Every stage asserts what
the board is before it acts, so a stage that could not have failed does not pass
quietly -- including the walk, which asserts the column was not already showing
what it scrolled to.
"""

from __future__ import annotations

import shutil
import socket
import sys
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
CONTROL = '[data-act="nextopen"]'
WHY = ".nextwhy"
# Long enough that four of them cannot share one 600px-tall column, which is
# what makes the walk have to scroll rather than merely re-colour a border.
BODY = " ".join(["Argue it out; nothing here is obvious and the cost lands later."] * 6)

FOCUSED = """() => {
  const it = document.querySelector('#column .item.focused');
  const col = document.getElementById('column');
  if (!it || !col) return null;
  const cr = col.getBoundingClientRect(), ir = it.getBoundingClientRect();
  return {id: it.id.replace('col-', ''), scrollTop: Math.round(col.scrollTop),
          inView: ir.top >= cr.top - 2 && ir.top < cr.bottom};
}"""

IN_VIEW = """(id) => {
  const it = document.getElementById('col-' + id);
  const col = document.getElementById('column');
  const cr = col.getBoundingClientRect(), ir = it.getBoundingClientRect();
  return ir.top >= cr.top - 2 && ir.top < cr.bottom;
}"""


def decision(node: str, title: str, prereqs: list[str]) -> dict[str, Any]:
    return {
        "id": node,
        "short": node,
        "title": title,
        "prereqs": prereqs,
        "body": f"{BODY} Settle {node}.",
        "options": [{"id": "a", "text": "The first way"}, {"id": "b", "text": "The other way"}],
    }


def handoff() -> dict[str, Any]:
    """Three decisions nothing rests on, and a fourth resting on the first.

    The fourth is the whole of the stalled case: once the first is invalidated
    rather than settled, its prerequisite is never satisfied and it can never
    reach the frontier, so a board can run out of answerable decisions while
    still carrying one nobody has closed.
    """
    return {
        "handoff_version": 1,
        "session": {
            "id": "next-open-probe",
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
                decision("d1", "Which storage?", []),
                decision("d2", "Which retention?", []),
                decision("d3", "Which encoding?", []),
                decision("d4", "Which migration?", ["d1"]),
            ],
        },
    }


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(directory: Path) -> tuple[uvicorn.Server, str]:
    """A backend on loopback, and nothing the launch path does around it."""
    directory.mkdir(parents=True, exist_ok=True)
    log = SessionLog(directory)
    log.record(SESSION_START_KIND, handoff())
    project_and_persist(log)
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(log), host="127.0.0.1", port=port, log_level="error")
    )
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server, f"http://127.0.0.1:{port}"
        time.sleep(0.1)
    raise AssertionError(NEVER_STARTED)


def board(base: str) -> dict[str, Any]:
    read: dict[str, Any] = httpx.get(base + "/state").json()["image1"]
    return read


def statuses(base: str) -> dict[str, str]:
    return {one["id"]: one["status"] for one in board(base)["decisions"]}


def frontier(base: str) -> list[str]:
    ids: list[str] = board(base)["frontier"]
    return ids


def agent_proposes_invalidate(base: str, node: str) -> str:
    """One killing change, queued against a decision the way an agent's arrives."""
    reply = httpx.post(
        base + "/events",
        json={
            "epoch": board(base)["epoch"],
            "events": [
                {
                    "kind": "invalidate",
                    "actor": "grill-master",
                    "channel": "map",
                    "idempotency_key": f"kill-{node}",
                    "payload": {"target": node, "why": "the question died with the plan above it"},
                }
            ],
        },
    )
    assert reply.json()[0]["status"] == "accepted", reply.text
    waiting = [one for one in board(base)["pending"] if not one["superseded"]]
    assert len(waiting) == 1, waiting
    queued: str = waiting[0]["id"]
    return queued


def human_applies(page: Any, base: str, queued: str, node: str) -> None:
    """The human letting a queued change land, from the inbox they open."""
    page.click(".pendbtn")
    page.wait_for_timeout(400)
    page.click(f'.slide [data-act="applyone"][data-uid="{queued}"]')
    for _ in range(50):
        if statuses(base).get(node) == "invalidated":
            page.wait_for_timeout(600)
            return
        page.wait_for_timeout(200)
    assert statuses(base).get(node) == "invalidated", f"{node} never went invalidated"


def settle(page: Any, base: str, node: str) -> None:
    """Answer one decision the way a human does, and wait for the board to say so."""
    page.click(f'[data-act="pick"][data-id="{node}"][data-opt="a"]')
    for _ in range(50):
        if statuses(base).get(node) == "settled":
            page.wait_for_timeout(400)
            return
        page.wait_for_timeout(200)
    assert statuses(base).get(node) == "settled", f"{node} never settled"


def focused(page: Any) -> dict[str, Any]:
    state: dict[str, Any] | None = page.evaluate(FOCUSED)
    assert state is not None, "nothing on the board is focused"
    return state


def open_board(play: Any, base: str) -> Any:
    page = play.chromium.launch(headless=True).new_page(viewport={"width": 1280, "height": 600})
    page.goto(base + "/")
    page.wait_for_timeout(1200)
    if page.locator('[data-act="takeover"]').count():
        page.click('[data-act="takeover"]')
        page.wait_for_timeout(800)
    page.wait_for_selector("#col-d1", timeout=10000)
    return page


def walk(page: Any, expected: str) -> bool:
    """One press, and what the column did about it.

    Returns whether the column had to scroll to obey -- the walk's whole claim
    is that the decision it lands on is on screen, and a press that changed no
    scroll position proves nothing about a board that fits in the window.
    """
    was_showing = page.evaluate(IN_VIEW, expected)
    before = focused(page)["scrollTop"]
    page.click(CONTROL)
    page.wait_for_timeout(400)
    now = focused(page)
    assert now["id"] == expected, f"the walk landed on {now['id']}, not {expected}"
    assert now["inView"], f"{expected} took the focus off screen"
    scrolled = now["scrollTop"] != before
    assert scrolled or was_showing, f"{expected} was off screen and the column never moved"
    return scrolled


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-next-open-probe-"))
    server, base = serve(scratch / "session")

    # Preconditions, before a single press: three decisions are answerable, in
    # the order the walk below claims, and the fourth is not -- so the walk is
    # being asked to follow an order rather than to visit everything.
    assert frontier(base) == ["d1", "d2", "d3"], frontier(base)
    assert statuses(base)["d4"] == "open", statuses(base)

    with sync_playwright() as play:
        page = open_board(play, base)
        control = page.locator(CONTROL)
        assert control.count() == 1, "the board's heading carries no next-open control"
        assert control.is_enabled(), "an answerable board offers a dead control"
        assert page.locator(WHY).count() == 0, "a live control is explaining itself"
        assert focused(page)["id"] == "d1", focused(page)

        # 1. The walk is the frontier's order, it wraps at the end, and the
        #    column scrolls at least once to obey.
        moved = walk(page, "d2")
        moved = walk(page, "d3") or moved
        moved = walk(page, "d1") or moved
        assert moved, "no press ever scrolled the column -- the board fitted in the window"

        # 2. A board that has run out of answerable decisions while still
        #    carrying an open one says it is waiting, not that it is finished.
        #    d1 is invalidated rather than settled, so d4's prerequisite is
        #    never met and d4 can never reach the frontier.
        human_applies(page, base, agent_proposes_invalidate(base, "d1"), "d1")
        settle(page, base, "d2")
        settle(page, base, "d3")
        assert frontier(base) == [], frontier(base)
        assert statuses(base)["d4"] == "open", statuses(base)
        assert page.locator("#completion").count() == 0, "an unfinished board announced completion"
        assert not control.is_enabled(), "a board with nothing answerable offers a live control"
        stalled = page.locator(WHY)
        assert stalled.is_visible(), "the dead control gives no reason anyone can read"
        stalled_text = (stalled.inner_text() or "").strip()
        assert "waiting" in stalled_text.lower(), stalled_text

        # 3. Closing the last open decision leaves the same dead control saying
        #    something else. Same control, same board, different answer -- which
        #    is the whole of what it is for.
        human_applies(page, base, agent_proposes_invalidate(base, "d4"), "d4")
        assert page.locator("#completion").count() == 1, "the finished board announced nothing"
        page.click('#completion [data-act="dismiss-completion"]')
        page.wait_for_timeout(400)
        assert not control.is_enabled(), "a finished board offers a live control"
        finished = page.locator(WHY)
        assert finished.is_visible(), "the finished board's control gives no reason"
        finished_text = (finished.inner_text() or "").strip()
        assert "waiting" not in finished_text.lower(), finished_text
        assert finished_text != stalled_text, "a finished board reads the same as a stalled one"

    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("next-open probe: PASS")


if __name__ == "__main__":
    sys.exit(main())
