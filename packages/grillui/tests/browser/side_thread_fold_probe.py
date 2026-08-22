"""A side thread's fold control, driven end to end in a browser.

    uv run --with playwright python tests/browser/side_thread_fold_probe.py

The fold is the only route a side thread's conclusion has to the map, and it is
a control that spends the whole session either enabled or greyed out. Whether it
opens is not something the source can settle: the gate reads the board, the board
is what the backend projected out of the log, and what the human is left looking
at is a rendered button. This drives the whole route -- a human opens a thread on
a decision, the fold is shut while their own turn is the last thing in it, the
agent answers, the fold opens quoting what would cross, and pressing it reaches
the grill-master with that turn as the thread's conclusion.

Like the other probes here it is outside `make ci-grillui`, which would have to
carry a browser to run it; the source invariant behind the gate is pinned in the
suite.

The tier is a stub rather than a model, for the same reason as elsewhere: what is
measured is the route. It holds its thread reply until the probe has looked at
the shut control, so the one state that is gone in a blink is not a race.
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
DECISION = "d1"
MOOT = "d2"
# What the human opens the thread with, and what the thread agent concludes --
# the turn that is handed over when the fold is pressed.
ASKED = "does an append-only log cost us the ability to correct a mistake?"
STATED = (
    "It does not: a correction is another entry, and the projection reads the later one. "
    "The cost is storage, which nothing here is short of. Answer d1 with the log."
)


@dataclass
class StubTier:
    """A tier that says what the route needs said, and records what it was given.

    The thread reply waits on `release`, so the probe can look at a fold control
    that has nothing to hand over yet before the reply that arms it lands. The
    two turns are told apart by what the dispatch carries: a context routing a
    thread's conclusion is the grill-master's fold turn.
    """

    tier: str = FAST_TIER
    release: threading.Event = field(default_factory=threading.Event)
    conclusions: list[str] = field(default_factory=list)

    def run(self, log: SessionLog, dispatch: Path, /) -> None:
        context = DispatchContext.model_validate_json(dispatch.read_text(encoding="utf-8"))
        if context.conclusion is None:
            assert self.release.wait(60), "the probe never released the thread's reply"
            record_reply(log, self.tier, context.channel, STATED, {TIER_KEY: self.tier})
            return
        self.conclusions.append(context.conclusion.text)
        record_reply(
            log,
            self.tier,
            MAP_CHANNEL,
            json.dumps(
                {
                    "text": "That settles what d2 was waiting on. It waits for you.",
                    "updates": [
                        {"kind": "invalidate", "target": MOOT, "why": "corrections are entries"}
                    ],
                }
            ),
            {TIER_KEY: self.tier},
        )


def handoff() -> dict[str, Any]:
    return {
        "handoff_version": 1,
        "session": {
            "id": "side-thread-fold-probe",
            "title": "Session store design",
            "created": "2026-08-22T09:00:00+00:00",
            "author": "probe",
        },
        "impetus": "The store shape is about to be built and nobody has argued against it.",
        "context": "The log is append-only and the page is a renderer.",
        "constraints": ["no new services"],
        "grilling_brief": {"posture": "hard on recovery", "stop_when": "every decision is settled"},
        "plan": {
            "statement": "Design the session store.",
            "decisions": [
                {
                    "id": DECISION,
                    "short": "Store",
                    "title": "Which storage?",
                    "prereqs": [],
                    "body": "Pick the storage layer.",
                    "options": [
                        {"id": "a", "text": "Append-only log"},
                        {"id": "b", "text": "Table of rows"},
                    ],
                },
                {
                    "id": MOOT,
                    "short": "Edits",
                    "title": "How is a stored record corrected?",
                    "prereqs": [],
                    "body": "Pick the correction path.",
                    "options": [{"id": "a", "text": "In place"}, {"id": "b", "text": "By append"}],
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


def until(base: str, ready: Any, what: str) -> dict[str, Any]:
    """Poll the board until it says what the gesture was supposed to make true."""
    for _ in range(120):
        read = board(base)
        if ready(read):
            return read
        time.sleep(0.25)
    never = f"the board never {what}: {board(base)}"
    raise AssertionError(never)


def fold_control(page: Any) -> Any:
    control = page.locator('.slide [data-act="fold"]')
    assert control.count() == 1, f"{control.count()} fold controls on the thread"
    return control


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-side-thread-fold-probe-"))
    driver = StubTier()
    server, base = serve(scratch / "session", driver)
    assert board(base)["decisions"], "the board came up empty"

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(base + "/")
        page.wait_for_timeout(1200)
        if page.locator('[data-act="takeover"]').count():
            page.click('[data-act="takeover"]')
            page.wait_for_timeout(800)
        page.wait_for_selector(f"#col-{DECISION}", timeout=10000)

        # 1. The human opens a thread on the decision by saying something in it.
        opener = f'[data-act="newthread"][data-id="{DECISION}"]'
        if not page.locator(opener).count():
            page.click(f"#col-{DECISION} .head")
            page.wait_for_timeout(400)
        page.locator(opener).first.click()
        page.wait_for_timeout(500)
        page.fill(".slide #ft-say", ASKED)
        page.click('.slide [data-act="draftsay"]')
        threads = until(base, lambda read: read["threads"], "opened the thread")["threads"]
        assert threads[0]["decision"] == DECISION, threads[0]
        page.wait_for_timeout(1200)

        # 2. With the human's own turn the last thing said, there is nothing to
        #    hand over, and the control says so rather than pretending.
        assert len(board(base)["threads"][0]["turns"]) == 1, "the reply arrived early"
        shut = fold_control(page)
        assert shut.is_disabled(), "the fold offers to hand back the human's own words"
        assert "has not answered yet" in page.locator(".slide .thread-actions").inner_text()

        # 3. The agent answers, and that turn is what arms the control.
        driver.release.set()
        until(
            base,
            lambda read: len(read["threads"][0]["turns"]) == 2,
            "carried the agent's reply",
        )
        page.wait_for_timeout(1500)
        armed = fold_control(page)
        assert armed.is_enabled(), "the agent answered and the fold stayed shut"
        preview = page.locator(".slide details.foldimpact")
        assert preview.count() == 1, "the fold offers no preview of what would cross"
        preview.click()
        page.wait_for_timeout(200)
        assert STATED in preview.inner_text(), (
            f"the preview does not quote the turn that would cross: {preview.inner_text()}"
        )

        # 4. Folding reaches the grill-master with that turn as the conclusion,
        #    and what it makes of it waits in the human's queue.
        armed.click()
        queued = until(
            base,
            lambda read: any(one["kind"] == "invalidate" for one in read["pending"]),
            "queued the grill-master's change",
        )
        assert driver.conclusions == [STATED], driver.conclusions
        assert board(base)["threads"][0]["state"] == "folded", queued["threads"]

        browser.close()
    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("side thread fold probe: clean")


if __name__ == "__main__":
    main()
