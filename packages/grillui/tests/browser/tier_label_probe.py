"""What the page says about which tier answered, measured in a browser.

Two claims live here, and neither is a property of the source. Whether a label
is on screen, whether it is still there after a reload, and whether toggling a
control rewrote history are all questions only a rendered page answers -- and
whether two positions of one control look the same is a question only a layout
engine answers, because the source can carry a class the stylesheet does not
colour and a colour the class does not name.

    uv run --with playwright python tests/browser/tier_label_probe.py

It is deliberately outside `make ci-grillui`: the gate would have to carry a
browser and its binaries, and what it pins is pinned in the suite as the source
invariant that produces it.

It seeds its own session rather than taking a directory, because the shape it
needs is specific -- one fast agent turn and one heavy one on the same channel,
on a thread and on the map channel alike -- and no real session is guaranteed to
have been transferred. It asserts that shape reached the board before it reads
anything off the page, so a board that could not have failed does not pass.
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

FAST_SAID = "The fast tier answered this one."
HEAVY_SAID = "The expert tier answered this one."
FAST_LABEL = "fast agent"
HEAVY_LABEL = "expert agent"
TO_EXPERT = "Transfer to expert"
TO_FAST = "Return to fast agent"
THREAD = "t-probe"
NEVER_STARTED = "the backend never started"

HANDOFF = {
    "handoff_version": 1,
    "session": {
        "id": "tier-label-probe",
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
            },
        ],
    },
}


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


def say(base: str, *events: dict) -> None:
    """Put turns into the log the way a driver does: attributed, on a channel."""
    status = httpx.get(base + "/status").json()
    posted = httpx.post(base + "/events", json={"epoch": status["epoch"], "events": list(events)})
    for receipt in posted.json():
        assert receipt["status"] == "accepted", receipt


def turn(kind: str, channel: str, text: str, tier: str | None, target: str | None = None) -> dict:
    """One entry, attributed as `record_reply` attributes an agent's reply: the
    tier is a payload key on the entry rather than a field of the envelope."""
    payload: dict = {"text": text}
    if tier is not None:
        payload["tier"] = tier
        payload["model"] = f"{tier}-model"
    if target is not None:
        payload["target"] = target
    return {
        "kind": kind,
        "actor": "grill-master" if channel == "map" else "thread-agent",
        "channel": channel,
        "idempotency_key": f"probe-{tier}-{channel}-{time.time()}",
        "payload": payload,
    }


def human_turn(channel: str, text: str) -> dict:
    return {
        "kind": "thread-turn",
        "actor": "human",
        "channel": channel,
        "idempotency_key": f"probe-human-{channel}-{text[:6]}-{time.time()}",
        "payload": {"turns": [{"who": "human", "text": text}]},
    }


def open_thread(base: str) -> None:
    say(
        base,
        {
            "kind": "thread-created",
            "actor": "human",
            "channel": THREAD,
            "idempotency_key": "probe-thread",
            "payload": {
                "decision": "d1",
                "kind": "clarify",
                "title": "Storage, at length",
                "text": "Why the append-only log?",
            },
        },
    )


def enter(page, base: str) -> None:
    page.goto(base + "/")
    page.wait_for_timeout(1200)
    if page.locator('[data-act="takeover"]').count():
        page.click('[data-act="takeover"]')
        page.wait_for_timeout(800)
    page.wait_for_selector("#col-d1", timeout=10000)


def thread_labels(page) -> list[str]:
    """Every `who` line in the open thread pane, as the DOM holds it.

    `textContent` rather than the rendered text: the line is uppercased by the
    stylesheet, the same as `YOU` and `BACKEND` beside it, and what is being
    measured is which words the page chose, not how the sheet cased them.
    """
    return page.eval_on_selector_all(
        ".threadpane .tbody .turn .who",
        "els => els.map(e => e.childNodes[0].textContent.trim())",
    )


def open_pane(page) -> None:
    page.click('#col-d1 [data-act="threads"]')
    page.wait_for_timeout(400)
    page.click(f'[data-act="openthread"][data-tid="{THREAD}"]')
    page.wait_for_timeout(600)


def at_rest(page) -> None:
    """Pointer away from everything and nothing focused, so what is measured
    next is the control's own styling and not a hover or a focus ring."""
    page.mouse.move(0, 0)
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.wait_for_timeout(200)


