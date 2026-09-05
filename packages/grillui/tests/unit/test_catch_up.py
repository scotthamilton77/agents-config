"""A thread picked back up after being set aside, and the chain it does not resume.

Two facts, and they are one fact: the interval moved a decision, or it did not.
Where it did, the reopening dispatch carries the catch-up and the heavy tier
opens a cold chain; where it did not, there is no catch-up and the chain resumes
as on any other turn.

What counts as a move is measured here the way the projector measures it -- by
folding the log through each entry of the interval and looking at image 1's
decisions -- rather than by naming kinds. The fixture below is built so that a
kind list would get it wrong: its interval carries thread turns, a status entry,
a park, a thread fold and an agent's update left waiting in the human's queue,
every one of which says it changed the map and none of which did.

Nothing here reaches a network or a model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from conftest import ScriptedCli, ScriptedFast, handoff_doc, run_turns, write_handoff

from grillui.dispatch import record_dispatch
from grillui.drivers import RESUME_FILE, FastDriver, HeavyDriver
from grillui.lane import Lane
from grillui.projector import fold, to_image1
from grillui.schemas import (
    APPLY_KIND,
    MAP_CHANNEL,
    STATUS_KIND,
    STATUS_PHASE_COMPOSING,
    THREAD_CLOSE_KIND,
    THREAD_FOLD_KIND,
    THREAD_PARK_KIND,
    DispatchContext,
    EventSubmission,
)
from grillui.session import open_session
from grillui.tiers import TierConfig

if TYPE_CHECKING:
    from grillui.log import SessionLog

NODE = "d1"
MINE = "t-mine"
OTHER = "t-other"
DONE = "t-done"

# Every turn says something nothing else says, so "in full" is checkable by
# looking for the words in the prompt the driver built.
MINE_ASKED = "mine: how long is a session kept?"
MINE_ANSWERED = "mine: thirty days, then archive."
MINE_AGAIN = "mine: and what archives it?"
OTHER_SAID = "other: on restart, and never otherwise."
DONE_CONCLUDED = "done: name the files for the session id."

REVISED_BODY = "Pick the storage layer, given a thirty-day retention."
REVISE_WHY = "retention changes what the store has to hold"
REPLY = "The archive is out of scope for this thread."

OLD_CHAIN = "chain-before-the-thread-was-closed"
MAP_CHAIN = "the-map-s-own-chain"


# --- the session ---------------------------------------------------------------


def submit(log: SessionLog, kind: str, key: str, /, *, actor: str, channel: str, **payload: Any):
    receipt = log.submit([turn(kind, key, actor=actor, channel=channel, **payload)], log.epoch)[0]
    assert receipt.status == "accepted", receipt
    return receipt


def turn(kind: str, key: str, /, *, actor: str, channel: str, **payload: Any) -> EventSubmission:
    return EventSubmission(
        kind=kind, actor=actor, channel=channel, idempotency_key=key, payload=payload
    )


def said(text: str, who: str = "thread-agent") -> dict[str, Any]:
    return {"turns": [{"who": who, "text": text}]}


def set_aside(session_dir: Path) -> SessionLog:
    """One decision the human settled, three threads, and the one that matters
    closed after asking its question."""
    write_handoff(session_dir, handoff_doc())
    log = open_session(session_dir)
    for thread, opening in ((MINE, MINE_ASKED), (OTHER, "other: when is the log compacted?")):
        submit(
            log,
            "thread-created",
            f"open-{thread}",
            actor="human",
            channel=thread,
            decision=NODE,
            kind="mandate",
            title=thread,
            requires_action=True,
            **said(opening, "human"),
        )
    submit(
        log,
        "thread-turn",
        "mine-answered",
        actor="thread-agent",
        channel=MINE,
        **said(MINE_ANSWERED),
    )
    submit(
        log,
        "thread-created",
        f"open-{DONE}",
        actor="human",
        channel=DONE,
        decision=NODE,
        kind="mandate",
        title=DONE,
        requires_action=True,
        **said("done: what are the files called?", "human"),
    )
    # Settled by the human, which is what makes the agent's later revise a
    # proposal that waits rather than an update that lands.
    submit(
        log,
        "answer",
        "answer-node",
        actor="human",
        channel=MAP_CHANNEL,
        target=NODE,
        answer={"option": "a", "text": "an append-only log"},
        why="the audit trail is the point",
    )
    submit(log, THREAD_CLOSE_KIND, "close-mine", actor="human", channel=MINE)
    return log


def interval(log: SessionLog, *, apply_it: bool) -> None:
    """Everything that happened while the thread was away.

    Only the apply moves a decision. The rest -- two thread turns, a status
    entry, a park, a thread fold, and the agent's revise waiting in the queue --
    is the board looking busy and the map standing still.
    """
    submit(
        log, "thread-turn", "other-said", actor="thread-agent", channel=OTHER, **said(OTHER_SAID)
    )
    log.emit_status(STATUS_PHASE_COMPOSING, "the 'fast' tier is composing", OTHER)
    submit(log, THREAD_PARK_KIND, "park-other", actor="human", channel=OTHER)
    submit(
        log, "thread-turn", "done-said", actor="thread-agent", channel=DONE, **said(DONE_CONCLUDED)
    )
    submit(log, THREAD_FOLD_KIND, "fold-done", actor="human", channel=DONE)
    submit(
        log,
        "revise",
        "revise-node",
        actor="grill-master",
        channel=MAP_CHANNEL,
        target=NODE,
        body=REVISED_BODY,
        why=REVISE_WHY,
    )
    if apply_it:
        submit(
            log,
            APPLY_KIND,
            "apply-revise",
            actor="human",
            channel=MAP_CHANNEL,
            pending=["revise-node"],
        )


def reopening() -> EventSubmission:
    """The human's turn picking the thread back up, which is what closes the
    interval and what this dispatch is for."""
    return turn(
        "thread-turn", "mine-again", actor="human", channel=MINE, **said(MINE_AGAIN, "human")
    )


def reopened(session_dir: Path, *, moved: bool) -> SessionLog:
    """A set-aside thread, an interval that did or did not move a decision, and
    the human's turn picking the thread back up."""
    log = set_aside(session_dir)
    interval(log, apply_it=moved)
    log.submit([reopening()], log.epoch)
    return log


