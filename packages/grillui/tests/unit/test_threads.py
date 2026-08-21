"""Thread agents in their own contexts, and who is allowed to change the map.

Two rules are pinned here, and both are about what an agent is and is not
handed.

**A thread agent gets its own thread and stubs of the rest.** The claims about
that are made against the bytes the backend recorded giving it, not against a
projection the test built: what a thread agent knows about another thread is
exactly what those bytes contain, and asserting on an in-memory model would pass
just as happily against a recorder that wrote something else.

**Only the grill-master authors map mutations.** That is asserted from both
sides -- over the wire and out of a driver's own reply -- because a rule enforced
on one path and not the other is not enforced. Where a conclusion does reach the
board, the assertion is on the log entry's actor and channel rather than on the
call that produced it.

Nothing here reaches a network or a model: both tiers run against scripted
transports, and every concurrency claim is settled by a barrier or by the log's
own record rather than by sleeping and hoping.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from conftest import TIMEOUT, ScriptedCli, ScriptedFast, event, post, run_turns, seed_node
from fastapi.testclient import TestClient

from grillui.dispatch import GRILL_MASTER, THREAD_AGENT, record_dispatch
from grillui.drivers import FastDriver, HeavyDriver, ReplyRefusedError
from grillui.lane import Lane, TurnDriver
from grillui.log import LOG_FILE, SessionLog
from grillui.projector import fold, project_thread, to_image1
from grillui.schemas import (
    MAP_CHANNEL,
    MAP_MUTATION_KINDS,
    REASON_THREAD_MAP_MUTATION,
    REASON_UNKNOWN_KIND,
    STATUS_KIND,
    STATUS_PHASE_COMPOSING,
    STATUS_PHASE_ERROR,
    THREAD_FOLD_KIND,
    THREAD_PARK_KIND,
    TRANSFER_FLAG,
    DispatchContext,
    EventSubmission,
    Image2,
    Thread,
)
from grillui.tiers import TierConfig

NODE = "d-store"
MINE = "t-mine"
OTHER = "t-other"
DONE = "t-done"
PARKED = "t-parked"

# Every thread says something nothing else says, so "this thread's turns and no
# other's" is checkable by looking for the words in the recorded bytes.
MINE_SAID = "mine: how long is a session kept?"
OTHER_SAID = "other: when is the log compacted?"
DONE_ASKED = "done: what are the files called?"
DONE_CONCLUDED = "done: name them for the session id."
PARKED_SAID = "parked: what backs the directory up?"
MINE_CONCLUDED = "mine: keep a session for thirty days, then archive it."


# --- building a board with threads on it ---------------------------------------


def open_thread(client: TestClient, epoch: str, thread: str, title: str, said: str) -> None:
    receipt = post(
        client,
        epoch,
        event(
            "thread-created",
            actor="human",
            channel=thread,
            key=f"open-{thread}",
            decision=NODE,
            kind="mandate",
            title=title,
            requires_action=True,
            turns=[{"who": "human", "text": said}],
        ),
    )[0]
    assert receipt["status"] == "accepted"


def say(
    client: TestClient, epoch: str, thread: str, text: str, actor: str = "thread-agent"
) -> None:
    receipt = post(
        client,
        epoch,
        event(
            "thread-turn",
            actor=actor,
            channel=thread,
            key=f"said-{thread}-{text[:12]}",
            turns=[{"who": actor, "text": text}],
        ),
    )[0]
    assert receipt["status"] == "accepted"


def gesture(client: TestClient, epoch: str, kind: str, thread: str) -> dict[str, Any]:
    return post(client, epoch, event(kind, actor="human", channel=thread, key=f"{kind}-{thread}"))[
        0
    ]


def board(client: TestClient, epoch: str) -> None:
    """One decision and four threads: two live, one folded, one parked."""
    seed_node(client, epoch, NODE)
    open_thread(client, epoch, MINE, "Retention", MINE_SAID)
    open_thread(client, epoch, OTHER, "Compaction", OTHER_SAID)
    open_thread(client, epoch, DONE, "Naming", DONE_ASKED)
    say(client, epoch, DONE, DONE_CONCLUDED)
    assert gesture(client, epoch, THREAD_FOLD_KIND, DONE)["status"] == "accepted"
    open_thread(client, epoch, PARKED, "Backups", PARKED_SAID)
    assert gesture(client, epoch, THREAD_PARK_KIND, PARKED)["status"] == "accepted"


def turn_event(kind: str, channel: str, key: str, **payload: Any) -> EventSubmission:
    """One human gesture, straight to the lane rather than over HTTP: the tests
    that schedule turns need the threads back to join them."""
    return EventSubmission(
        kind=kind, actor="human", channel=channel, idempotency_key=key, payload=payload
    )


def human_answer(key: str, **payload: Any) -> EventSubmission:
    return turn_event(
        "answer", MAP_CHANNEL, key, target=NODE, answer={"text": "an append-only log"}, **payload
    )


def raw(log: SessionLog) -> str:
    return (log.directory / LOG_FILE).read_text(encoding="utf-8")


def contexts(dispatches: list[Path]) -> list[DispatchContext]:
    return [
        DispatchContext.model_validate_json(path.read_text(encoding="utf-8")) for path in dispatches
    ]


def composing(log: SessionLog) -> dict[str, str]:
    """Which tier the lane told the human each channel is waiting on."""
    return {
        entry.channel: str(entry.payload.get("tier"))
        for entry in log.entries()
        if entry.kind == STATUS_KIND and entry.payload.get("phase") == STATUS_PHASE_COMPOSING
    }


def errors(log: SessionLog) -> list[str]:
    return [
        str(entry.payload.get("detail"))
        for entry in log.entries()
        if entry.kind == STATUS_KIND and entry.payload.get("phase") == STATUS_PHASE_ERROR
    ]


@dataclass
class BarrierDriver:
    """A tier whose turn cannot finish until every expected turn has started.

    Concurrency is proved by the barrier tripping: turns taken one after another
    never reach the party count, and the wait times out into a broken barrier
    rather than passing on a sleep that happened to be long enough.
    """

    barrier: threading.Barrier
    tier: str = "fast"
    dispatches: list[Path] = field(default_factory=list)

    def run(self, _log: SessionLog, dispatch: Path, /) -> None:
        self.dispatches.append(dispatch)
        self.barrier.wait(TIMEOUT)


@dataclass
class RecordingDriver:
    """A tier that takes a turn by noting what it was handed and saying nothing."""

    tier: str = "fast"
    dispatches: list[Path] = field(default_factory=list)

    def run(self, _log: SessionLog, dispatch: Path, /) -> None:
        self.dispatches.append(dispatch)


def fast_tier(reply: str) -> tuple[TurnDriver, ScriptedFast]:
    """The real fast driver over a scripted model, so a turn runs the shipped
    path: the prompt is composed, the reply is read, and the log is written to
    by the code that does it in a session."""
    transport = ScriptedFast(reply=reply)
    return FastDriver(TierConfig(), transport), transport


def mutation_reply(text: str, title: str) -> str:
    return json.dumps(
        {"text": text, "updates": [{"kind": "revise", "target": NODE, "title": title}]}
    )


# ── GUI-D24 / §8.8: the thread projection ──


def test_the_dispatched_thread_crosses_in_full_and_every_other_as_a_stub(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a board carrying the dispatched thread, a second live one, a folded
    one and a parked one
    When it is projected for the dispatched thread's agent
    Then that thread is image 2's own, unchanged; every other live thread is a
         stub of exactly the five fields and nothing else, with the conclusion
         present on the folded one and absent on the open one; and the parked
         thread is not there at all.

    The stub set is the whole contract: a stub carrying turns is the context
    bloat the projection exists to prevent, and a folded stub without its
    conclusion is a thread that changed the board and will not say how.
    """
    board(client, log.epoch)
    image = fold(log.epoch, log.entries())

    projection = project_thread(image, MINE)

    mine = next(thread for thread in image.threads if thread.id == MINE)
    written = json.loads(projection.model_dump_json())["threads"]
    assert written[0] == json.loads(mine.model_dump_json())
    assert written[1:] == [
        {"id": OTHER, "decision": NODE, "title": "Compaction", "state": "open"},
        {
            "id": DONE,
            "decision": NODE,
            "title": "Naming",
            "state": "folded",
            "conclusion": DONE_CONCLUDED,
        },
    ]


