"""The status lane's promptness and ordering, and who is owed a reply.

The lane's promptness is a property of its place in the append -- inside the
same lock as the human's turn, before the driver is touched -- so it is pinned
by that structure rather than by a stopwatch. Any clock here, even one reading
the log's own timestamps, is measuring what the machine was doing that second
as much as what the lane does; the ones that remain are coarse backstops, wide
enough that a loaded runner never reaches them.

The drivers here are stubs on purpose. What is being pinned is that the lane is
written before a tier is reached and regardless of whether one answers, so a
driver that blocks forever and a driver that cannot be reached at all are the
two cases worth standing up.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import TIMEOUT, SpyDriver, driven, event, seed_node
from fastapi.testclient import TestClient

from grillui.dispatch import DISPATCH_DIR
from grillui.lane import UnreachableDriver
from grillui.log import SessionLog
from grillui.schemas import (
    STATUS_KIND,
    STATUS_PHASE_ACCEPTED,
    STATUS_PHASE_COMPOSING,
    STATUS_PHASE_ERROR,
    STATUS_PHASE_REPLIED,
    LogEntry,
)

# Only a gross regression -- a model call landing on the lane ahead of the
# emission -- is meant to reach this. A fast tier answers in about a second and a
# heavy one in twelve to thirty-four, so nothing a turn could be made to wait for
# fits underneath, while ordinary scheduling on a busy runner fits with room to
# spare. What the entries cost is pinned structurally, not here.
CEILING_MS = 2000.0
THREAD = "t1"


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


@pytest.fixture
def held() -> Iterator[SpyDriver]:
    """A turn held in flight for the whole test.

    Releasing in teardown rather than in the test body means an assertion
    failing mid-test does not leave the turn thread waiting out TIMEOUT.
    """
    driver = SpyDriver(hold=True)
    yield driver
    driver.release.set()


def test_the_lane_reads_accepted_then_composing_naming_the_dispatching_tier(
    log: SessionLog, held: SpyDriver
) -> None:
    """
    Given a session whose tier is a driver whose turn is still in flight
    When a human answers a decision
    Then the lane carries exactly `accepted` then `composing`, the composing
         entry names the tier taking the turn, and both are backend-authored on
         the human's own channel.

    The tier travels in the entry rather than being looked up by whoever renders
    it: a page that had to infer which tier it was waiting on would infer it from
    configuration the turn may not have used.

    The turn is held for the duration, because what is claimed here is what the
    lane says while a reply is still coming. Reading it after the turn ended
    would be reading the closing phase as well, and racing the driver's thread
    for which of the two the assertion met.
    """
    driver = held
    client = driven(log, driver)
    node = seed_node(client, log.epoch)

    _post_answer(client, log.epoch, node)

    lane = statuses(log)
    assert phases(lane) == [STATUS_PHASE_ACCEPTED, STATUS_PHASE_COMPOSING]
    assert lane[1].payload["tier"] == driver.tier
    assert "tier" not in lane[0].payload
    assert [entry.actor for entry in lane] == ["backend", "backend"]
    assert [entry.channel for entry in lane] == ["map", "map"]


def test_the_lane_lands_with_the_human_turn_rather_than_with_the_reply(
    log: SessionLog, held: SpyDriver
) -> None:
    """
    Given a tier whose turn never finishes
    When a human answers a decision
    Then the human's entry and both lane entries are three consecutive seqs, all
         three already in the log by the time the tier is handed the turn, and
         the tier is still composing when they are read.

    That is the claim, and it is structural: the entries are appended under the
    lock the human's own append holds, and the driver is reached only once that
    lock is released, so no turn can be made to run between them. Timed instead,
    the same claim would pass or fail on what else the machine was doing -- which
    is why the clock left here is wide enough to catch only a model call on the
    path and nothing else.
    """
    driver = held
    client = driven(log, driver)
    node = seed_node(client, log.epoch)

    _post_answer(client, log.epoch, node)

    turn = next(entry for entry in log.entries() if entry.actor == "human")
    lane = statuses(log)
    assert phases(lane) == [STATUS_PHASE_ACCEPTED, STATUS_PHASE_COMPOSING]
    assert [entry.seq for entry in lane] == [turn.seq + 1, turn.seq + 2]
    assert driver.started.wait(TIMEOUT)
    assert [entry.seq for entry in driver.seen[-3:]] == [turn.seq, *(entry.seq for entry in lane)]
    assert not driver.finished.is_set()
    assert elapsed_ms(turn, lane[-1]) < CEILING_MS


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
    Then the lane carries accepted, composing and error, all of them inside a
         window no model call would fit in.

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
    assert elapsed_ms(turn, lane[0]) < CEILING_MS
    assert elapsed_ms(turn, error) < CEILING_MS
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
    log: SessionLog, session_dir: Path, held: SpyDriver
) -> None:
    """
    Given the same agent-authored thread, which drew no reply
    When the human speaks in it
    Then the lane fires on that thread's channel and a dispatch is recorded.

    The pair with the test above is the whole of the answerability rule: the
    thread is not what decides, the actor is.

    Held for the same reason as the first lane check: the claim is about what
    fires when the turn starts, not about what the lane looks like once it ended.
    """
    driver = held
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
    log: SessionLog, held: SpyDriver
) -> None:
    """
    Given a tier whose turn is still in flight
    When the human's write is answered
    Then the receipts are already back.

    The human's write must not wait on a model. A write endpoint that returned
    when the turn did would put a 34-second heavy turn in front of every gesture
    the human makes, which is the failure the whole lane exists to prevent.
    """
    driver = held
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


def test_each_turns_lane_entries_land_adjacent_to_the_turn_they_report(
    log: SessionLog, held: SpyDriver
) -> None:
    """
    Given one batch carrying two human turns on two channels
    When the lane accepts it
    Then each turn is immediately followed by its own accepted and composing,
    rather than the second turn wedging between the first and its lane entries.

    Both turns are held in flight, so the shape read here is the one the append
    lock produced rather than one either turn's closing phase has landed in.
    """
    driver = held
    client = driven(log, driver)
    client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [
                event(
                    "thread-created",
                    actor="human",
                    channel="t1",
                    key="adj-1",
                    kind="side",
                    title="one",
                    turns=[{"who": "human", "text": "one"}],
                ),
                event(
                    "thread-created",
                    actor="human",
                    channel="t2",
                    key="adj-2",
                    kind="side",
                    title="two",
                    turns=[{"who": "human", "text": "two"}],
                ),
            ],
        },
    )

    shape = [(entry.kind, entry.channel) for entry in log.entries()]
    assert shape == [
        ("thread-created", "t1"),
        (STATUS_KIND, "t1"),
        (STATUS_KIND, "t1"),
        ("thread-created", "t2"),
        (STATUS_KIND, "t2"),
        (STATUS_KIND, "t2"),
    ]


def _lane(log: SessionLog) -> list[tuple[Any, str]]:
    """The lane as a reader watching one channel at a time sees it."""
    return [(entry.payload.get("phase"), entry.channel) for entry in statuses(log)]


def test_a_turn_that_ends_closes_the_lane_on_the_channel_it_ran_on(
    log: SessionLog, driver: SpyDriver
) -> None:
    """
    Given a tier whose turn finishes
    When a human answers a decision
    Then the lane reads accepted, composing and then a closing phase, all on the
         channel the turn ran on.

    The closing phase is what makes the lane readable as state rather than as a
    feed. Without it there is no entry that ever says a turn ended, so a reader
    tracking what each channel is waiting on has every channel a turn has ever
    run on waiting for the rest of the session -- and the human is shown a
    permanent "composing" for a reply that arrived minutes ago.
    """
    client = driven(log, driver)
    node = seed_node(client, log.epoch)

    _post_answer(client, log.epoch, node)

    await_phase(log, STATUS_PHASE_REPLIED)
    assert _lane(log) == [
        (STATUS_PHASE_ACCEPTED, "map"),
        (STATUS_PHASE_COMPOSING, "map"),
        (STATUS_PHASE_REPLIED, "map"),
    ]


def test_a_fold_is_acknowledged_in_the_thread_and_composed_and_closed_on_the_map(
    log: SessionLog, driver: SpyDriver
) -> None:
    """
    Given an agent-authored thread, which drew no reply of its own
    When the human folds it
    Then `accepted` lands in the thread and `composing` and its closing phase
         both land on the map, which is where the turn runs.

    The two entries answer different questions and belong in different places.
    `accepted` answers the human: the gesture you just made landed, here where
    you made it. `composing` says who owes a turn -- and for a fold that is the
    grill-master on the map, because the grill-master is the only agent that
    authors map mutations. Announced in the thread instead it would promise a
    reply on a channel no agent was dispatched to, name the thread's tier for a
    turn the map's tier is taking, and leave the map -- where the mutation
    actually lands -- with nothing to say it was coming.
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
                    key="agent-thread",
                    kind="mandate",
                    title="Storage durability",
                    requires_action=True,
                    turns=[{"who": "grill-master", "text": "This one needs a thread."}],
                )
            ],
        },
    )
    assert statuses(log) == [], "an agent-authored thread is owed no reply"

    folded = client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [event("thread-fold", actor="human", channel=THREAD, key="fold-1")],
        },
    ).json()

    assert folded[0]["status"] == "accepted"
    await_phase(log, STATUS_PHASE_REPLIED)
    assert _lane(log) == [
        (STATUS_PHASE_ACCEPTED, THREAD),
        (STATUS_PHASE_COMPOSING, "map"),
        (STATUS_PHASE_REPLIED, "map"),
    ]


def test_a_turn_that_could_not_be_taken_closes_the_lane_where_it_opened(log: SessionLog) -> None:
    """The failing turn closes where the working one does.

    A pair that opened on one channel and closed on another would leave the
    first waiting forever and the second reporting the end of something it was
    never told had started.
    """
    client = driven(log, UnreachableDriver())
    client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [
                event(
                    "thread-created",
                    actor="grill-master",
                    channel=THREAD,
                    key="agent-thread",
                    turns=[{"who": "grill-master", "text": "This one needs a thread."}],
                )
            ],
        },
    )

    client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [event("thread-fold", actor="human", channel=THREAD, key="fold-1")],
        },
    )

    await_phase(log, STATUS_PHASE_ERROR)
    assert _lane(log) == [
        (STATUS_PHASE_ACCEPTED, THREAD),
        (STATUS_PHASE_COMPOSING, "map"),
        (STATUS_PHASE_ERROR, "map"),
    ]