def caught_up(log: SessionLog, channel: str = MINE) -> list[dict[str, Any]]:
    context = DispatchContext.model_validate_json(
        record_dispatch(log, channel=channel).read_text(encoding="utf-8")
    )
    return [item.model_dump() for item in context.catch_up]


def seq_of(log: SessionLog, kind: str) -> int:
    return next(entry.seq for entry in log.entries() if entry.kind == kind)


def chains(session_dir: Path) -> dict[str, str]:
    return json.loads((session_dir / RESUME_FILE).read_text(encoding="utf-8"))


def held(session_dir: Path, **chain: str) -> None:
    (session_dir / RESUME_FILE).write_text(json.dumps(chain), encoding="utf-8")


def take_heavy_turn(log: SessionLog, cli: Any, channel: str = MINE) -> None:
    HeavyDriver(TierConfig(), cli).run(log, record_dispatch(log, channel=channel))


@dataclass
class SilentCli:
    """A CLI turn that answers and names no chain, which is the case a cold
    turn must not fall back out of."""

    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: list[str], _directory: Path, /) -> str:
        self.calls.append(list(argv))
        return json.dumps({"result": REPLY})


@dataclass
class ThreadReplyDriver:
    """A tier that answers on the channel it was dispatched for, the way a
    thread agent does."""

    tier: str = "fast"
    contexts: list[DispatchContext] = field(default_factory=list)

    def run(self, log: SessionLog, dispatch: Path, /) -> None:
        context = DispatchContext.model_validate_json(dispatch.read_text(encoding="utf-8"))
        self.contexts.append(context)
        submit(
            log,
            "thread-turn",
            f"reply-{len(log.entries())}",
            actor="thread-agent",
            channel=context.channel,
            **said(REPLY),
        )


