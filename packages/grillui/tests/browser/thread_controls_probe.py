"""What a thread pane offers before anything has been said in it, measured in a browser.

    uv run --with playwright python tests/browser/thread_controls_probe.py

The moment a human most wants to choose who they are asking is before they ask.
A thread pane reached from a decision exists in two states that look alike and
render differently: one whose thread the agent already opened, and a draft whose
thread nothing has created yet because the first thing said is what opens it.
Only the first carried the tier control, so the control the human reaches for
first arrived one turn after the turn it was wanted for.

Presence is asserted against the viewport rather than against the markup,
because a row rendered below the fold of the panel and a row never rendered are
the same thing to the human and different things in the source. The pane's foot
is pinned, so a control inside it is on screen -- and that is a claim about
layout, which only a layout engine can settle.

The last case is what keeps the control from being decoration: the draft's
channel is not the name the thread gets, so a transfer pressed on a draft has to
be carried onto the minted thread or the first turn goes out on the fast tier
with the human having paid for the expert.

It seeds its own session: the shape it needs is a board with one decision and one
agent-opened thread, which is a property of the fixture rather than of any
session on disk. Like the other probes here it is outside `make ci-grillui`,
which would have to carry a browser to run it.
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
from grillui.escalation import in_expert_mode
from grillui.log import SessionLog
from grillui.persistence import project_and_persist
from grillui.schemas import MAP_CHANNEL, SESSION_START_KIND

# Short enough that a control row overflowing the pane's foot would fall off it.
VIEWPORT = {"width": 1280, "height": 600}
DECISION = "d1"
AGENT_THREAD = "t-agent"
FIRST_TURN = "Say what an append guarantees before I answer this."
NEVER_STARTED = "the backend never started"

HANDOFF = {
    "handoff_version": 1,
    "session": {
        "id": "thread-controls-probe",
        "title": "Session store design",
        "created": "2026-08-18T09:00:00+00:00",
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
                "options": [{"id": "a", "text": "Append-only log"}, {"id": "b", "text": "Table"}],
            }
        ],
    },
}

# The tier control and the row it sits in, measured against the window that is
# showing them. `within` is the whole claim: rendered, laid out, and on screen.
MEASURE = """() => {
  const btn = document.querySelector('.threadpane [data-act="transfer"]');
  const r = btn ? btn.getBoundingClientRect() : null;
  return {
    present: !!btn,
    label: btn ? btn.innerText.trim() : null,
    channel: btn ? btn.dataset.channel : null,
    rows: document.querySelectorAll('.threadpane .thread-actions').length,
    vh: window.innerHeight,
    vw: window.innerWidth,
    box: r ? {top: Math.round(r.top), bottom: Math.round(r.bottom),
              left: Math.round(r.left), right: Math.round(r.right)} : null,
    within: !!r && r.top >= 0 && r.left >= 0
      && r.bottom <= window.innerHeight && r.right <= window.innerWidth
      && r.height > 0 && r.width > 0,
  };
}"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def post(base: str, kind: str, channel: str, actor: str, payload: dict) -> None:
    """One event, through the door the backend opens to an agent."""
    epoch = httpx.get(base + "/status").json()["epoch"]
    receipt = httpx.post(
        base + "/events",
        json={
            "epoch": epoch,
            "events": [
                {
                    "kind": kind,
                    "actor": actor,
                    "channel": channel,
                    "idempotency_key": f"probe-{kind}-{time.time_ns()}",
                    "payload": payload,
                }
            ],
        },
    ).json()[0]
    assert receipt["status"] == "accepted", receipt


def serve(log: SessionLog, port: int) -> uvicorn.Server:
    """A backend on loopback, and nothing the launch path does around it."""
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


def open_board(page, base: str) -> None:
    page.goto(base + "/")
    page.wait_for_timeout(1200)
    if page.locator('[data-act="takeover"]').count():
        page.click('[data-act="takeover"]')
        page.wait_for_timeout(800)
    page.wait_for_selector(f"#col-{DECISION}", timeout=10000)


def expand(page, selector: str) -> None:
    """Reach a control that lives inside the decision's own block."""
    if not page.locator(selector).count():
        page.click(f"#col-{DECISION} .head")
        page.wait_for_timeout(400)
    assert page.locator(selector).count(), f"the board offers no {selector}"


