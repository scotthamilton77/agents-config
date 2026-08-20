"""The status lane's budget and ordering, and who is owed a reply.

Every timing claim below is measured from the log's own timestamps rather than
from a wall clock the test holds. The budget is a property of the lane's place
in the append -- inside the same lock, before the driver is touched -- and a test
that timed its own HTTP round trip would be measuring the test client instead,
passing or failing on load rather than on the thing under test.

The drivers here are stubs on purpose. What is being pinned is that the lane is
written before a tier is reached and regardless of whether one answers, so a
driver that blocks forever and a driver that cannot be reached at all are the
two cases worth standing up.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import event, seed_node
from fastapi.testclient import TestClient

from grillui.api import create_app
from grillui.dispatch import DISPATCH_DIR
from grillui.lane import UnreachableDriver
from grillui.log import SessionLog
from grillui.schemas import (
    STATUS_KIND,
    STATUS_PHASE_ACCEPTED,
    STATUS_PHASE_COMPOSING,
    STATUS_PHASE_ERROR,
    LogEntry,
)

BUDGET_MS = 10.0
TIMEOUT = 5.0
THREAD = "t1"


@dataclass
class SpyDriver:
    """A tier that records what the log already said when it was handed a turn.

    `hold` keeps the turn in flight until the test releases it, which is how a
    slow model is stood in for without one.
    """

    tier: str = "fast"
    hold: bool = False
    seen: list[LogEntry] = field(default_factory=list)
    dispatches: list[Path] = field(default_factory=list)
    started: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)

    def run(self, log: SessionLog, dispatch: Path, /) -> None:
        self.seen = log.entries()
        self.dispatches.append(dispatch)
        self.started.set()
        if self.hold:
            self.release.wait(TIMEOUT)
        self.finished.set()


def driven(log: SessionLog, driver: Any) -> TestClient:
    return TestClient(create_app(log, driver))


def statuses(log: SessionLog, phase: str | None = None) -> list[LogEntry]:
    """The lane's entries, in log order."""
    return [
        entry
        for entry in log.entries()
        if entry.kind == STATUS_KIND and phase in (None, entry.payload.get("phase"))
    ]


def phases(entries: list[LogEntry]) -> list[Any]:
    return [entry.payload.get("phase") for entry in entries]


def elapsed_ms(first: LogEntry, last: LogEntry) -> float:
    """The window between two entries, as the log itself recorded it."""
    delta = datetime.fromisoformat(last.timestamp) - datetime.fromisoformat(first.timestamp)
    return delta.total_seconds() * 1000


def await_phase(log: SessionLog, phase: str) -> LogEntry:
    """Wait for a phase the lane emits from a turn's own thread.

    Only the waiting is done on a wall clock; what the wait is for is asserted
    against the log's timestamps, so a slow poll cannot make a late entry look
    punctual.
    """
    deadline = time.monotonic() + TIMEOUT
    found: list[LogEntry] = []
    while not found and time.monotonic() < deadline:
        found = statuses(log, phase)
        time.sleep(0.001)
    assert found, f"no {phase!r} status entry appeared within {TIMEOUT}s"
    return found[0]


@pytest.fixture
def driver() -> SpyDriver:
    return SpyDriver()


def test_the_lane_reads_accepted_then_composing_naming_the_dispatching_tier(
    log: SessionLog, driver: SpyDriver
) -> None:
    """
    Given a session whose tier is a driver that answers
    When a human answers a decision
    Then the lane carries exactly `accepted` then `composing`, the composing
         entry names the tier taking the turn, and both are backend-authored on
         the human's own channel.

    The tier travels in the entry rather than being looked up by whoever renders
    it: a page that had to infer which tier it was waiting on would infer it from
    configuration the turn may not have used.
    """
    client = driven(log, driver)
    node = seed_node(client, log.epoch)

    _post_answer(client, log.epoch, node)

    lane = statuses(log)
    assert phases(lane) == [STATUS_PHASE_ACCEPTED, STATUS_PHASE_COMPOSING]
    assert lane[1].payload["tier"] == driver.tier
    assert "tier" not in lane[0].payload
    assert [entry.actor for entry in lane] == ["backend", "backend"]
    assert [entry.channel for entry in lane] == ["map", "map"]


def test_the_lane_lands_inside_ten_milliseconds_of_the_human_turn(log: SessionLog) -> None:
    """
    Given a tier whose turn never finishes
    When a human answers a decision
    Then both lane entries are appended within 10 ms of the human's own entry,
         measured from the log's timestamps.

    The driver is held in flight for the whole test, so the budget is met while
    a model would still be composing. That is the claim: the lane's cost is an
    append, not a turn, and no code path here can be made to wait on one.
    """
    driver = SpyDriver(hold=True)
    client = driven(log, driver)
    node = seed_node(client, log.epoch)

    _post_answer(client, log.epoch, node)

    turn, accepted, composing = log.entries()[-3:]
    assert turn.actor == "human"
    assert elapsed_ms(turn, accepted) < BUDGET_MS
    assert elapsed_ms(turn, composing) < BUDGET_MS
    assert not driver.finished.is_set()
    driver.release.set()