# --- GUI-A75: what the catch-up is, and what it is not -------------------------


def test_an_interval_that_moved_no_decision_yields_no_catch_up(session_dir: Path) -> None:
    """
    Given a thread closed and then reopened, across an interval carrying thread
    turns, a status entry, a park, a thread fold and an agent's update left
    waiting in the human's queue
    When the reopening dispatch is recorded
    Then it carries no catch-up.

    None of those entries moved a decision, whatever its kind says it does. A
    catch-up assembled from a list of kinds would report five events here and
    describe a board the human is not looking at; folding the log through each
    entry and reading image 1's decisions reports none, which is the truth.
    """
    log = reopened(session_dir, moved=False)

    assert caught_up(log) == []


def test_applying_that_queued_update_inside_the_interval_is_one_entry_at_the_apply(
    session_dir: Path,
) -> None:
    """
    Given the same interval, with the queued update applied inside it
    When the reopening dispatch is recorded
    Then the catch-up is exactly one entry, naming the decision the apply moved,
         at the sequence of the apply and not of the entry that queued it,
         carrying the kind and the rationale the log holds for it.

    A proposal that waits changes nothing on the map: it is a map event at the
    `apply` that lands it, and reporting it at the sequence it was authored at
    would tell the thread the board moved at a moment it did not.
    """
    log = reopened(session_dir, moved=True)

    assert caught_up(log) == [
        {
            "seq": seq_of(log, APPLY_KIND),
            "kind": "revise",
            "target": NODE,
            "why": REVISE_WHY,
        }
    ]
    assert seq_of(log, APPLY_KIND) > seq_of(log, "revise")


def test_a_second_turn_on_the_reopened_thread_is_caught_up_again_by_nothing(
    session_dir: Path,
) -> None:
    """
    Given a thread already reopened and caught up
    When the human takes another turn on it
    Then that dispatch carries no catch-up.

    The interval runs from the set-aside gesture to the turn that reopens the
    thread, and it closes there. A catch-up riding every later turn would
    re-tell the thread what it was told when it came back.
    """
    log = reopened(session_dir, moved=True)
    assert caught_up(log) != []

    submit(
        log,
        "thread-turn",
        "mine-third",
        actor="human",
        channel=MINE,
        **said("mine: and the archive format?", "human"),
    )

    assert caught_up(log) == []


# --- GUI-A76: the cold chain ---------------------------------------------------


def test_a_moved_interval_opens_the_heavy_turn_cold_with_the_thread_in_full(
    session_dir: Path,
) -> None:
    """
    Given a reopened thread whose interval moved a decision, on a channel
    holding a chain from before it was set aside
    When the heavy tier takes that turn
    Then it is invoked with no resume identifier, its prompt carries the
         thread's turns in full beside the catch-up, and the session id it
         returns -- and no earlier one -- becomes the chain the next turn
         resumes, with every other channel's chain left as it was.

    The accumulated reasoning of the older chain was formed against a board that
    has since moved, and a snapshot crossing whole on this turn does not correct
    it: a chain already carrying a dozen older snapshots has no reason to read
    the newest as a correction rather than as more of the same.
    """
    log = reopened(session_dir, moved=True)
    held(session_dir, **{MAP_CHANNEL: MAP_CHAIN, MINE: OLD_CHAIN})
    cli = ScriptedCli(session_id="chain-after-the-catch-up")

    take_heavy_turn(log, cli)

    assert "--resume" not in cli.calls[0]
    assert OLD_CHAIN not in cli.calls[0]
    prompt = cli.calls[0][-1]
    for spoken in (MINE_ASKED, MINE_ANSWERED, MINE_AGAIN):
        assert spoken in prompt
    assert REVISE_WHY in prompt
    assert chains(session_dir) == {
        MAP_CHANNEL: MAP_CHAIN,
        MINE: "chain-after-the-catch-up",
    }