def test_the_projections_board_is_image_twos_board_unchanged(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an image with decisions, history, a frontier, settled answers and a
    pending queue
    When it is projected for one thread
    Then every section but the threads is image 2's, byte for byte, and the
         field set and its order are image 2's too.

    The projection reduces other threads' bodies and nothing else. A decision
    dropped on this path would be as invisible as one dropped from a dispatch,
    and the field-order check is what keeps a projection whose threads are all
    full bodies serialising as image 2 does.
    """
    board(client, log.epoch)
    post(
        client,
        log.epoch,
        event(
            "answer",
            actor="human",
            key="settle-store",
            target=NODE,
            answer={"option": "a", "text": "an append-only log"},
            why="the audit trail is the point",
        ),
    )
    image = fold(log.epoch, log.entries())

    projected = json.loads(project_thread(image, MINE).model_dump_json())

    whole = json.loads(image.model_dump_json())
    assert list(projected) == list(whole)
    for section in ("epoch", "seq", "decisions", "frontier", "settled", "pending", "history"):
        assert json.dumps(projected[section]) == json.dumps(whole[section])
    assert whole["settled"] and whole["history"]


def test_projecting_a_fixed_board_twice_yields_byte_identical_bytes(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given one log
    When it is folded and projected twice over
    Then both projections are byte-identical.

    The same determinism guarantee the images carry: a dispatch is reproducible
    from the log alone, so what an agent was given can be rebuilt after the
    fact rather than taken on trust.
    """
    board(client, log.epoch)

    once = project_thread(fold(log.epoch, log.entries()), MINE).model_dump_json()

    assert once == project_thread(fold(log.epoch, log.entries()), MINE).model_dump_json()


def test_a_thread_gesture_sets_that_threads_state_and_moves_no_decision(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a folded thread and a parked one
    When the board is folded
    Then each thread carries the state its gesture set, and no decision moved.

    Folding a thread is not a map mutation: the conclusion reaches the board
    only through the grill-master, so the gesture itself must leave every
    decision exactly as it was.
    """
    seed_node(client, log.epoch, NODE)
    open_thread(client, log.epoch, MINE, "Retention", MINE_SAID)
    open_thread(client, log.epoch, DONE, "Naming", DONE_ASKED)
    say(client, log.epoch, DONE, DONE_CONCLUDED)
    before = fold(log.epoch, log.entries()).decisions

    assert gesture(client, log.epoch, THREAD_FOLD_KIND, DONE)["status"] == "accepted"
    assert gesture(client, log.epoch, THREAD_PARK_KIND, MINE)["status"] == "accepted"

    image = fold(log.epoch, log.entries())
    assert {thread.id: thread.state for thread in image.threads} == {
        MINE: "parked",
        DONE: "folded",
    }
    assert image.decisions == before


@pytest.mark.parametrize("kind", [THREAD_FOLD_KIND, THREAD_PARK_KIND])
def test_a_thread_gesture_sent_on_the_map_channel_is_refused(
    kind: str, client: TestClient, log: SessionLog
) -> None:
    """
    Given the map channel, which is not a thread
    When a thread gesture arrives on it
    Then it is refused and appended nowhere.

    A thread gesture names its thread by the channel it arrived on, so one
    addressed to the map names none. Accepting it is worse than a no-op: the
    board does not move, but folding is a gesture the grill-master owes an
    answer to, so it would spend a whole turn routing a conclusion that does
    not exist.
    """
    seed_node(client, log.epoch, NODE)
    before = log.entries()

    receipt = post(client, log.epoch, event(kind, actor="human", key="k1"))[0]

    assert receipt["status"] == "rejected"
    assert receipt["reason"] == REASON_UNKNOWN_KIND
    assert log.entries() == before


def test_a_thread_fold_on_the_map_channel_dispatches_nothing(
    session_dir: Path, log: SessionLog
) -> None:
    """
    Given a lane with a tier attached
    When a thread fold arrives on the map channel
    Then no dispatch is recorded and no turn is scheduled.

    The refusal is what stops the burn, and the evidence is the absence of a
    dispatch file: a grill-master handed an empty conclusion and told to act on
    it costs a heavy turn and answers a question nobody asked.
    """
    lane = Lane(log, RecordingDriver())

    receipts, turns = lane.accept([turn_event(THREAD_FOLD_KIND, MAP_CHANNEL, "k1")], log.epoch)

    assert [receipt.status for receipt in receipts] == ["rejected"]
    assert turns == []
    assert not (session_dir / "dispatches").exists()


# ── GUI-D24 / GUI-A36: dispatch identity and what a thread agent is handed ──


def test_a_thread_dispatch_is_recorded_for_the_thread_agent_carrying_its_projection(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a session with several threads
    When the backend records a dispatch on one thread's channel
    Then the recorded context names the thread agent on that channel and carries
         that thread's projection.

    A thread dispatch labelled `grill-master` is the sole-author rule undone
    before anything is written: the agent reasoning about the board would be the
    one told it may change it.
    """
    board(client, log.epoch)
    image = fold(log.epoch, log.entries())

    recorded = record_dispatch(log, channel=MINE)

    context = contexts([recorded])[0]
    assert (context.agent, context.channel) == (THREAD_AGENT, MINE)
    assert context.image2.model_dump_json() == project_thread(image, MINE).model_dump_json()


def test_a_map_dispatch_is_still_the_grill_masters_and_carries_image_two_whole(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given the same session
    When the backend records a dispatch on the map channel
    Then it names the grill-master and carries image 2 with every thread's body
         intact.

    The negative control for the projection: without it, a projector that
    stubbed every dispatch would satisfy the thread case and quietly starve the
    grill-master.
    """
    board(client, log.epoch)
    image = fold(log.epoch, log.entries())

    recorded = record_dispatch(log)

    context = contexts([recorded])[0]
    assert (context.agent, context.channel) == (GRILL_MASTER, MAP_CHANNEL)
    assert image.model_dump_json() in recorded.read_text(encoding="utf-8")
    assert OTHER_SAID in recorded.read_text(encoding="utf-8")


def test_a_recorded_thread_dispatch_holds_no_other_threads_turns(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given four threads, each of which said something nothing else said
    When one thread's dispatch is recorded
    Then its own words are in the bytes, no other thread's turns are, and the
         one thing a stub does quote -- a folded thread's conclusion -- is.

    Checked against the recorded file rather than the model: those bytes are
    what the agent is given, and they are the only evidence after the turn is
    over.
    """
    board(client, log.epoch)

    recorded = record_dispatch(log, channel=MINE).read_text(encoding="utf-8")

    assert MINE_SAID in recorded
    assert OTHER_SAID not in recorded
    assert PARKED_SAID not in recorded
    assert DONE_ASKED not in recorded
    assert DONE_CONCLUDED in recorded


def test_two_thread_channels_take_turns_concurrently_while_the_map_is_in_flight(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a human turn on the map and one in each of two threads, submitted
    together
    When the lane schedules them
    Then all three turns are in flight at once, and each thread's dispatch
         carries its own new turn and not the other's.

    The barrier is the proof: three turns taken one after another never reach
    the party count, so a lane that serialised them would break the barrier
    rather than pass on timing. Thread agents run in separate contexts,
    concurrently, by design.
    """
    board(client, log.epoch)
    driver = BarrierDriver(threading.Barrier(3))
    lane = Lane(log, driver)

    run_turns(
        lane,
        human_answer("map-turn"),
        turn_event("thread-turn", MINE, "mine-turn", turns=[{"text": "and after thirty days?"}]),
        turn_event("thread-turn", OTHER, "other-turn", turns=[{"text": "and on restart?"}]),
    )

    assert errors(log) == []
    recorded = {
        context.channel: path.read_text(encoding="utf-8")
        for context, path in zip(contexts(driver.dispatches), driver.dispatches, strict=True)
    }
    assert set(recorded) == {MAP_CHANNEL, MINE, OTHER}
    assert "and after thirty days?" in recorded[MINE]
    assert "and on restart?" not in recorded[MINE]
    assert "and on restart?" in recorded[OTHER]
    assert "and after thirty days?" not in recorded[OTHER]


def test_escalating_one_thread_leaves_every_other_channel_on_the_fast_tier(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a human turn carrying a transfer in one thread, and ordinary turns in
    another thread and on the map
    When the lane schedules all three
    Then only the escalated thread composes on the expert tier, and only its
         turn reaches that driver.

    The tier is a property of the channel. A session-wide tier would move every
    channel on one escalation, and the human who paid for one heavy turn would
    be paying for all of them.
    """
    board(client, log.epoch)
    fast, expert = RecordingDriver("fast"), RecordingDriver("heavy")
    lane = Lane(log, fast, expert)

    run_turns(
        lane,
        turn_event(
            "thread-turn",
            MINE,
            "escalated",
            turns=[{"text": "just decide"}],
            **{TRANSFER_FLAG: True},
        ),
        turn_event("thread-turn", OTHER, "ordinary", turns=[{"text": "and on restart?"}]),
        human_answer("map-turn"),
    )

    assert composing(log) == {MINE: "heavy", OTHER: "fast", MAP_CHANNEL: "fast"}
    assert [context.channel for context in contexts(expert.dispatches)] == [MINE]
    assert sorted(context.channel for context in contexts(fast.dispatches)) == [MAP_CHANNEL, OTHER]


def test_a_channel_stays_on_the_expert_tier_until_the_human_takes_it_back(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a thread the human escalated
    When they take another turn in it saying nothing about tiers, and then one
    that returns it
    Then the middle turn is still composed by the expert tier and the last one
         is back on the fast tier.

    Expert mode is a state the human set, not a flag on one message: a channel
    that fell back the moment they stopped repeating themselves would silently
    undo the transfer they asked for.
    """
    board(client, log.epoch)
    fast, expert = RecordingDriver("fast"), RecordingDriver("heavy")
    lane = Lane(log, fast, expert)

    run_turns(
        lane,
        turn_event("thread-turn", MINE, "on", turns=[{"text": "up"}], **{TRANSFER_FLAG: True}),
    )
    run_turns(lane, turn_event("thread-turn", MINE, "still", turns=[{"text": "go on"}]))
    run_turns(
        lane,
        turn_event("thread-turn", MINE, "off", turns=[{"text": "back"}], **{TRANSFER_FLAG: False}),
    )

    tiers = [
        entry.payload.get("tier")
        for entry in log.entries()
        if entry.kind == STATUS_KIND and entry.payload.get("phase") == STATUS_PHASE_COMPOSING
    ]
    assert tiers == ["heavy", "heavy", "fast"]


def test_the_grill_masters_heavy_turns_issue_one_process_at_a_time_under_thread_load(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given the map escalated to the heavy tier and two thread turns running
    beside it
    When two map turns and two thread turns are scheduled together
    Then no two heavy invocations ever overlap, and the thread turns are taken
         by the fast tier regardless.

    Thread agents are outside the single-process rule and the grill-master is
    not: the resumed-turn discount lives in a cache one process holds, and two
    processes talking over each other on one chain forfeit it.
    """
    board(client, log.epoch)
    cli = ScriptedCli(hold=0.05)
    fast, transport = fast_tier("Retention is the open question.")
    lane = Lane(log, fast, HeavyDriver(TierConfig(), cli))

    run_turns(
        lane,
        human_answer("map-one", **{TRANSFER_FLAG: True}),
        human_answer("map-two", **{TRANSFER_FLAG: True}),
        turn_event("thread-turn", MINE, "mine-turn", turns=[{"text": "and after that?"}]),
        turn_event("thread-turn", OTHER, "other-turn", turns=[{"text": "and on restart?"}]),
    )

    assert errors(log) == []
    assert cli.overlapping is False
    assert len(cli.calls) == 2
    assert len(transport.calls) == 2


# ── GUI-D25 / GUI-A37: the grill-master is the sole author of map mutations ──


def test_a_map_mutation_submitted_on_a_thread_channel_is_rejected_and_appended_nowhere(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a thread agent submitting a revise on its own thread's channel
    When the write is judged
    Then it comes back rejected with the sole-author reason and no trace of it
         reaches the log.

    Thread agents recommend; they never emit map updates. A mutation authored
    anywhere but the map channel changes the board behind the agent that has to
    reason about it next.
    """
    board(client, log.epoch)
    before = raw(log)

    receipt = post(
        client,
        log.epoch,
        event("revise", actor="thread-agent", channel=MINE, key="sneak", target=NODE, title="mine"),
    )[0]

    assert receipt["status"] == "rejected"
    assert receipt["reason"] == REASON_THREAD_MAP_MUTATION
    assert raw(log) == before


def test_a_thread_agents_declared_updates_are_refused_by_the_same_appender(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a thread agent whose reply declares a map update
    When its turn runs
    Then the turn fails with the sole-author reason and the update reaches the
         log no more than it would have over the wire.

    A driver is a client of the appender like anything else. If the rule were
    enforced only on the HTTP path, the one caller that never takes it would be
    the one running inside the backend.
    """
    board(client, log.epoch)
    before = raw(log)
    driver, _ = fast_tier(mutation_reply("Folding this in.", "rewritten by a thread"))

    with pytest.raises(ReplyRefusedError) as refused:
        driver.run(log, record_dispatch(log, channel=MINE))

    assert REASON_THREAD_MAP_MUTATION in str(refused.value)
    assert raw(log) == before


def test_accepting_a_thread_conclusion_dispatches_the_grill_master_carrying_it(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a thread whose last turn is its agent's conclusion
    When the human folds the thread
    Then the thread is folded and the backend dispatches the grill-master on the
         map channel, carrying that conclusion in the context and in the prompt.

    Routing it this way is what keeps the grill-master's own conversational
    context informed of how the map evolves. A conclusion nobody hands it is a
    board that moves behind the agent reasoning about it.
    """
    board(client, log.epoch)
    say(client, log.epoch, MINE, MINE_CONCLUDED)
    driver, transport = fast_tier("Nothing on the board changes.")
    lane = Lane(log, driver)

    run_turns(lane, turn_event(THREAD_FOLD_KIND, MINE, "fold-mine"))

    dispatched = contexts(sorted((log.directory / "dispatches").glob("*.json")))[-1]
    assert (dispatched.agent, dispatched.channel) == (GRILL_MASTER, MAP_CHANNEL)
    assert dispatched.conclusion is not None
    assert (dispatched.conclusion.thread, dispatched.conclusion.text) == (MINE, MINE_CONCLUDED)
    assert MINE_CONCLUDED in transport.calls[0]["prompt"]
    folded = next(thread for thread in fold(log.epoch, log.entries()).threads if thread.id == MINE)
    assert folded.state == "folded"


def test_the_map_mutation_a_folded_conclusion_produces_is_the_grill_masters(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a folded thread conclusion the grill-master decides to apply
    When its turn runs
    Then the mutation is on the board, and the entry carrying it is the
         grill-master's own on the map channel.

    The attribution is the point. The thread agent reached the conclusion and
    the grill-master authored the change, and the log has to say which is which
    for the next turn to reason from it.
    """
    board(client, log.epoch)
    say(client, log.epoch, MINE, MINE_CONCLUDED)
    driver, _ = fast_tier(
        mutation_reply("Folded: retention now bounds the store.", "Store, for 30d")
    )
    lane = Lane(log, driver)

    run_turns(lane, turn_event(THREAD_FOLD_KIND, MINE, "fold-mine"))

    assert errors(log) == []
    applied = [entry for entry in log.entries() if entry.kind == "fold"]
    assert [(entry.actor, entry.channel) for entry in applied] == [("grill-master", MAP_CHANNEL)]
    node = next(
        one for one in to_image1(fold(log.epoch, log.entries())).decisions if one.id == NODE
    )
    assert node.title == "Store, for 30d"
    assert not [
        entry
        for entry in log.entries()
        if entry.actor == "thread-agent" and entry.kind in MAP_MUTATION_KINDS
    ]


def test_a_conclusion_folded_as_context_only_leaves_the_board_alone_and_says_so(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a folded thread conclusion the grill-master takes as context only
    When its turn runs
    Then no decision moved, no map mutation was appended, and the grill-master's
         reply is in the log saying so.

    Some conclusions fold as context or notification only. The grill-master
    decides which, and a backend that inferred it from the shape of a reply
    would be making that decision on its behalf.
    """
    board(client, log.epoch)
    say(client, log.epoch, MINE, MINE_CONCLUDED)
    said = "Nothing on the board changes: retention was already priced into the store answer."
    driver, _ = fast_tier(said)
    lane = Lane(log, driver)
    before = fold(log.epoch, log.entries()).decisions
    cursor = log.seq

    run_turns(lane, turn_event(THREAD_FOLD_KIND, MINE, "fold-mine"))

    image = fold(log.epoch, log.entries())
    assert image.decisions == before
    assert [entry.kind for entry in log.entries() if entry.kind == "fold"] == []
    spoken = [entry for entry in log.entries_after(cursor) if entry.actor == GRILL_MASTER]
    assert [(entry.kind, entry.channel) for entry in spoken] == [("informational", MAP_CHANNEL)]
    assert spoken[0].payload["text"] == said


def test_a_reply_that_is_not_the_update_shape_is_recorded_as_what_it_said(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a grill-master reply that is JSON but not the update shape
    When its turn runs
    Then it is recorded as prose rather than mined for updates.

    Guessing at a half-shaped object would author board changes out of a reply
    that never asked for any -- the one failure the receipt vocabulary cannot
    surface, because the write succeeded.
    """
    board(client, log.epoch)
    said = json.dumps({"thoughts": "not the contract", "updates": "not a list"})
    driver, _ = fast_tier(said)
    cursor = log.seq

    driver.run(log, record_dispatch(log))

    spoken = [entry for entry in log.entries_after(cursor) if entry.actor == GRILL_MASTER]
    assert [entry.kind for entry in spoken] == ["informational"]
    assert spoken[0].payload["text"] == said


def test_the_image_schemas_do_not_grow_the_projections_stub_fields() -> None:
    """
    Given the strict image schema
    When its thread shape is read
    Then it carries no conclusion field.

    The projection is its own model. Image 2 growing a stub field would put a
    thread's conclusion in the board's own record, where a second reader would
    eventually disagree with the thread's turns about what it concluded.
    """
    assert "conclusion" not in Image2.model_fields
    assert "conclusion" not in Thread.model_fields
    assert Image2.model_fields["threads"].annotation == list[Thread]
