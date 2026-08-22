"""The map thread, driven end to end in a browser.

What lives here and nowhere else is the whole route: a human who wants several
decisions changed at once presses a control on the board, says so in plain
words, folds the thread, and finds the changes waiting in their inbox. Every
step of that is a rendered control acting on a running backend -- the source can
say which string reaches which sink, and it cannot say that the fold button is
on screen, enabled, and wired to a gesture the backend answers with a
grill-master turn.

    uv run --with playwright python tests/browser/map_thread_probe.py

It is deliberately outside `make ci-grillui`: the gate would have to carry a
browser and its binaries, and what this pins is pinned in the suite as the
source invariant and the prompt each agent is given.

The tier behind it is a stub rather than a model. What is being measured is the
route, and a real model would make the assertions a judgement about a
completion: the stub replies with the statement a primed agent is asked for on
the thread, and with the invalidates that statement obliges on the map.
"""

from __future__ import annotations

import json
import shutil
import socket
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from playwright.sync_api import sync_playwright

from grillui.api import create_app
from grillui.drivers import record_reply
from grillui.log import SessionLog
from grillui.persistence import project_and_persist
from grillui.schemas import (
    FAST_TIER,
    MAP_CHANNEL,
    SESSION_START_KIND,
    TIER_KEY,
    DispatchContext,
)

NEVER_STARTED = "the backend never started"

# What the human asks for: one answer that kills two other decisions, which is
# the shape no route reached before -- a change on decisions the thread is not
# anchored to.
ASKED = "invalidate d2 and d3 because d1 is b"
# What a primed map-thread agent hands back: the request as decisions and what
# happens to each, written to be acted on by an agent that never saw the thread.
STATED = (
    "d1 is answered b, so d2 and d3 are both moot: each asks how to shape a queue that "
    "answer removes. Invalidate d2 and d3, citing d1's answer."
)
MOOT = ("d2", "d3")


@dataclass
class StubTier:
    """A tier that says what the route needs said, and records what it was given.

    Two turns, told apart by what the dispatch carries rather than by a counter:
    a context routing a thread's conclusion is the grill-master's fold turn, and
    anything else is the thread's own.
    """

    tier: str = FAST_TIER
    conclusions: list[str] = field(default_factory=list)

    def run(self, log: SessionLog, dispatch: Path, /) -> None:
        context = DispatchContext.model_validate_json(dispatch.read_text(encoding="utf-8"))
        if context.conclusion is None:
            record_reply(log, self.tier, context.channel, STATED, {TIER_KEY: self.tier})
            return
        self.conclusions.append(context.conclusion.text)
        record_reply(
            log,
            self.tier,
            MAP_CHANNEL,
            json.dumps(
                {
                    "text": "Both follow from d1. Each waits for you.",
                    "updates": [
                        {"kind": "invalidate", "target": one, "why": "d1 is answered b"}
                        for one in MOOT
                    ],
                }
            ),
            {TIER_KEY: self.tier},
        )

    @staticmethod
    def _primed(_log: SessionLog) -> bool:
        """The mandate rides the composed prompt rather than the recorded
        dispatch, so the dispatch bytes cannot show it. What is asserted here is
        the prompt, which the suite reads directly."""
        return True


def handoff() -> dict[str, Any]:
    return {
        "handoff_version": 1,
        "session": {
            "id": "map-thread-probe",
            "title": "Queue design",
            "created": "2026-08-22T09:00:00+00:00",
            "author": "probe",
        },
        "impetus": "The queue shape is about to be built and nobody has argued against it.",
        "context": "The log is append-only and the page is a renderer.",
        "constraints": ["no new services"],
        "grilling_brief": {
            "posture": "hard on cost and on recovery",
            "stop_when": "every decision is settled or parked with a named blocker",
        },
        "plan": {
            "statement": "Design the work queue.",
            "decisions": [
                {
                    "id": "d1",
                    "short": "Queue",
                    "title": "Is there a queue at all?",
                    "prereqs": [],
                    "body": "Decide whether work is queued.",
                    "options": [
                        {"id": "a", "text": "Queue the work"},
                        {"id": "b", "text": "Run it inline, no queue"},
                    ],
                },
                {
                    "id": "d2",
                    "short": "Ordering",
                    "title": "How is the queue ordered?",
                    "prereqs": [],
                    "body": "Pick the ordering rule.",
                    "options": [{"id": "a", "text": "FIFO"}, {"id": "b", "text": "By priority"}],
                },
                {
                    "id": "d3",
                    "short": "Retries",
                    "title": "How does a queued item retry?",
                    "prereqs": [],
                    "body": "Pick the retry policy.",
                    "options": [{"id": "a", "text": "Backoff"}, {"id": "b", "text": "Never"}],
                },
            ],
        },
    }


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(directory: Path, driver: StubTier) -> tuple[uvicorn.Server, str]:
    directory.mkdir(parents=True, exist_ok=True)
    log = SessionLog(directory)
    log.record(SESSION_START_KIND, handoff())
    project_and_persist(log)
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(log, driver), host="127.0.0.1", port=port, log_level="error")
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