def test_a_cold_turn_naming_no_chain_leaves_the_channel_holding_none(
    session_dir: Path,
) -> None:
    """
    Given the same cold turn, whose driver returns no session id
    When it is taken
    Then the channel holds no resume record at all, and the other channel's is
         untouched.

    The record the cold turn set aside is discarded when the turn opens rather
    than kept for a null to fall back on: falling back would resume the very
    chain the catch-up exists to get away from.
    """
    log = reopened(session_dir, moved=True)
    held(session_dir, **{MAP_CHANNEL: MAP_CHAIN, MINE: OLD_CHAIN})

    take_heavy_turn(log, SilentCli())

    assert chains(session_dir) == {MAP_CHANNEL: MAP_CHAIN}


def test_the_fast_tier_is_told_what_moved_as_well(session_dir: Path) -> None:
    """
    Given the same reopened thread
    When the fast tier takes that turn
    Then its prompt carries the catch-up too.

    Whichever tier takes the reopening turn is the tier that has to know the
    board moved: the fast tier's context is rebuilt from the fold every
    dispatch, and this section is what tells it what changed rather than what
    is now true.
    """
    log = reopened(session_dir, moved=True)
    transport = ScriptedFast(reply=REPLY)

    FastDriver(TierConfig(), transport).run(log, record_dispatch(log, channel=MINE))

    assert REVISE_WHY in transport.calls[0]["prompt"]


# --- GUI-A77: an unchanged interval is an ordinary turn ------------------------


def test_an_unchanged_interval_resumes_the_chain_the_channel_already_held(
    session_dir: Path,
) -> None:
    """
    Given a reopened thread whose interval moved no decision
    When the heavy tier takes that turn
    Then the dispatch carries no catch-up and the turn resumes the identifier
         the channel already held, exactly as on a thread nobody set aside.

    Opening a cold chain here is refused: it pays the cold-start tax to fix a
    chain that is not stale, and forfeits the resume discount on every thread
    turn in the session.
    """
    log = reopened(session_dir, moved=False)
    held(session_dir, **{MAP_CHANNEL: MAP_CHAIN, MINE: OLD_CHAIN})
    cli = ScriptedCli(session_id="chain-carried-on")
    assert caught_up(log) == []

    take_heavy_turn(log, cli)

    assert cli.calls[0][cli.calls[0].index("--resume") + 1] == OLD_CHAIN
    assert REVISE_WHY not in cli.calls[0][-1]
    assert chains(session_dir) == {MAP_CHANNEL: MAP_CHAIN, MINE: "chain-carried-on"}


# --- GUI-A78: the human is told nothing ----------------------------------------


def test_reopening_a_thread_raises_nothing_to_the_human(session_dir: Path) -> None:
    """
    Given a thread set aside across an interval that moved a decision
    When the human's turn reopens it and the lane runs that turn
    Then nothing is raised: no notification joins the queue, the board projects
         no element it did not project before, and the log grows by the
         reopening turn, its status entries and the reply alone.

    The catch-up is dispatch context and nothing else. A board element or a
    notification announcing it would make the human read a message about their
    own gesture, on a board that has not changed.
    """
    log = set_aside(session_dir)
    interval(log, apply_it=True)
    before = to_image1(fold(log.epoch, log.entries()))
    kinds_before = [entry.kind for entry in log.entries()]
    driver = ThreadReplyDriver()

    run_turns(Lane(log, driver), reopening())

    assert [item.model_dump() for item in driver.contexts[0].catch_up] != []
    grew = log.entries()[len(kinds_before) :]
    assert [(one.actor, one.kind) for one in grew if one.kind != STATUS_KIND] == [
        ("human", "thread-turn"),
        ("thread-agent", "thread-turn"),
    ]
    after = to_image1(fold(log.epoch, log.entries()))
    assert after.pending == before.pending == []
    assert after.decisions == before.decisions
    assert after.frontier == before.frontier
    assert after.settled == before.settled
    assert [one.id for one in after.threads] == [one.id for one in before.threads]