def test_the_lane_entries_land_before_the_driver_is_invoked(
    log: SessionLog, driver: SpyDriver
) -> None:
    """
    Given a driver that snapshots the log the moment it is handed a turn
    When a human answers a decision
    Then both lane entries are already in that snapshot.

    Ordering, not timing. A lane that raced the driver could still pass a budget
    on a fast machine while the page showed nothing until the model replied on a
    slow one.
    """
    client = driven(log, driver)
    node = seed_node(client, log.epoch)

    _post_answer(client, log.epoch, node)

    assert driver.started.wait(TIMEOUT)
    at_invocation = [
        entry.payload.get("phase") for entry in driver.seen if entry.kind == STATUS_KIND
    ]
    assert at_invocation == [STATUS_PHASE_ACCEPTED, STATUS_PHASE_COMPOSING]


def test_an_unreachable_agent_still_produces_accepted_and_error_entries_in_the_window(
    log: SessionLog,
) -> None:
    """
    Given a tier that cannot be reached at all
    When a human answers a decision
    Then the lane carries accepted, composing and error, all within 10 ms of the
         human's entry.

    An unreachable agent is the case the lane exists for. Without it the human
    waits on a reply that is never coming, with nothing on the page to
    distinguish that from a model taking its time.
    """
    client = driven(log, UnreachableDriver())
    node = seed_node(client, log.epoch)

    _post_answer(client, log.epoch, node)

    error = await_phase(log, STATUS_PHASE_ERROR)
    lane = statuses(log)
    assert phases(lane) == [STATUS_PHASE_ACCEPTED, STATUS_PHASE_COMPOSING, STATUS_PHASE_ERROR]
    turn = next(entry for entry in log.entries() if entry.actor == "human")
    assert elapsed_ms(turn, lane[0]) < BUDGET_MS
    assert elapsed_ms(turn, error) < BUDGET_MS
    assert "unreachable" in error.payload["detail"]


def test_an_agent_authored_thread_produces_no_status_entry_and_no_dispatch(
    log: SessionLog, driver: SpyDriver, session_dir: Path
) -> None:
    """
    Given a mandate thread whose only turn is the agent's
    When it is accepted
    Then it is recorded and left alone: no lane entry, and no dispatch.

    Only a human turn is owed a reply. A backend that answered its own agent's
    opening turn would talk to itself indefinitely, and every turn of it would
    look to the page exactly like a turn someone asked for.
    """
    client = driven(log, driver)
    receipts = client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [
                event(
                    "thread-created",
                    actor="grill-master",
                    channel=THREAD,
                    key="mandate-1",
                    kind="mandate",
                    title="Storage durability",
                    requires_action=True,
                    turns=[{"who": "grill-master", "text": "This one needs a thread."}],
                )
            ],
        },
    ).json()

    assert receipts[0]["status"] == "accepted"
    assert statuses(log) == []
    assert not driver.started.wait(0.05)
    assert not (session_dir / DISPATCH_DIR).exists()


def test_a_human_turn_in_that_same_thread_produces_a_status_entry_and_a_dispatch(
    log: SessionLog, driver: SpyDriver, session_dir: Path
) -> None:
    """
    Given the same agent-authored thread, which drew no reply
    When the human speaks in it
    Then the lane fires on that thread's channel and a dispatch is recorded.

    The pair with the test above is the whole of the answerability rule: the
    thread is not what decides, the actor is.
    """
    client = driven(log, driver)
    client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [
                event(
                    "thread-created",
                    actor="grill-master",
                    channel=THREAD,
                    key="mandate-1",
                    turns=[{"who": "grill-master", "text": "This one needs a thread."}],
                )
            ],
        },
    )

    receipts = client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [
                event(
                    "thread-turn",
                    actor="human",
                    channel=THREAD,
                    key="human-thread-1",
                    turns=[{"who": "human", "text": "Durability is the point."}],
                )
            ],
        },
    ).json()

    assert receipts[0]["status"] == "accepted"
    assert driver.started.wait(TIMEOUT)
    assert phases(statuses(log)) == [STATUS_PHASE_ACCEPTED, STATUS_PHASE_COMPOSING]
    assert [entry.channel for entry in statuses(log)] == [THREAD, THREAD]
    assert len(list((session_dir / DISPATCH_DIR).glob("*.json"))) == 1


def test_events_returns_its_receipts_without_waiting_for_the_driver_to_finish(
    log: SessionLog,
) -> None:
    """
    Given a tier whose turn is still in flight
    When the human's write is answered
    Then the receipts are already back.

    The human's write must not wait on a model. A write endpoint that returned
    when the turn did would put a 34-second heavy turn in front of every gesture
    the human makes, which is the failure the whole lane exists to prevent.
    """
    driver = SpyDriver(hold=True)
    client = driven(log, driver)
    node = seed_node(client, log.epoch)

    receipts = _post_answer(client, log.epoch, node)

    assert receipts[0]["status"] == "accepted"
    assert driver.started.wait(TIMEOUT)
    assert not driver.finished.is_set()
    driver.release.set()
    assert driver.finished.wait(TIMEOUT)


def _post_answer(client: TestClient, epoch: str, node: str) -> list[dict[str, Any]]:
    """One human turn on the map channel, through the real write endpoint."""
    response = client.post(
        "/events",
        json={
            "epoch": epoch,
            "events": [
                event(
                    "answer",
                    actor="human",
                    key="human-1",
                    target=node,
                    answer={"option": "a", "text": "an append-only log"},
                    why="the audit trail is the point",
                )
            ],
        },
    )
    assert response.status_code == 200
    receipts: list[dict[str, Any]] = response.json()
    return receipts