def created_thread(log: SessionLog) -> str:
    """The channel the page's own first turn opened."""
    opened = [
        entry
        for entry in log.entries()
        if entry.kind == "thread-created" and entry.actor == "human"
    ]
    assert opened, "the page's first turn opened no thread"
    return opened[-1].channel


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-thread-controls-probe-"))
    port = free_port()
    log = SessionLog(scratch / "session")
    server = serve(log, port)
    base = f"http://127.0.0.1:{port}"
    # A thread the agent opened and the human has not yet spoken in: the state
    # the draft is compared against, and the one that already worked.
    post(
        base,
        "thread-created",
        AGENT_THREAD,
        "grill-master",
        {
            "decision": DECISION,
            "kind": "question",
            "requires_action": True,
            "title": "What an accepted write promises",
            "turns": [{"who": "grill-master", "text": "Say what an append guarantees. " * 12}],
        },
    )

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport=VIEWPORT)
        open_board(page, base)

        # 1. The thread the agent opened, with no human turn in it.
        expand(page, f'[data-act="openthread"][data-tid="{AGENT_THREAD}"]')
        page.locator(f'[data-act="openthread"][data-tid="{AGENT_THREAD}"]').first.click()
        page.wait_for_timeout(600)
        agent_thread = page.evaluate(MEASURE)
        print(f"  agent-opened thread: {agent_thread}")
        assert agent_thread["within"], (
            f"the tier control is off screen on an agent-opened thread: {agent_thread}"
        )

        # 2. The draft, which is the same pane before the thread exists.
        page.click('[data-act="closepanel"]')
        page.wait_for_timeout(300)
        expand(page, f'[data-act="newthread"][data-id="{DECISION}"]')
        page.locator(f'[data-act="newthread"][data-id="{DECISION}"]').first.click()
        page.wait_for_timeout(500)
        draft = page.evaluate(MEASURE)
        print(f"  draft thread: {draft}")
        assert draft["present"], f"a draft thread offers no tier control at all: {draft}"
        assert draft["within"], f"the tier control is off screen on a draft: {draft}"
        assert draft["channel"] == f"draft:{DECISION}", (
            f"the control names a channel the draft is not on: {draft}"
        )
        assert draft["label"] == "⚡ Transfer to expert", draft

        # 3. The popped-out draft is the same pane in its own window, and the
        #    control has to be on screen there too -- a window sized to its own
        #    content is exactly where a foot rendered below the fold would hide.
        with page.expect_popup() as popped:
            page.click('[data-act="popout"]')
        window = popped.value
        window.wait_for_timeout(900)
        pop = window.evaluate(MEASURE)
        print(f"  popped-out draft: {pop}")
        assert pop["present"], f"the popped draft offers no tier control: {pop}"
        assert pop["within"], f"the tier control is off screen in the popped window: {pop}"
        window.close()
        page.wait_for_timeout(300)

        # 4. What the control is for. Pressed on a draft it has to reach the
        #    thread the first turn opens, whose name the draft never had.
        expand(page, f'[data-act="newthread"][data-id="{DECISION}"]')
        page.locator(f'[data-act="newthread"][data-id="{DECISION}"]').first.click()
        page.wait_for_timeout(400)
        page.click('.threadpane [data-act="transfer"]')
        page.wait_for_timeout(300)
        flipped = page.evaluate(MEASURE)
        assert flipped["label"] == "⚡ Return to fast agent", (
            f"the press did not move the draft's channel: {flipped}"
        )
        page.fill("#ft-say", FIRST_TURN)
        page.click('.threadpane [data-act="draftsay"]')
        page.wait_for_timeout(1500)

        opened = created_thread(log)
        print(f"  the first turn opened {opened}")
        assert opened != f"draft:{DECISION}", "the thread kept the draft's own name"
        assert in_expert_mode(log.entries(), opened), (
            "the transfer pressed on the draft did not reach the thread it opened"
        )
        assert not in_expert_mode(log.entries(), MAP_CHANNEL), (
            "a thread's transfer moved the map channel as well"
        )

        browser.close()
    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("thread controls probe: clean")


if __name__ == "__main__":
    main()
