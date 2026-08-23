"""The completion offer, measured in a browser.

Five rendered facts live here and nowhere else. Whether settling the last open
decision actually puts an overlay on screen carrying both actions; whether
dismissing it leaves a board that can still be written to, with the control it
was offering visibly marked; whether letting an agent's invalidate land on the
last open decision finishes the board too, in an overlay that says how many
decisions were answered and how many set aside; whether an agent putting an
open node back on the board takes the announcement away and settling that node
brings it back; and what the human is left looking at when the browser refuses
to close the tab.
The source can say which branch builds which string -- it cannot say that a
human saw one, that the board underneath still took a message, or that the tab
survived `window.close()`.

    uv run --with playwright python tests/browser/completion_probe.py

It is deliberately outside `make ci-grillui`: the gate would have to carry a
browser and its binaries, and what this pins is pinned in the suite as the
source invariant and the wire behaviour that produce it.

One session, driven through the whole arc, because the arc is the subject: the
overlay's meaning is a transition, and a transition needs the state before it.
Every stage asserts what the board is before it acts, so a stage that could not
have failed does not pass quietly.
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
from grillui.log import SessionLog
from grillui.persistence import project_and_persist
from grillui.schemas import SESSION_START_KIND

NEVER_STARTED = "the backend never started"
OVERLAY = "#completion"
END = '[data-act="endsession"]'
ASKED = "Which of these do we regret first?"


def decision(node: str, title: str, prereqs: list[str]) -> dict[str, Any]:
    return {
        "id": node,
        "short": node,
        "title": title,
        "prereqs": prereqs,
        "body": f"Settle {node}.",
        "options": [{"id": "a", "text": "The first way"}, {"id": "b", "text": "The other way"}],
    }


def handoff() -> dict[str, Any]:
    return {
        "handoff_version": 1,
        "session": {
            "id": "completion-probe",
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
                decision("d2", "Which retention?", ["d1"]),
            ],
        },
    }


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(directory: Path) -> tuple[uvicorn.Server, str, SessionLog]:
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
            return server, f"http://127.0.0.1:{port}", log
        time.sleep(0.1)
    raise AssertionError(NEVER_STARTED)


def board(base: str) -> dict[str, Any]:
    read: dict[str, Any] = httpx.get(base + "/state").json()["image1"]
    return read


def statuses(base: str) -> dict[str, str]:
    return {one["id"]: one["status"] for one in board(base)["decisions"]}


def agent_adds(base: str, node: str) -> None:
    """One open decision, put on the board by the agent that owns the map.

    An `add-node` is not a proposal -- it overwrites no answer -- so it lands
    the moment it is appended, which is exactly the mid-session arrival the
    announcement has to survive.
    """
    reply = httpx.post(
        base + "/events",
        json={
            "epoch": board(base)["epoch"],
            "events": [
                {
                    "kind": "add-node",
                    "actor": "grill-master",
                    "channel": "map",
                    "idempotency_key": f"probe-{node}",
                    "payload": {
                        "target": node,
                        "short": node,
                        "title": "And what about backups?",
                        "body": f"Settle {node}.",
                        "prereqs": [],
                        "options": [
                            {"id": "a", "text": "Nightly"},
                            {"id": "b", "text": "Never"},
                        ],
                    },
                }
            ],
        },
    )
    assert reply.json()[0]["status"] == "accepted", reply.text


def agent_proposes_invalidate(base: str, node: str) -> str:
    """One killing change, queued against a decision the way an agent's arrives.

    An `invalidate` is never applied by the agent that wrote it -- undermining a
    decision is the human's call -- so this leaves a proposal in the queue and
    the board untouched, which is the state the human's press acts on.
    """
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
                    "payload": {"target": node, "why": "the answer above it killed the question"},
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


def wait_for_board(page: Any, base: str, node: str) -> None:
    """Wait until the page is showing a decision the backend already carries."""
    assert node in statuses(base), f"{node} is not on the board"
    page.wait_for_selector(f"#col-{node}", timeout=10000)
    page.wait_for_timeout(400)


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
    scratch = Path(tempfile.mkdtemp(prefix="grillui-completion-probe-"))
    server, base, log = serve(scratch / "session")

    # Preconditions, before a single click: the board is up, it carries both
    # decisions, and neither is settled -- so nothing below can pass on a board
    # that was finished before the probe touched it.
    assert statuses(base) == {"d1": "open", "d2": "open"}, statuses(base)

    with sync_playwright() as play:
        page = open_board(play, base)
        assert page.locator(OVERLAY).count() == 0, "an unfinished board announced completion"

        # 1. Settling one of two open decisions announces nothing. This is the
        #    non-vacuity precondition for stage 2: the overlay below appears
        #    because the board finished, not because a decision was answered.
        settle(page, base, "d1")
        assert statuses(base) == {"d1": "settled", "d2": "open"}, statuses(base)
        assert page.locator(OVERLAY).count() == 0, "a half-answered board announced completion"
        assert "pulsing" not in (page.locator(END).get_attribute("class") or "")

        # 2. Settling the last open decision presents the overlay, carrying both
        #    actions, over a board that is not sealed.
        settle(page, base, "d2")
        assert statuses(base) == {"d1": "settled", "d2": "settled"}, statuses(base)
        assert page.locator(OVERLAY).count() == 1, "the finished board announced nothing"
        assert page.locator(f"{OVERLAY} {END}").count() == 1, "the overlay offers no ending"
        dismiss = page.locator(f'{OVERLAY} [data-act="dismiss-completion"]')
        assert dismiss.count() == 1, "the overlay offers no way back"
        assert page.locator(f"{OVERLAY} .box").is_visible(), "the overlay is not on screen"

        # 3. Dismissing returns a board that can still be written to, with the
        #    control the overlay was offering marked so it stays findable.
        dismiss.click()
        page.wait_for_timeout(400)
        assert page.locator(OVERLAY).count() == 0, "the overlay stayed up"
        top = page.locator(f".topbar {END}")
        assert "pulsing" in (top.get_attribute("class") or ""), "the control is not pulsing"
        assert top.is_enabled(), "the board is sealed"
        assert not board(base)["threads"], "a thread existed before anything was said"
        page.click('[data-act="toggle"][data-id="d1"]')
        page.wait_for_timeout(300)
        page.click('[data-act="newthread"][data-id="d1"]')
        page.wait_for_timeout(400)
        page.fill(".slide #ft-say", ASKED)
        page.click('.slide [data-act="draftsay"]')
        page.wait_for_timeout(1500)
        threads = board(base)["threads"]
        assert len(threads) == 1, threads
        assert [one["text"] for one in threads[0]["turns"]] == [ASKED], threads[0]
        # Writing into the board did not re-announce a board that never left the
        # finished state: the offer is a transition, not a standing fact.
        assert page.locator(OVERLAY).count() == 0, "the overlay re-fired without a transition"
        page.click('.slide [data-act="closepanel"]')
        page.wait_for_timeout(300)

        # 4. A decision nobody answers can still come to rest: the human applies
        #    the invalidate an agent proposed, and the board is finished by that
        #    press. The offer says which decisions were answered and which were
        #    set aside, and dismissing it pulses the control as it always did.
        agent_adds(base, "d3")
        wait_for_board(page, base, "d3")
        assert statuses(base)["d3"] == "open", statuses(base)
        assert page.locator(OVERLAY).count() == 0, "a reopened board still announced completion"
        queued = agent_proposes_invalidate(base, "d3")
        assert page.locator(OVERLAY).count() == 0, "a queued change finished the board by itself"
        human_applies(page, base, queued, "d3")
        assert statuses(base) == {"d1": "settled", "d2": "settled", "d3": "invalidated"}
        assert page.locator(OVERLAY).count() == 1, (
            "a board whose last question was set aside announced nothing"
        )
        said = page.locator(f"{OVERLAY} .box").inner_text()
        assert "3 decisions: 2 answered, 1 set aside" in said, said
        page.click(f'{OVERLAY} [data-act="dismiss-completion"]')
        page.wait_for_timeout(400)
        assert "pulsing" in (page.locator(f".topbar {END}").get_attribute("class") or ""), (
            "the set-aside board left no pulsing control behind"
        )

        # 5. An agent putting an open decision back on the board takes both the
        #    overlay and the pulse away, and settling it announces again.
        agent_adds(base, "d4")
        wait_for_board(page, base, "d4")
        assert statuses(base)["d4"] == "open", statuses(base)
        assert page.locator(OVERLAY).count() == 0, "a reopened board still announced completion"
        assert "pulsing" not in (page.locator(f".topbar {END}").get_attribute("class") or ""), (
            "the pulse outlived the finished board"
        )
        settle(page, base, "d4")
        assert page.locator(OVERLAY).count() == 1, (
            "re-entering the finished state announced nothing"
        )

        # 6. Ending from the overlay is the ending. The browser refuses to close
        #    a tab it did not open, silently -- so what is measured is that the
        #    tab is still here, and that what is on it says so.
        page.click(f"{OVERLAY} {END}")
        page.wait_for_timeout(1500)
        assert not page.is_closed(), "the tab closed -- the fallback path was never reached"
        assert page.locator(OVERLAY).count() == 0, "the overlay outlived the session"
        shell = page.locator("#shell").inner_text()
        assert "This session has ended." in shell, shell
        assert "close this tab" in shell, shell
        assert not page.locator(f".topbar {END}").is_enabled(), "the ended board is still live"
        ended = [one for one in log.entries() if one.kind == "session-end"]
        assert len(ended) == 1, f"{len(ended)} session-end entries"
        assert (scratch / "session" / "result.json").exists(), "no terminal result was written"

    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("completion probe: clean")


if __name__ == "__main__":
    main()
