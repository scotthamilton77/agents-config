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
authors map mutations and a conclusion nobody hands it changes nothing. The lane
follows that routing rather than the click: the human's gesture is acknowledged
where they made it, and the turn it schedules is announced, tiered and closed on
the channel that turn actually runs on.

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
from grillui.projector import supersede_conflicts
from grillui.schemas import (
    ANSWERABLE_KINDS,
    MAP_CHANNEL,
    STATUS_PHASE_ACCEPTED,
    STATUS_PHASE_COMPOSING,
    STATUS_PHASE_ERROR,
    STATUS_PHASE_REPLIED,
    THREAD_FOLD_KIND,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from grillui.log import SessionLog
    from grillui.schemas import EventSubmission, Receipt, SupersedeConflict


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

    `conflict` and `reassess` are the two turns no gesture on a channel asked
    for. A conflict turn is also where the recursion stops: it does not look for
    conflicts of its own, so handing one back can never chain into a second.
    """

    channel: str
    concluding: str | None = None
    conflict: SupersedeConflict | None = None
    reassess: bool = False


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
        self._doctor = False

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
                # The two entries are addressed to two different channels, and
                # for every gesture but a fold they are the same one. `accepted`
                # answers the human's gesture, so it belongs where they made it.
                # `composing` says who owes a turn and names the tier taking it,
                # so it belongs on the channel that turn runs on -- the same
                # channel its `replied` or `error` will close, and the same one
                # whose expert mode chose the tier being named.
                self.log.emit_status(
                    STATUS_PHASE_ACCEPTED,
                    f"{event.kind} from the human accepted on channel {event.channel!r}",
                    event.channel,
                )
                self.log.emit_status(
                    STATUS_PHASE_COMPOSING,
                    f"the {driver.tier!r} tier is composing a reply",
                    turn.channel,
                    tier=driver.tier,
                )
        return receipts, [self._schedule(driver, turn) for driver, turn in turns]

    @property
    def doctor_outstanding(self) -> bool:
        """Whether a map-doctor turn is in flight.

        What the page holds the board immutable against. It is memory rather
        than log state on purpose: a backend that died mid-doctor took the
        dispatch with it, and a board that stayed frozen across that restart
        would be frozen waiting for an answer nobody is composing.
        """
        return self._doctor

    def call_doctor(self) -> threading.Thread | None:
        """Send the grill-master over the whole board and the pending queue.

        The escape hatch when superseding has not been enough: one turn, told to
        reassess everything, with the board held immutable by the page until it
        answers. A second call while one is outstanding is not a second turn --
        the human clicking twice must not put two reassessments on one chain.

        With no tier attached there is nothing to dispatch, and saying so by
        returning nothing is what keeps the page from freezing the board against
        an answer that is never coming.
        """
        if self.driver is None or self._doctor:
            return None
        self._doctor = True
        driver = self.tier_for(MAP_CHANNEL, self.driver)
        return self._schedule(driver, Turn(MAP_CHANNEL, reassess=True))

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
        and the lane's error phase is what they get instead. A doctor turn
        releases the board on the way out whichever way it went, since a board
        frozen against a turn that failed is frozen for good.
        """
        try:
            standing = self._conflicts() if self._watching(turn) else []
            dispatch = record_dispatch(
                self.log,
                channel=turn.channel,
                concluding=turn.concluding,
                conflict=turn.conflict,
                reassess=turn.reassess,
            )
            driver.run(self.log, dispatch)
            if self._watching(turn):
                self._hand_back(driver, standing)
            self.log.emit_status(
                STATUS_PHASE_REPLIED, f"the {driver.tier!r} tier's turn is over", turn.channel
            )
        except Exception as error:
            self.log.emit_status(
                STATUS_PHASE_ERROR, f"the {driver.tier!r} tier failed: {error!r}", turn.channel
            )
        finally:
            if turn.reassess:
                self._doctor = False

    @staticmethod
    def _watching(turn: Turn) -> bool:
        """Whether this turn's reply could raise a conflict to hand back.

        Only a map turn can: a pending notice is the grill-master's, and an
        author may only supersede its own. A conflict turn is excluded because
        it is the hand-back -- one that looked again would find the conflict it
        was sent about still in the log and send itself forever.
        """
        return turn.channel == MAP_CHANNEL and turn.conflict is None

    def _conflicts(self) -> list[SupersedeConflict]:
        return supersede_conflicts(self.log.entries())

    def _hand_back(self, driver: TurnDriver, standing: Sequence[SupersedeConflict]) -> None:
        """Give the grill-master back a withdrawal the human got in front of.

        Only what this turn raised: the conflicts standing before it were
        already handed back when they appeared, and a caller that re-sent them
        would be asking the grill-master to reconcile the same disagreement
        once per turn for the rest of the session. Nothing on the board moves
        here -- the reconciliation is the agent's next reply, authored the way
        every other map mutation is.
        """
        known = {one.update.id for one in standing}
        for conflict in self._conflicts():
            if conflict.update.id not in known:
                self._take_turn(driver, Turn(MAP_CHANNEL, conflict=conflict))