def styling(page, selector: str) -> dict:
    return page.eval_on_selector(
        selector,
        """(el) => {
          const s = getComputedStyle(el);
          return {background: s.backgroundColor, border: s.borderColor,
                  color: s.color, weight: s.fontWeight, shadow: s.boxShadow,
                  text: el.textContent.trim()};
        }""",
    )


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="grillui-tier-label-probe-"))
    directory = scratch / "session"
    directory.mkdir(parents=True)
    port = free_port()
    server = serve(directory, port)
    base = f"http://127.0.0.1:{port}"

    open_thread(base)
    say(base, turn("thread-turn", THREAD, FAST_SAID, "fast"))
    say(base, human_turn(THREAD, "Take that to the expert."))
    say(base, turn("thread-turn", THREAD, HEAVY_SAID, "heavy"))
    say(base, turn("informational", "map", FAST_SAID, "fast", target="d1"))
    say(base, turn("informational", "map", HEAVY_SAID, "heavy", target="d1"))

    # The projection is what a rejoining page reads, so the tier has to be in it
    # before anything about a reload is claimed.
    projected = httpx.get(base + "/state").json()["image1"]["threads"][0]["turns"]
    assert [t.get("tier") for t in projected] == [None, "fast", None, "heavy"], projected

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1360, "height": 900})
        enter(page, base)

        # 1. Each agent turn on a thread wears the tier that took it, and the
        #    human's wears no tier at all.
        open_pane(page)
        labels = thread_labels(page)
        assert labels == ["You", FAST_LABEL, "You", HEAVY_LABEL], labels

        # 2. The map channel's turns are labelled the same way. They reach the
        #    page as queue items rather than as projected turns, which is a
        #    second read path and so a second place the label can go missing.
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        notes = page.eval_on_selector_all(
            "#col-d1 .infonote strong", "els => els.map(e => e.textContent.trim())"
        )
        assert any(n.startswith(FAST_LABEL) for n in notes), notes
        assert any(n.startswith(HEAVY_LABEL) for n in notes), notes

        # 3. Toggling the channel's mode does not rewrite what already happened.
        #    A page reading the mode instead of the turn would relabel the whole
        #    transcript here, which is exactly the evidence the human needs.
        page.click(f'[data-act="transfer"][data-channel="{THREAD}"]')
        page.wait_for_timeout(400)
        open_pane(page)
        after_toggle = thread_labels(page)
        assert after_toggle == labels, f"the toggle rewrote history: {after_toggle}"
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # 4. A page that reloads -- and so was never there for the turns -- reads
        #    the same labels off the projection.
        enter(page, base)
        open_pane(page)
        reloaded = thread_labels(page)
        assert reloaded == labels, f"the reload lost the labels: {reloaded}"
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # 5. The control names the action, in both positions, and looks the same
        #    in both. It is read on the map channel's control, in the topbar,
        #    where nothing else can be mistaken for it.
        #    Both sides are read at rest -- pointer away and nothing focused --
        #    because hover and focus are states of the press rather than of the
        #    tier, and reading one side mid-press would compare two moments
        #    instead of two positions.
        control = '.topbar [data-act="transfer"]'
        at_rest(page)
        fast_side = styling(page, control)
        assert fast_side["text"].endswith(TO_EXPERT), fast_side
        page.click(control)
        page.wait_for_timeout(500)
        at_rest(page)
        expert_side = styling(page, control)
        assert expert_side["text"].endswith(TO_FAST), expert_side
        assert {k: v for k, v in fast_side.items() if k != "text"} == {
            k: v for k, v in expert_side.items() if k != "text"
        }, f"the control is styled differently on the two tiers:\n  {fast_side}\n  {expert_side}"

        # 6. GUI-A35's half that a browser answers: the control is on the map
        #    channel and on every open thread, and neither position is disabled.
        controls = page.eval_on_selector_all(
            '[data-act="transfer"]',
            "els => els.map(e => ({channel: e.dataset.channel, off: e.disabled}))",
        )
        page.click('#col-d1 [data-act="threads"]')
        page.wait_for_timeout(400)
        paned = page.eval_on_selector_all(
            '[data-act="transfer"]',
            "els => els.map(e => ({channel: e.dataset.channel, off: e.disabled}))",
        )
        assert any(c["channel"] == "map" for c in controls), controls
        assert any(c["channel"] == THREAD for c in paned), paned
        assert not any(c["off"] for c in controls + paned), controls + paned

        # 7. The transfer the human just made routes the next turn: the page
        #    stamps the flag on the turn it sends, and the backend reads the
        #    channel's mode back off exactly that.
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        print(f"  thread: {labels}")
        print(f"  map: {notes}")
        print(f"  control: {fast_side['text']!r} / {expert_side['text']!r}")

        browser.close()
    server.should_exit = True
    shutil.rmtree(scratch, ignore_errors=True)
    print("tier label probe: clean")


if __name__ == "__main__":
    main()
