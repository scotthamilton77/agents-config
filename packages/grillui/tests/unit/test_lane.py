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

Which seat a turn is announced on is here too, because the choice is made in the
same breath as the announcement. Two of the map channel's escalations need no
human text and so are read off the board: the gesture's own class, which seats a
judgment gesture on the expert with no first-rung turn recorded and writes
nothing; and the distrust counter, whose second signal writes one policy
transfer and whose third writes nothing new.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from conftest import TIMEOUT, SpyDriver, driven, event, run_turns, seed_node
from fastapi.testclient import TestClient

from grillui import lane as lane_module
from grillui.dispatch import DISPATCH_DIR
from grillui.lane import DocumentRefusedError, Lane, UnreachableDriver
from grillui.log import SessionLog
from grillui.projector import fold
from grillui.schemas import (
    APPLY_KIND,
    DISMISS_KIND,
    FAST_TIER,
    FOLD_KIND,
    HEAVY_TIER,
    MAP_CHANNEL,
    PENDING_KEY,
    RULINGS_KEY,
    STATUS_KIND,
    STATUS_PHASE_ACCEPTED,
    STATUS_PHASE_COMPOSING,
    STATUS_PHASE_ERROR,
    STATUS_PHASE_REPLIED,
    STATUS_PHASE_TRANSFERRED,
    TIER_KEY,
    TRANSFER_FLAG,
    DispatchContext,
    EventSubmission,
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


# ── An answer that kills other decisions, and what the lane does about it ──

KILLED = ["d2", "d3"]
KILLING_OPTION = {"id": "b", "text": "Close it unactioned", "puts_in_question": KILLED}


def _seed(log: SessionLog) -> None:
    """A board whose first decision offers an option naming the other two.

    Seeded through the appender rather than through the lane, so nothing here
    schedules a turn of its own: what these tests are about is the one turn the
    human's answer buys.
    """
    for node, options in (
        ("d1", [{"id": "a", "text": "Build the export"}, KILLING_OPTION]),
        ("d2", [{"id": "a", "text": "Yes"}, {"id": "b", "text": "No"}]),
        ("d3", [{"id": "a", "text": "Yes"}, {"id": "b", "text": "No"}]),
    ):
        receipt = log.submit(
            [
                EventSubmission(
                    kind="add-node",
                    actor="grill-master",
                    idempotency_key=f"seed-{node}",
                    payload={
                        "target": node,
                        "short": node,
                        "title": f"Which {node}?",
                        "body": "Decide.",
                        "prereqs": [],
                        "options": options,
                    },
                )
            ],
            log.epoch,
        )[0]
        assert receipt.status == "accepted"


def _answer(lane: Lane, option: str = "b") -> None:
    """The human answering the first decision, and the turn it buys, run out."""
    run_turns(
        lane,
        EventSubmission(
            kind="answer",
            actor="human",
            idempotency_key="human-answer",
            payload={"target": "d1", "answer": {"option": option}},
        ),
    )


def _notices(log: SessionLog) -> list[str]:
    """What the backend said to the human in its own voice."""
    return [
        str(entry.payload.get("text"))
        for entry in log.entries()
        if entry.kind == "informational" and entry.actor == "backend"
    ]


def _obligations(driver: Any) -> list[Any]:
    """The mootness obligation on each dispatch this tier was handed."""
    return [
        DispatchContext.model_validate_json(path.read_text(encoding="utf-8")).mootness
        for path in driver.dispatches
    ]


@dataclass
class ProposingDriver:
    """A tier that rules `invalidate` on every id its dispatch named, and queues
    the update each ruling is credited by.

    The turn a model is supposed to take, standing in for one: it reads the
    obligation out of the context it was handed rather than off the board, so a
    dispatch carrying none rules on nothing. The ruling and the update travel
    together because that is what crediting one requires -- a driver that sent
    the verdict alone would be the failure the check exists to catch.
    """

    tier: str = FAST_TIER
    dispatches: list[Path] = field(default_factory=list)

    def run(self, log: SessionLog, dispatch: Path, /) -> None:
        context = DispatchContext.model_validate_json(dispatch.read_text(encoding="utf-8"))
        self.dispatches.append(dispatch)
        named = [] if context.mootness is None else context.mootness.ids
        log.submit(
            [
                EventSubmission(
                    kind=FOLD_KIND,
                    actor="grill-master",
                    idempotency_key=f"reply-{uuid4().hex}",
                    payload={
                        "updates": [
                            {"kind": "informational", "text": "Those are dead."},
                            *(
                                {"kind": "invalidate", "target": one, "why": "the answer kills it"}
                                for one in named
                            ),
                        ],
                        RULINGS_KEY: [
                            {
                                "decision": one,
                                "ruling": "invalidate",
                                "why": "the answer kills it",
                            }
                            for one in named
                        ],
                    },
                )
            ],
            log.epoch,
        )


def test_a_gesture_owed_rulings_is_composed_by_the_expert_carrying_the_ids(
    log: SessionLog,
) -> None:
    """
    Given a board whose answered option names two other decisions still on offer
    When the human takes that option
    Then the expert seat composes the turn, its dispatch names both decisions,
         the decision answered and the option's own text, the first rung is
         never asked, and the lane closes naming the seat that took it.

    The first rung is briefed on the rule and does not honour it -- the live
    session's reply was two sentences against an answer that put eight decisions
    in question. So the seat is not chosen on what a turn said: the gesture owes
    a ruling per decision, which the board states before anyone is asked, and
    that is what names the seat.
    """
    fast = SpyDriver(tier=FAST_TIER, reply="d2 and d3 are dead now.")
    expert = SpyDriver(tier=HEAVY_TIER, reply="Agreed, both are moot.")
    lane = Lane(log, fast, expert=expert)
    _seed(log)

    _answer(lane)

    assert fast.dispatches == [], "a gesture owed rulings went through the first rung"
    obliged = _obligations(expert)
    assert len(obliged) == 1, "the expert did not take the turn"
    assert obliged[0] is not None
    assert obliged[0].ids == KILLED
    assert obliged[0].target == "d1"
    assert obliged[0].answer == KILLING_OPTION["text"]
    assert _lane(log)[-1] == (STATUS_PHASE_REPLIED, "map")
    assert (
        statuses(log, STATUS_PHASE_REPLIED)[-1]
        .payload["detail"]
        .startswith(f"the {HEAVY_TIER!r} tier")
    )


def test_an_expert_that_rules_on_nothing_either_leaves_the_ids_named_to_the_human(
    log: SessionLog,
) -> None:
    """
    Given both tiers ruling on nothing after an answer that puts two decisions
          in question
    When the human takes that option
    Then one backend notice names both decisions, and nothing on the board was
         invalidated by anything but a human gesture.

    Insisting is as far as the backend goes. Minting the invalidates itself
    would be the sole-author rule broken by the code enforcing it, so what is
    left is telling the human which decisions are still being offered -- which
    they can act on through the thread the map is steered from.
    """
    fast = SpyDriver(tier=FAST_TIER, reply="Both are dead.")
    expert = SpyDriver(tier=HEAVY_TIER, reply="Yes, dead.")
    lane = Lane(log, fast, expert=expert)
    _seed(log)

    _answer(lane)

    said = _notices(log)
    assert len(said) == 1, said
    assert ", ".join(KILLED) in said[0]
    assert [entry for entry in log.entries() if entry.kind == "invalidate"] == []


def test_an_obligation_met_or_never_created_presses_nobody(log: SessionLog, tmp_path: Path) -> None:
    """
    Given one session whose classed seat rules `invalidate` on each id it was
          given and queues each update, and another whose human takes the option
          naming nothing
    When each answer's turn is taken
    Then neither takes a second turn and neither says anything to the human, and
         the first has both invalidates waiting in the queue.

    Both halves are about what the press costs when it should not fire. A ruling
    the same turn queued the update for is the obligation met, whether or not the
    human has applied it yet -- a check reading the decision's status alone would
    press every honoured turn. And every session log written before this existed
    carries no pre-marks at all, so each has to go on costing exactly what it
    cost: the obligation is a property of the option the human took.

    Which seat is which follows from the option: the marked one is a judgment
    class and is composed on the expert, the unmarked one is clerical and stays
    on the first rung. Each session's other seat is here to be shown untouched.
    """
    honoured, first_rung = ProposingDriver(tier=HEAVY_TIER), SpyDriver(tier=FAST_TIER)
    _seed(log)
    _answer(Lane(log, first_rung, expert=honoured))

    assert first_rung.dispatches == [], "a judgment gesture went through the first rung"
    assert len(honoured.dispatches) == 1, "the classed seat was asked twice for one gesture"
    assert _notices(log) == []
    queued = fold(log.epoch, log.entries()).pending
    assert sorted(str(one.target) for one in queued if one.kind == "invalidate") == KILLED

    plain = SessionLog(tmp_path / "unmarked")
    prose, unused = SpyDriver(tier=FAST_TIER, reply="Noted."), SpyDriver(tier=HEAVY_TIER)
    _seed(plain)
    _answer(Lane(plain, prose, expert=unused), option="a")

    assert unused.dispatches == []
    assert _notices(plain) == []
    assert _obligations(prose) == [None]


def _seed_resting(log: SessionLog) -> None:
    """`d2` and `d3` resting on `d1`, the shape a dead prereq strands."""
    for node, prereqs in (("d1", []), ("d2", ["d1"]), ("d3", ["d1"])):
        receipt = log.submit(
            [
                EventSubmission(
                    kind="add-node",
                    actor="grill-master",
                    idempotency_key=f"rest-{node}",
                    payload={
                        "target": node,
                        "short": node,
                        "title": f"Which {node}?",
                        "body": "Decide.",
                        "prereqs": prereqs,
                        "options": [{"id": "a", "text": "Yes"}, {"id": "b", "text": "No"}],
                    },
                )
            ],
            log.epoch,
        )[0]
        assert receipt.status == "accepted"


def test_an_invalidate_the_human_applied_obliges_the_map_turn_it_buys(
    log: SessionLog,
) -> None:
    """
    Given two decisions resting on a third, the agent's invalidate on that third
          applied by the human, and the seat ruling on nothing
    When the apply lands and the human then answers one of the two
    Then the map turn the apply bought carries both stranded decisions and the
         invalidation as its rationale, both are answerable at all, one notice
         names them, and the backend authored no map mutation.

    The two halves of the same failure. A dead prereq that still gated its
    dependents left them locked for the rest of the session, so the answer here
    could not have been given at all; and dependents that only made sense given
    the dead prereq are now offered again on a footing that has gone, which is
    what the turn is being asked to rule on.

    The turn the obligation rides is the apply's own (GUI-D48). The answer that
    follows names no decisions and strands none, so it is clerical and stays on
    the first rung -- which is what shows the obligation did not outlive the
    gesture that made it.
    """
    fast = SpyDriver(tier=FAST_TIER, reply="Understood.")
    expert = SpyDriver(tier=HEAVY_TIER, reply="Yes, noted.")
    lane = Lane(log, fast, expert=expert)
    _seed_resting(log)
    log.submit(
        [
            EventSubmission(
                kind="invalidate",
                actor="grill-master",
                idempotency_key="kill-d1",
                payload={"target": "d1", "why": "the export was dropped"},
            )
        ],
        log.epoch,
    )
    queued = fold(log.epoch, log.entries()).pending[0].id

    run_turns(
        lane,
        EventSubmission(
            kind="apply", actor="human", idempotency_key="apply-d1", payload={"pending": [queued]}
        ),
    )
    run_turns(
        lane,
        EventSubmission(
            kind="answer",
            actor="human",
            idempotency_key="answer-d2",
            payload={"target": "d2", "answer": {"option": "a"}},
        ),
    )

    obliged = _obligations(expert)
    assert len(obliged) == 1, "the apply bought no map turn"
    assert obliged[0] is not None
    assert obliged[0].ids == ["d2", "d3"]
    assert obliged[0].target == "d1"
    assert obliged[0].answer == "the export was dropped"
    assert obliged[0].cause == "invalidate"
    assert len(fast.dispatches) == 1, "the clerical answer did not stay on the first rung"
    said = _notices(log)
    assert len(said) == 1, said
    assert "d2, d3" in said[0]
    authored = [one for one in log.entries() if one.actor == "backend" and one.kind == "invalidate"]
    assert authored == []


# ── GMR-A9: the gesture's class names the seat, before any model is called ──


@dataclass
class RefusingDriver:
    """A seat whose reply is never the document the board reads.

    The shape a real driver's refusal takes after its own retry is spent: it
    raises out of `run`, which is what the lane presses on. Standing one up here
    rather than scripting a transport keeps a check about the press about the
    press.
    """

    tier: str = FAST_TIER
    dispatches: list[Path] = field(default_factory=list)
    gate: threading.Barrier | None = None

    def run(self, _log: SessionLog, dispatch: Path, /) -> None:
        self.dispatches.append(dispatch)
        # Held until every racing turn has arrived, so two presses reach the
        # counter together rather than whenever the scheduler happens to run
        # them. Without it the race is real but rarely observed, and a check
        # that only sometimes sees the bug is not a check.
        if self.gate is not None:
            self.gate.wait(TIMEOUT)
        raise DocumentRefusedError(self.tier, "prose")


@dataclass
class WithdrawingDriver:
    """A seat whose turn withdraws a queued notice.

    The one way a withdrawal conflict is raised: the human dealt with the notice
    while it waited, so taking it back now is a disagreement the author has to
    reconcile. The withdrawal goes in through the appender, as a real reply's
    does, or what it proves about the queue is nothing.
    """

    tier: str = FAST_TIER
    withdraws: str = ""
    dispatches: list[Path] = field(default_factory=list)

    def run(self, log: SessionLog, dispatch: Path, /) -> None:
        self.dispatches.append(dispatch)
        log.submit(
            [
                EventSubmission(
                    kind="informational",
                    actor="grill-master",
                    idempotency_key=f"reply-{uuid4().hex}",
                    payload={"text": "Taking that back.", "supersedes": [self.withdraws]},
                )
            ],
            log.epoch,
        )


def _two_seats() -> tuple[SpyDriver, SpyDriver]:
    """A first rung and an expert, each of which says something when it takes a
    turn.

    Speaking matters: an obligation stands until an agent answers on the map, so
    a silent seat would leave the previous gesture's obligation in front of the
    next one and class it too.
    """
    return SpyDriver(tier=FAST_TIER, reply="Noted."), SpyDriver(tier=HEAVY_TIER, reply="Noted.")


def _alert(log: SessionLog, key: str, target: str = "d3", tier: str = FAST_TIER) -> str:
    """One notice on the queue, whose pending id is its key."""
    receipt = log.submit(
        [
            EventSubmission(
                kind="elicit-alert",
                actor="grill-master",
                idempotency_key=key,
                payload={
                    "target": target,
                    "text": "This answer may not survive the retention question.",
                    "blocking": False,
                    TIER_KEY: tier,
                },
            )
        ],
        log.epoch,
    )[0]
    assert receipt.status == "accepted", receipt
    return key


def _proposal(log: SessionLog, key: str, target: str = "d3", tier: str = FAST_TIER) -> str:
    """One seat's proposal waiting in the queue, and the id it is dismissed by.

    The tier rides the authoring entry, which is where a real reply carries it,
    so which rung proposed this is a fact read back off the log rather than one
    the check asserts about itself.
    """
    receipt = log.submit(
        [
            EventSubmission(
                kind="invalidate",
                actor="grill-master",
                idempotency_key=key,
                payload={"target": target, "why": "the export subsumes it", TIER_KEY: tier},
            )
        ],
        log.epoch,
    )[0]
    assert receipt.status == "accepted", receipt
    return key


def _seats(log: SessionLog, channel: str = MAP_CHANNEL) -> list[str]:
    """Which tier the lane announced for each turn on this channel, in order.

    Read off the `composing` entries rather than off the drivers, because that
    entry is what the human sees while they wait: a lane that named the first
    rung and dispatched the expert would be telling them the turn is cheap while
    it spends.
    """
    return [
        str(entry.payload.get(TIER_KEY))
        for entry in statuses(log, STATUS_PHASE_COMPOSING)
        if entry.channel == channel
    ]


def _transfers(log: SessionLog, channel: str = MAP_CHANNEL) -> list[str]:
    """What the lane said each time the policy moved this channel."""
    return [
        str(entry.payload.get("detail"))
        for entry in statuses(log, STATUS_PHASE_TRANSFERRED)
        if entry.channel == channel
    ]


def _answer_at(lane: Lane, node: str, option: str = "a", **payload: Any) -> None:
    """The human answering one decision, and the turn it buys, run out."""
    run_turns(
        lane,
        EventSubmission(
            kind="answer",
            actor="human",
            idempotency_key=f"answer-{node}-{uuid4().hex}",
            payload={"target": node, "answer": {"option": option}, **payload},
        ),
    )


def test_an_answer_whose_mark_resolves_to_a_live_node_is_composed_by_the_expert(
    log: SessionLog,
) -> None:
    """
    Given a board whose answered option names two decisions still on offer
    When the human takes that option
    Then the expert composes the turn, the first rung is never asked, the lane
         names the expert from the start, and no transfer is written.

    The class is what names the seat, so there is no first-rung turn to fall
    back from and nothing to record: the next clerical gesture is first-rung
    again with no entry to undo.
    """
    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    _seed(log)

    _answer(lane)

    assert first.dispatches == [], "a judgment gesture went through the first rung"
    assert len(expert.dispatches) == 1
    assert _seats(log) == [HEAVY_TIER]
    assert _transfers(log) == [], "classing wrote a status entry"


def _apply(lane: Lane, *ids: str) -> None:
    """The human taking queued proposals onto the board, and any turn that
    gesture buys, run out."""
    run_turns(
        lane,
        EventSubmission(
            kind=APPLY_KIND,
            actor="human",
            idempotency_key=f"apply-{uuid4().hex}",
            payload={PENDING_KEY: list(ids)},
        ),
    )


def test_an_applied_invalidate_that_strands_a_dependent_is_composed_by_the_expert(
    log: SessionLog,
) -> None:
    """
    Given two decisions resting on a third and the agent's invalidate on it
    When the human applies that invalidate
    Then that gesture alone is composed by the expert, carrying both stranded
         decisions, with the first rung never asked and nothing written.

    The apply is the gesture that classes, so it is the gesture that gets the
    turn. Left to buy nothing, the class would name a seat for a turn nobody
    scheduled and the rulings it owes would fall on whatever the human happened
    to do next -- or on nothing at all, if they did nothing.
    """
    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    _seed_resting(log)

    _apply(lane, _proposal(log, "kill-d1", target="d1"))

    assert first.dispatches == [], "a judgment gesture went through the first rung"
    assert len(expert.dispatches) == 1, "the apply bought no expert turn of its own"
    obliged = _obligations(expert)[0]
    assert obliged is not None
    assert obliged.ids == ["d2", "d3"], "the turn was not owed both stranded decisions"
    assert obliged.target == "d1"
    assert _seats(log) == [HEAVY_TIER]
    assert _transfers(log) == []


def test_an_apply_that_strands_nothing_buys_no_turn(log: SessionLog) -> None:
    """
    Given an invalidate on a decision nothing rests on
    When the human applies it
    Then no turn is scheduled at all and the lane opens nothing.

    Applying is not conversation and is owed no reply. Only the strand makes it
    a gesture the board owes rulings on, so the ordinary apply -- which is most
    of them -- must go on costing nothing.
    """
    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    _seed_resting(log)

    _apply(lane, _proposal(log, "kill-d3", target="d3"))

    assert (first.dispatches, expert.dispatches) == ([], []), "an idle apply bought a turn"
    assert _seats(log) == []
    assert _transfers(log) == []


def test_a_thread_fold_is_composed_by_the_expert_on_the_map(log: SessionLog) -> None:
    """
    Given a thread the grill-master opened
    When the human folds it
    Then the map turn it schedules is the expert's and the first rung is never
         asked.

    Folding hands the map's author a conclusion to rule on, which is the same
    judgment an answer's mark asks for and not a clerical one.
    """
    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    log.submit(
        [
            EventSubmission(
                kind="thread-created",
                actor="grill-master",
                channel=THREAD,
                idempotency_key="agent-thread",
                payload={"turns": [{"who": "grill-master", "text": "This one needs a thread."}]},
            )
        ],
        log.epoch,
    )

    run_turns(
        lane,
        EventSubmission(
            kind="thread-fold", actor="human", channel=THREAD, idempotency_key="fold-1", payload={}
        ),
    )

    assert first.dispatches == [], "a judgment gesture went through the first rung"
    assert len(expert.dispatches) == 1
    assert _seats(log) == [HEAVY_TIER]
    assert _transfers(log) == []


def test_a_withdrawal_the_human_got_in_front_of_is_composed_by_the_expert(
    log: SessionLog,
) -> None:
    """
    Given a notice the human dealt with and a first-rung turn that then
          withdraws it
    When the conflict is handed back
    Then the hand-back is the expert's turn and carries the conflict, while the
         clerical gesture that started it stayed on the first rung.

    Both halves matter. The conflict is a judgment class, so it does not inherit
    the seat of whoever raised it; and the answer that raised it named no
    decisions, so it was clerical and stayed cheap.

    The hand-back is announced like any other turn. Nobody spoke a gesture to
    start it, which is exactly why it would otherwise close a turn the page
    never saw open.
    """
    first = WithdrawingDriver(tier=FAST_TIER, withdraws="notice-d1")
    expert = SpyDriver(tier=HEAVY_TIER, reply="Understood.")
    lane = Lane(log, first, expert=expert)
    _seed_resting(log)
    _alert(log, "notice-d1", "d1")

    _answer_at(lane, "d1")

    assert len(first.dispatches) == 1
    assert len(expert.dispatches) == 1, "the conflict was not handed to the expert"
    handed = DispatchContext.model_validate_json(expert.dispatches[0].read_text(encoding="utf-8"))
    assert handed.conflict is not None
    assert handed.conflict.update.id == "notice-d1"
    assert _seats(log) == [FAST_TIER, HEAVY_TIER], "the hand-back was never announced"
    assert phases(statuses(log)) == [
        STATUS_PHASE_ACCEPTED,
        STATUS_PHASE_COMPOSING,
        STATUS_PHASE_COMPOSING,
        STATUS_PHASE_REPLIED,
        STATUS_PHASE_REPLIED,
    ], "the hand-back closed a turn it never opened"
    assert _transfers(log) == []


def test_a_supersede_the_human_did_not_get_in_front_of_raises_no_expert_turn(
    log: SessionLog,
) -> None:
    """
    Given a notice on a decision nobody has answered, withdrawn by a first-rung
          turn
    When the turn is over
    Then no second turn is taken at all.

    A supersede-only reconciliation is clerical: the author revised itself and
    the human is not standing on the other side of it, so there is nothing for
    anyone to reconcile and no judgment to buy.
    """
    first = WithdrawingDriver(tier=FAST_TIER, withdraws="notice-d3")
    expert = SpyDriver(tier=HEAVY_TIER, reply="Understood.")
    lane = Lane(log, first, expert=expert)
    _seed_resting(log)
    _alert(log, "notice-d3", "d3")

    _answer_at(lane, "d1")

    assert len(first.dispatches) == 1
    assert expert.dispatches == [], "a supersede nobody got in front of bought an expert turn"
    assert _seats(log) == [FAST_TIER]
    assert _transfers(log) == []


def test_the_doctor_is_composed_by_the_expert(log: SessionLog) -> None:
    """
    Given a board and both seats
    When the human calls the doctor
    Then the expert takes the turn, the first rung is never asked, and nothing
         is written to the lane about a transfer.

    Reassessing the whole board is the escape hatch, and asking the cheap seat
    to do it first would spend the turn the hatch exists to avoid.

    Nobody spoke a gesture to start this turn either, so it is announced the
    way an accepted gesture's turn is: the human pressed a control and is owed
    the same clock, naming the same seat.
    """
    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    _seed_resting(log)

    turn = lane.call_doctor()

    assert turn is not None
    turn.join(TIMEOUT)
    assert not turn.is_alive()
    assert first.dispatches == [], "the doctor went through the first rung"
    assert len(expert.dispatches) == 1
    assert _seats(log) == [HEAVY_TIER], "the doctor turn was never announced"
    assert phases(statuses(log)) == [STATUS_PHASE_COMPOSING, STATUS_PHASE_REPLIED]
    assert _transfers(log) == []


def test_a_clerical_answer_is_composed_by_the_first_rung(log: SessionLog) -> None:
    """
    Given the same board, and the option that names nothing
    When the human takes it
    Then the first rung composes the turn and the expert is never asked.

    The control case for every claim above: the classing has to leave the
    ordinary gesture where it was, or it is not a classing but an escalation.
    """
    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    _seed(log)

    _answer(lane, option="a")

    assert expert.dispatches == [], "a clerical gesture was sent to the expert"
    assert len(first.dispatches) == 1
    assert _seats(log) == [FAST_TIER]
    assert _transfers(log) == []


def test_a_clerical_gesture_after_a_judgment_one_is_first_rung_again(log: SessionLog) -> None:
    """
    Given a judgment gesture already composed by the expert
    When the human then makes a clerical one
    Then it is the first rung's, and no transfer was written by either.

    Classing writes nothing, because there is nothing to fall back from. An
    implementation that recorded the escalation would leave the channel on the
    expert for the rest of the session, and the human would be paying for one
    marked answer until they noticed.
    """
    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    _seed(log)

    _answer(lane)
    _answer_at(lane, "d2")

    assert _seats(log) == [HEAVY_TIER, FAST_TIER]
    assert len(first.dispatches) == 1
    assert len(expert.dispatches) == 1
    assert _transfers(log) == []


def test_a_mark_resolving_to_a_dead_node_stays_on_the_first_rung(log: SessionLog) -> None:
    """
    Given both marked decisions already answered, and so no longer on offer
    When the human takes the option that names them
    Then the turn is the first rung's.

    A mark is a prediction about decisions the board is still offering. Once
    they are settled there is nothing to rule on, so an implementation that read
    the mark alone would buy an expert turn per marked answer for the rest of
    the session -- on a board where every named decision was already dealt with.
    """
    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    _seed(log)

    _answer_at(lane, "d2")
    _answer_at(lane, "d3")
    _answer(lane)

    assert expert.dispatches == [], "a mark resolving to nothing live bought an expert turn"
    assert _seats(log) == [FAST_TIER, FAST_TIER, FAST_TIER]
    assert _transfers(log) == []


# ── GMR-A10: two wordless refusals move the channel, and only ever once ──


def _dismiss(lane: Lane, *ids: str, status: str = "accepted") -> None:
    """The human ending a queue entry, which schedules no turn of its own."""
    receipts, turns = lane.accept(
        [
            EventSubmission(
                kind=DISMISS_KIND,
                actor="human",
                idempotency_key=f"dismiss-{uuid4().hex}",
                payload={PENDING_KEY: list(ids)},
            )
        ],
        lane.log.epoch,
    )
    assert [receipt.status for receipt in receipts] == [status], receipts
    assert turns == [], "a dismissal scheduled a turn"


def test_one_dismissal_of_a_first_rung_proposal_moves_nothing(log: SessionLog) -> None:
    """
    Given a first-rung seat's proposal waiting on the human
    When they dismiss it
    Then nothing is written to the lane and the next map turn is the first
         rung's.

    One is noise. A proposal the human simply did not want is not a seat that
    cannot do the work, and moving the channel on it would spend their money on
    a single click.
    """
    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    _seed_resting(log)

    _dismiss(lane, _proposal(log, "prop-1"))

    assert _transfers(log) == []
    _answer_at(lane, "d2")
    assert _seats(log) == [FAST_TIER]
    assert expert.dispatches == []


@pytest.mark.parametrize(
    "pair",
    [
        pytest.param(("dismiss", "dismiss"), id="dismissal-then-dismissal"),
        pytest.param(("dismiss", "press"), id="dismissal-then-press"),
        pytest.param(("press", "press"), id="press-then-press"),
    ],
)
def test_the_second_distrust_signal_writes_one_transfer_and_the_channel_stays_up(
    log: SessionLog, pair: tuple[str, str]
) -> None:
    """
    Given each way the two distrust signals can be paired
    When the second of them lands
    Then exactly one policy transfer is on the lane, it was not there after the
         first, and every map turn after it is the expert's.

    The two events are counted alike because they say the same thing without
    words: the human refusing a proposal, and the backend finding the reply too
    thin to stand. Counting only one of them would need the human to click the
    same refusal twice before the channel moved.
    """
    presses = "press" in pair
    first: Any = (
        RefusingDriver(tier=FAST_TIER) if presses else SpyDriver(tier=FAST_TIER, reply="Noted.")
    )
    expert = SpyDriver(tier=HEAVY_TIER, reply="Noted.")
    lane = Lane(log, first, expert=expert)
    _seed_resting(log)

    for index, (signal, node) in enumerate(zip(pair, ("d1", "d2"), strict=True)):
        if signal == "dismiss":
            _dismiss(lane, _proposal(log, f"prop-{index}"))
        else:
            _answer_at(lane, node)
        assert len(_transfers(log)) == index, (
            f"signal {index + 1} wrote the wrong number of entries"
        )

    _answer_at(lane, "d3")

    assert len(_transfers(log)) == 1
    assert _seats(log)[-1] == HEAVY_TIER, "the channel did not stay on the expert"


def test_a_third_signal_writes_no_second_entry(log: SessionLog) -> None:
    """
    Given a channel the policy has already moved
    When a third distrust signal lands
    Then no second entry joins the first.

    The channel is already there, so a second entry would say nothing and cost a
    reader working out which of two transfers is live.
    """
    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    _seed_resting(log)

    for index in range(3):
        _dismiss(lane, _proposal(log, f"prop-{index}"))

    assert len(_transfers(log)) == 1


def test_the_humans_transfer_control_returns_the_channel_to_the_first_rung(
    log: SessionLog,
) -> None:
    """
    Given a channel the policy moved on the second signal
    When the human takes the transfer back
    Then that turn and the next are the first rung's, and a later signal writes
         no second entry.

    An entry only ever moves a channel up; the way back down is theirs. A
    counter that fired again afterwards would overturn the human's own control
    on the next click they made.
    """
    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    _seed_resting(log)
    for index in range(2):
        _dismiss(lane, _proposal(log, f"prop-{index}"))
    assert len(_transfers(log)) == 1

    _answer_at(lane, "d1", **{TRANSFER_FLAG: False})
    _dismiss(lane, _proposal(log, "prop-later"))
    _answer_at(lane, "d2")

    assert _seats(log) == [FAST_TIER, FAST_TIER]
    assert len(_transfers(log)) == 1, "a signal after the human's control wrote a second entry"


def test_a_press_on_a_thread_channel_is_no_signal_about_the_map(log: SessionLog) -> None:
    """
    Given a thread whose first-rung seat never returns a document
    When the human speaks in it twice and both turns are pressed onto the expert
    Then nothing is written on the map channel.

    The counter is the map's, because that is the channel these three triggers
    are about. A thread that cannot hold its own shape says nothing about the
    seat composing the board, and counting it would move the map on turns the
    human took somewhere else entirely.
    """
    first, expert = RefusingDriver(tier=FAST_TIER), SpyDriver(tier=HEAVY_TIER, reply="Noted.")
    lane = Lane(log, first, expert=expert)
    log.submit(
        [
            EventSubmission(
                kind="thread-created",
                actor="grill-master",
                channel=THREAD,
                idempotency_key="agent-thread",
                payload={"turns": [{"who": "grill-master", "text": "This one needs a thread."}]},
            )
        ],
        log.epoch,
    )

    for index in range(2):
        run_turns(
            lane,
            EventSubmission(
                kind="thread-turn",
                actor="human",
                channel=THREAD,
                idempotency_key=f"said-{index}",
                payload={"turns": [{"text": "Say more about the retention window."}]},
            ),
        )

    assert len(first.dispatches) == 2
    assert len(expert.dispatches) == 2, "the thread turns were not pressed"
    assert _transfers(log) == [], "a thread's press moved the map channel"


def test_a_dismissal_naming_a_proposal_the_queue_never_held_is_read_without_raising(
    log: SessionLog,
) -> None:
    """
    Given a well-shaped dismissal naming an id no proposal in the queue carries
    When it is offered twice
    Then nothing is written and the batch came back with receipts rather than
         an exception.

    The count is read before the gesture lands, which puts this reader in front
    of the appender rather than behind it -- and inside the append lock, where
    an exception would take the whole batch down instead of one refused event.
    A gesture that named no proposal refused none either way.
    """
    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    _seed_resting(log)

    for _ in range(2):
        receipts, turns = lane.accept(
            [
                EventSubmission(
                    kind=DISMISS_KIND,
                    actor="human",
                    idempotency_key=f"dismiss-{uuid4().hex}",
                    payload={PENDING_KEY: ["no-such-proposal"]},
                )
            ],
            log.epoch,
        )
        assert [receipt.status for receipt in receipts] == ["rejected"]
        assert turns == []

    assert _transfers(log) == []


def test_dismissing_the_experts_own_proposal_is_no_signal(log: SessionLog) -> None:
    """
    Given two proposals the expert seat authored
    When the human dismisses both
    Then nothing is written and the next map turn is the first rung's.

    A proposal the expert wrote says nothing about the rung below it. Counting
    it would move the channel to the seat the human has just twice said got it
    wrong, which is the one move the count is not evidence for.
    """
    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    _seed_resting(log)

    for index in range(2):
        _dismiss(lane, _proposal(log, f"theirs-{index}", tier=HEAVY_TIER))

    assert _transfers(log) == []
    _answer_at(lane, "d2")
    assert _seats(log) == [FAST_TIER]
    assert expert.dispatches == []


def test_a_dismissal_the_queue_refuses_is_no_signal(log: SessionLog) -> None:
    """
    Given a notice on the queue, which is not a proposal and so not something to
          dismiss
    When two dismissals naming it are refused, and one real dismissal follows
    Then nothing is written to the lane.

    The count is taken on the gesture that landed. A refused gesture changed
    nothing the human can see, so counting it would move the channel on two
    clicks that did nothing -- and the queue is full of notices, the backend's
    own unmet-obligation ones among them.
    """
    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    _seed_resting(log)
    told = _alert(log, "notice-d3")

    for _ in range(2):
        _dismiss(lane, told, status="rejected")
    _dismiss(lane, _proposal(log, "prop-1"))

    assert _transfers(log) == []


class RacingLog(SessionLog):
    """A log that holds the first policy transfer inside its own append until a
    second writer has decided to make one too.

    The interleave the counter's critical section has to close, made
    deterministic. The guard is a read of the record, so a writer that has not
    appended yet is invisible to the next reader: held here, the second signal
    asks the question while the first answer is still in flight. That is the
    window two turn threads race through on their own -- but only for the few
    microseconds of pure Python between the read and the write, which no barrier
    placed outside the lane can reliably land in.

    The wait is bounded and its expiry is the passing shape: where the two steps
    are one critical section the second writer never arrives, because it is
    still waiting on the lock the first is holding.
    """

    gate: threading.Barrier | None = None

    def emit_status(
        self, phase: str, detail: str, channel: str = MAP_CHANNEL, *, tier: str | None = None
    ) -> LogEntry:
        if phase == STATUS_PHASE_TRANSFERRED and self.gate is not None:
            with suppress(threading.BrokenBarrierError):
                # Long enough that a descheduled racer cannot slip past it and
                # let the broken build write alone -- and still inside the join
                # the caller waits the turn out with, so a gate nobody else
                # reaches ends the turn rather than hanging it.
                self.gate.wait(TIMEOUT / 2)
        return super().emit_status(phase, detail, channel, tier=tier)


def test_two_presses_racing_write_one_transfer_between_them(session_dir: Path) -> None:
    """
    Given one dismissal already counted, and two clerical map gestures in one
          batch whose first-rung turns run concurrently and are held until both
          are ready to be pressed
    When both presses reach the counter together
    Then exactly one policy transfer is on the lane.

    Turn threads race by design, so "at most one entry" has to hold against the
    racing pair and not only against the sequential one. The first signal is
    spent up front deliberately: below the threshold a signal returns before it
    reaches the guard at all, so a pair racing from zero has only one of them in
    the window. From one, both cross the threshold together -- and counting,
    asking whether the policy has already moved this channel, and writing are
    three separate reads and a write over shared state. Split apart, both see an
    empty guard and both append, and the entry is sticky, so the second is not
    something a later pass could tidy up.
    """
    log = RacingLog(session_dir)
    log.gate = threading.Barrier(2)
    first = RefusingDriver(tier=FAST_TIER, gate=threading.Barrier(2))
    expert = SpyDriver(tier=HEAVY_TIER, reply="Noted.")
    lane = Lane(log, first, expert=expert)
    _seed_resting(log)
    _dismiss(lane, _proposal(log, "prop-0"))
    assert _transfers(log) == [], "the first signal wrote an entry"

    _receipts, turns = lane.accept(
        [
            EventSubmission(
                kind="answer",
                actor="human",
                idempotency_key=f"racing-{node}",
                payload={"target": node, "answer": {"option": "a"}},
            )
            for node in ("d2", "d3")
        ],
        log.epoch,
    )
    for turn in turns:
        turn.join(TIMEOUT)
        assert not turn.is_alive(), "a racing turn outlived its timeout"

    assert len(first.dispatches) == 2, "the two turns did not both reach the first rung"
    assert len(_transfers(log)) == 1, "two racing presses wrote two transfers"


def test_a_restart_over_the_same_session_writes_no_second_transfer(
    log: SessionLog, session_dir: Path
) -> None:
    """
    Given a channel the policy has already moved, and a successor process
          opening the same session directory
    When two further dismissals land on the fresh lane
    Then no second entry joins the first, and the map is still the expert's.

    The count is one tenure's and starts again; the move is the log's and does
    not. A successor that asked its own counter alone would reach the threshold
    a second time and buy a channel it is already on -- which is why the guard
    reads the record rather than the tally.
    """
    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    _seed_resting(log)
    for index in range(2):
        _dismiss(lane, _proposal(log, f"prop-{index}"))
    assert len(_transfers(log)) == 1

    successor = SessionLog(session_dir)
    later_first, later_expert = _two_seats()
    later = Lane(successor, later_first, expert=later_expert)
    for index in range(2):
        _dismiss(later, _proposal(successor, f"after-{index}"))

    assert len(_transfers(successor)) == 1, "a restarted tenure bought the transfer again"
    _answer_at(later, "d2")
    assert _seats(successor)[-1] == HEAVY_TIER, "the move did not survive the restart"
    assert later_first.dispatches == []


def test_the_applys_dispatch_carries_the_obligation_it_was_scheduled_for(
    log: SessionLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given an apply that stranded two decisions, and a map reply landing between
          the gesture being scheduled and its turn being taken
    When the turn is taken
    Then its dispatch still names both stranded decisions.

    The obligation is a window on the log that closes at the last thing an agent
    said on the map. A turn that read it again when it ran would find the window
    shut and be handed nothing -- or, later in a session, the next gesture's
    obligation in place of its own. Scheduling is where the gesture is known, so
    scheduling is where the obligation is taken.
    """
    real = lane_module.record_dispatch

    def interleaved(session: SessionLog, **rest: Any) -> Path:
        monkeypatch.setattr(lane_module, "record_dispatch", real)
        session.submit(
            [
                EventSubmission(
                    kind="informational",
                    actor="grill-master",
                    idempotency_key="in-between",
                    payload={"text": "Something else entirely."},
                )
            ],
            session.epoch,
        )
        return real(session, **rest)

    first, expert = _two_seats()
    lane = Lane(log, first, expert=expert)
    _seed_resting(log)
    monkeypatch.setattr(lane_module, "record_dispatch", interleaved)

    _apply(lane, _proposal(log, "kill-d1", target="d1"))

    obliged = _obligations(expert)[0]
    assert obliged is not None, "the reply in between emptied the apply's obligation"
    assert obliged.ids == ["d2", "d3"]
    assert obliged.target == "d1"
