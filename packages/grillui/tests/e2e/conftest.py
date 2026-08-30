"""Fixtures and plan builders for the end-to-end scenarios.

Each scenario states the plan it needs rather than sharing one: what a scenario
is about is usually a shape in the board -- an option that pre-marks two
decisions, a chain of prereqs, a decision with nothing resting on it -- and a
shared fixture plan would leave every scenario reading around the parts it did
not want.

One browser for the whole run and one page per scenario. Launching chromium is
the expensive part and it holds no session state; a page does, and a page
carried between scenarios would be looking at a backend that has gone.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from harness import Session, start
from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence
    from pathlib import Path

    from playwright.sync_api import Browser, Page

    from grillui.schemas import LogEntry

# How long the page is given to render what a turn produced. The board polls,
# so this is a bound on the poll rather than on anything a model does.
RENDER = 2000
BOARD_TIMEOUT = 15000


def option(id: str, text: str, puts_in_question: Sequence[str] = ()) -> dict[str, Any]:
    """One answer on offer, and the decisions its author predicts it unsettles."""
    offered: dict[str, Any] = {"id": id, "text": text}
    if puts_in_question:
        offered["puts_in_question"] = list(puts_in_question)
    return offered


def decision(
    id: str,
    title: str = "Which way?",
    *,
    short: str = "",
    prereqs: Sequence[str] = (),
    options: Sequence[Mapping[str, Any]] = (),
    body: str = "Pick one.",
    **extra: Any,
) -> dict[str, Any]:
    """One node of a plan, defaulting to the plainest answerable decision."""
    return {
        "id": id,
        "short": short or id,
        "title": title,
        "prereqs": list(prereqs),
        "body": body,
        "options": [dict(one) for one in options] or [option("a", "Yes"), option("b", "No")],
        **extra,
    }


def handoff(
    decisions: Sequence[Mapping[str, Any]] | None = None, **overrides: Any
) -> dict[str, Any]:
    """A conforming briefing over the decisions a scenario states.

    The five briefing fields are always present because the backend refuses a
    partial one -- and `stop_when` in particular travels with every turn, so a
    scenario that omitted it would be grilling with no termination condition.
    """
    plan = {
        "statement": "Design the session store.",
        "decisions": [dict(one) for one in decisions or [decision("d1")]],
    }
    return {
        "handoff_version": 1,
        "session": {
            "id": "e2e",
            "title": "Session store design",
            "created": "2026-08-18T09:00:00+00:00",
            "author": "e2e",
        },
        "impetus": "The store shape is about to be built and nobody has argued against it.",
        "context": "The log is append-only and the page is a renderer.",
        "constraints": ["no new services"],
        "grilling_brief": {
            "posture": "hard on cost and on recovery",
            "stop_when": "every decision is settled or parked with a named blocker",
        },
        "plan": plan,
        **overrides,
    }


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    """One headless chromium for the whole run."""
    with sync_playwright() as play:
        found = play.chromium.launch(headless=True)
        yield found
        found.close()


@pytest.fixture
def launcher(tmp_path: Path) -> Iterator[Callable[..., Session]]:
    """Open backends, and close every one of them however the scenario ended.

    Closing is what puts the process environment back, so a scenario that
    failed mid-turn must not be able to leave the next one configured by it.
    """
    opened: list[Session] = []

    def open_session(name: str = "session", **kwargs: Any) -> Session:
        session = start(tmp_path / name, **kwargs)
        opened.append(session)
        return session

    yield open_session
    for session in reversed(opened):
        session.close()
        session.stub.close()


@pytest.fixture
def board(browser: Browser) -> Iterator[Callable[[Session], Page]]:
    """Open the board in a page, and assert it got there before anything is clicked.

    A second window is refused with a rendered explanation, so the take-over is
    pressed where one is offered -- a scenario is the only driver of its own
    session, and a claim left with a page that has gone would leave every
    gesture refused for a reason that is not what the scenario is about.
    """
    pages: list[Page] = []

    def open_board(session: Session) -> Page:
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        pages.append(page)
        page.goto(session.url)
        page.wait_for_timeout(RENDER)
        if page.locator('[data-act="takeover"]').count():
            page.click('[data-act="takeover"]')
            page.wait_for_timeout(RENDER)
        first = session.board()["decisions"][0]["id"]
        page.wait_for_selector(f"#col-{first}", timeout=BOARD_TIMEOUT)
        return page

    yield open_board
    for page in pages:
        page.close()


def document(
    text: str = "Noted.",
    updates: Sequence[Mapping[str, Any]] = (),
    supersedes: Sequence[str] = (),
    rulings: Sequence[Mapping[str, Any]] = (),
    stop: Mapping[str, Any] | None = None,
    **broken: Any,
) -> str:
    """One grill-master map document, defaulting to the turn that proposes
    nothing and rules on nothing.

    Every field is loosely typed and `broken` takes any extra key, because a
    good half of what the scenarios script is documents that are wrong on
    purpose: a builder that only produced valid ones could not state the
    invalid case at all.
    """
    body: dict[str, Any] = {
        "text": text,
        "updates": [dict(one) for one in updates],
        "supersedes": list(supersedes),
        "rulings": [dict(one) for one in rulings],
        "stop": {"met": False, "why": ""} if stop is None else dict(stop),
        **broken,
    }
    return json.dumps(body)


def ruling(decision: str, verdict: str, why: str = "because the answer moved it") -> dict[str, str]:
    return {"decision": decision, "ruling": verdict, "why": why}


def turn(reply: str, **extra: Any) -> dict[str, Any]:
    """One scripted turn for a shim: what it says, and how it says it."""
    return {"reply": reply, **extra}


def agent_turns(entries: Sequence[LogEntry], channel: str = "map") -> list[LogEntry]:
    """The entries an agent authored on one channel, in log order."""
    return [
        entry
        for entry in entries
        if entry.channel == channel and entry.actor in {"grill-master", "thread-agent"}
    ]


def lane(entries: Sequence[LogEntry], channel: str) -> list[tuple[str, str | None]]:
    """One channel's status lane: each phase, and the tier it named."""
    return [
        (str(entry.payload.get("phase")), entry.payload.get("tier"))
        for entry in entries
        if entry.kind == "status" and entry.channel == channel
    ]


def notices(entries: Sequence[LogEntry]) -> list[str]:
    """Every informational the backend or an agent put on the map, as text."""
    said = []
    for entry in entries:
        if entry.channel != "map":
            continue
        if entry.kind == "informational":
            said.append(str(entry.payload.get("text", "")))
        for update in entry.payload.get("updates", []) or []:
            if isinstance(update, dict) and update.get("kind") == "informational":
                said.append(str(update.get("text", "")))
    return said
