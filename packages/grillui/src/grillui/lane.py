"""The status lane, the answerability decision, and the seam a tier plugs into.

Four rules meet here.

**The lane is mechanical.** The instant a human turn is accepted, and inside the
same lock that appended it, the backend emits `accepted` and then `composing`
naming the tier about to take the turn -- before one byte leaves the process.
That is 0-1 ms against a second for a fast reply and half a minute for a heavy
one, and it is why the page can show that a message landed rather than showing
nothing until a model gets around to answering. No status entry is ever produced
by a model and no code path here waits on one, including the failure path: an
agent that cannot be reached at all surfaces as an error phase in milliseconds
rather than as an unbounded silence.

**Only a human turn is owed a reply.** The page also opens agent-authored
threads -- a mandate thread whose only turn is the agent's. Those are recorded
and left alone: no lane entry and no dispatch, so the backend never answers
itself. Answerability is decided here and acceptance is decided by the appender;
an agent-authored thread is fully accepted and simply not answered.

**A gesture is answered by whoever may act on it.** Every turn is answered on
the channel it was spoken on, with one exception: folding a thread is answered
by the grill-master on the map, because the grill-master is the only agent that
authors map mutations and a conclusion nobody hands it changes nothing.

**The tier is a property of the channel, not of the session.** Each turn's
driver is chosen for the channel it is about to run on, so escalating one thread
leaves every other thread and the map where the human left them. Threads take
their turns concurrently with each other and with the map; only the heavy tier's
own single-flight rule serialises anything, and it serialises the resume chain
rather than the session.

The driver seam is the whole of what a tier has to implement. A turn is one
invocation: the driver runs, says what it has to say into the log, and returns.
There is no polling loop and no resident agent process, because the orchestrator
is what decides when any agent gets a turn. The invocation happens off the
append lock and off the request path, so a slow or hung tier delays nothing the
human is waiting on -- their write is already durable and already answered with
a receipt by the time the driver starts.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, NamedTuple, Protocol

from grillui.dispatch import record_dispatch
from grillui.escalation import in_expert_mode
from grillui.schemas import (
    ANSWERABLE_KINDS,
    MAP_CHANNEL,
    STATUS_PHASE_ACCEPTED,
    STATUS_PHASE_COMPOSING,
    STATUS_PHASE_ERROR,
    THREAD_FOLD_KIND,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from grillui.log import SessionLog
    from grillui.schemas import EventSubmission, Receipt


class AgentUnreachableError(RuntimeError):
    """A tier that could not be reached at all.

    Distinct from a tier that answered badly: there is no turn to salvage and
    nothing to wait for, so the lane says so immediately instead of leaving the
    human watching a timer that will never stop.
    """

    def __init__(self, tier: str) -> None:
        super().__init__(f"the {tier!r} tier could not be reached")


class TurnDriver(Protocol):
    """One tier's way of taking one turn.

    `tier` is what the lane names in its `composing` entry, so it is the string
    a human reads while waiting. `run` is given the recorded dispatch context --
    image 2 whole, as the agent got it -- and the log to say its piece into. It
    is called once per turn, from a thread of its own, and returns when the turn
    is over.
    """

    tier: str

    def run(self, log: SessionLog, dispatch: Path, /) -> None: ...


class UnreachableDriver:
    """A tier with nothing behind it.

    The stub the error path is proved against, and the shape any real driver's
    transport failure takes: raising out of `run` is how a driver reports that
    it never got a turn at all.
    """

    tier = "unreachable"

    def run(self, _log: SessionLog, _dispatch: Path, /) -> None:
        raise AgentUnreachableError(self.tier)


class Turn(NamedTuple):
    """One turn to be taken: whose channel it is, and what it is about.

    The channel is the dispatch's, which is not always the channel the gesture
    arrived on. Folding a thread is a gesture the human makes in the thread and
    the grill-master answers on the map, because the grill-master is the only
    agent that authors map mutations -- and it cannot author one it was never
    told about.
    """

    channel: str
    concluding: str | None = None


def turn_of(event: EventSubmission) -> Turn:
    """Which agent owes this gesture a turn."""
    if event.kind == THREAD_FOLD_KIND:
        return Turn(MAP_CHANNEL, concluding=event.channel)
    return Turn(event.channel)


def is_answerable(event: EventSubmission) -> bool:
    """Whether this event is a turn the backend owes a reply to.

    Both halves are load-bearing. The kind test excludes gestures that are not
    conversation -- ending a session is a human act that no agent answers. The
    actor test is what keeps the backend from answering itself.
    """
    return event.actor == "human" and event.kind in ANSWERABLE_KINDS


class Lane:
    """The status lane over one session log, and the driver it schedules.

    A lane with no driver has no agent attached: nothing is composing, so it
    emits nothing and dispatches nothing. That is the state the backend is in
    until a tier is configured, and it is deliberately not disguised as a
    working one.

    `expert` is the tier a channel the human has escalated takes its turns on,
    and the choice is made per channel: escalating one thread must leave every
    other where it was, so the tier cannot be a property of the session or of
    the driver. A lane with no expert tier configured never escalates anything.
    """

    def __init__(
        self, log: SessionLog, driver: TurnDriver | None = None, expert: TurnDriver | None = None
    ) -> None:
        self.log = log
        self.driver = driver
        self.expert = expert

    def tier_for(self, channel: str, driver: TurnDriver) -> TurnDriver:
        """The tier this channel's next turn goes to: the expert one when the
        human has escalated this channel, and the session's own otherwise.

        Named before the `composing` entry is written rather than after, so the
        tier the human is told they are waiting on is the tier that takes the
        turn.
        """
        if self.expert is None:
            return driver
        return self.expert if in_expert_mode(self.log.entries(), channel) else driver

    def accept(
        self, batch: Sequence[EventSubmission], epoch: str
    ) -> tuple[list[Receipt], list[threading.Thread]]:
        """Judge a batch, emit the lane for every human turn in it, and schedule
        each turn's dispatch.

        The receipts are settled and the lane is written before this returns;
        the driver has not been touched. The threads come back so a caller that
        needs to know when a turn finished can wait for it -- nothing in the
        request path does.
        """
        base = self.driver
        receipts: list[Receipt] = []
        turns: list[tuple[TurnDriver, Turn]] = []
        with self.log.appending():
            if base is None:
                return self.log.submit(batch, epoch), []
            # One event at a time under the one lock, so each turn's lane
            # entries land adjacent to the turn they report -- a second turn in
            # the same batch never wedges between a turn and its `accepted`.
            for event in batch:
                receipt = self.log.submit([event], epoch)[0]
                receipts.append(receipt)
                if receipt.status != "accepted" or not is_answerable(event):
                    continue
                turn = turn_of(event)
                # The tier is the dispatched channel's, and it is read after the
                # gesture landed: a turn carrying the human's transfer is itself
                # the escalation, and must not be composed by the tier they just
                # moved off.
                driver = self.tier_for(turn.channel, base)
                turns.append((driver, turn))
                self.log.emit_status(
                    STATUS_PHASE_ACCEPTED,
                    f"{event.kind} from the human accepted on channel {event.channel!r}",
                    event.channel,
                )
                self.log.emit_status(
                    STATUS_PHASE_COMPOSING,
                    f"the {driver.tier!r} tier is composing a reply",
                    event.channel,
                    tier=driver.tier,
                )
        return receipts, [self._schedule(driver, turn) for driver, turn in turns]

    def _schedule(self, driver: TurnDriver, turn: Turn) -> threading.Thread:
        thread = threading.Thread(
            target=self._take_turn,
            args=(driver, turn),
            daemon=True,
            name=f"turn-{turn.channel}",
        )
        thread.start()
        return thread

    def _take_turn(self, driver: TurnDriver, turn: Turn) -> None:
        """One turn, off the lock and off the request path.

        Every failure is caught, whatever it is: the human's write is already
        durable and already answered, so nothing here may escape and turn a
        landed turn into a crashed one. What the human must not get is silence,
        and the lane's error phase is what they get instead.
        """
        try:
            dispatch = record_dispatch(self.log, channel=turn.channel, concluding=turn.concluding)
            driver.run(self.log, dispatch)
        except Exception as error:
            self.log.emit_status(
                STATUS_PHASE_ERROR, f"the {driver.tier!r} tier failed: {error!r}", turn.channel
            )