def proposed(read: dict[str, Any]) -> list[dict[str, Any]]:
    """The map changes waiting in the queue, which is not the whole queue: the
    turn's own prose queues beside them as a notice, and counting that as a
    change would pass this probe on a reply that proposed nothing."""
    return [one for one in read["pending"] if one["kind"] == "invalidate"]


def until(base: str, ready: Any, what: str) -> dict[str, Any]:
    """Poll the board until it says what the gesture was supposed to make true.

    A fixed wait either fails on a slow machine or spends the difference on
    every run; the failure message names what never arrived.
    """
    for _ in range(80):
        read = board(base)
        if ready(read):
            return read
        time.sleep(0.25)
    never = f"the board never {what}: {board(base)}"
    raise AssertionError(never)


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-map-thread-probe-"))
    driver = StubTier()
    server, base = serve(scratch / "session", driver)
    assert board(base)["decisions"], "the board came up empty"

    with sync_playwright() as play:
        page = play.chromium.launch(headless=True).new_page(viewport={"width": 1280, "height": 900})
        page.goto(base + "/")
        page.wait_for_timeout(1200)
        if page.locator('[data-act="takeover"]').count():
            page.click('[data-act="takeover"]')
            page.wait_for_timeout(800)
        page.wait_for_selector("#col-d1", timeout=10000)

        # 1. The control is on the board, and pressing it creates nothing: a
        #    thread minted by a click would spend an agent's turn on curiosity.
        control = page.locator('[data-act="mapthread"]')
        assert control.count() == 1, f"{control.count()} map-thread controls"
        assert not board(base)["threads"], "a thread existed before anything was said"
        control.click()
        page.wait_for_timeout(500)
        assert page.locator(".slide.left.pane").count() == 1, "no map-thread pane opened"
        assert not board(base)["threads"], "opening the pane created a thread"

        # 2. Saying the request opens the one map thread, anchored to nothing.
        page.fill(".slide #ft-say", ASKED)
        page.click('.slide [data-act="draftsay"]')
        threads = until(base, lambda read: read["threads"], "opened the thread")["threads"]
        assert len(threads) == 1, threads
        assert threads[0]["id"] == "t-map", threads[0]
        assert threads[0]["decision"] is None, threads[0]
        assert threads[0]["kind"] == "map", threads[0]

        # 3. Its agent answers on the thread, and nothing on the board has
        #    moved: what an agent says is a proposal at most, never a mutation.
        until(
            base,
            lambda read: len(read["threads"][0]["turns"]) == 2,
            "carried the agent's reply",
        )
        assert not board(base)["pending"], "a thread agent changed the board"

        # 4. The fold control is offered and enabled without any declared
        #    impact, which is the one thing the map thread's fold may not wait
        #    for -- its agent authors nothing to declare.
        fold = page.locator('.slide [data-act="fold"]')
        assert fold.count() == 1, f"{fold.count()} fold controls on the map thread"
        assert fold.is_enabled(), "the map thread's fold is disabled"
        fold.click()

        # 5. Folding is a grill-master turn that saw the conclusion, and its
        #    proposals are in the human's queue rather than on the board.
        queued = until(base, lambda read: len(proposed(read)) >= 2, "queued the changes")
        assert [one["target"] for one in proposed(queued)] == list(MOOT), queued["pending"]
        assert driver.conclusions and STATED in driver.conclusions[0], driver.conclusions
        statuses = {one["id"]: one.get("status") for one in queued["decisions"]}
        assert statuses["d2"] != "invalidated", "a proposal moved the board without the human"

        # 6. The board says so where the human is looking.
        page.wait_for_timeout(1200)
        assert "2 changes waiting on you" in page.locator(".pendbtn").inner_text()
        assert board(base)["threads"][0]["state"] == "folded"

    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("map thread probe: clean")


if __name__ == "__main__":
    main()
