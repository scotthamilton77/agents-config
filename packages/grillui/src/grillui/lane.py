"""The status lane, the answerability decision, and the seam a tier plugs into.

Eight rules meet here.

**The lane is mechanical.** The instant a human turn is accepted, and inside the
same lock that appended it, the backend emits `accepted` and then `composing`
naming the tier about to take the turn -- before one byte leaves the process.
That happens in the time it takes to append, against however long the seat
takes to answer, and it is why the page can show that a message landed rather
than showing nothing until a model gets around to answering. No status entry is
ever produced by a model and no code path here waits on one, including the failure path: an
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

**A turn dies with the process that announced it.** The turn is a thread inside
one process, so a backend killed mid-turn leaves a `composing` nothing will ever
close. A successor opening the same directory closes those out on the way in --
the previous tenure's turns are over whatever else is true of them, and a
channel left announced is a waiting clock that counts up for the rest of the
session.

**The tier is a property of the channel, not of the session.** Each turn's
driver is chosen for the channel it is about to run on, so transferring one
thread leaves every other thread and the map where the human left them. Threads
take their turns concurrently with each other and with the map; only the heavy tier's
own single-flight rule serialises anything, and it serialises the resume chain
rather than the session.

**A gesture the board can class is seated before a model is called.** The
judgment classes are closed and each is read off the board at the moment the
turn is scheduled, so a gesture that is one of them is composed by the expert
seat from the start: no first-rung turn is recorded for it, and nothing is
round-tripped through a rung the class already passed over. The `composing`
entry therefore names the seat that actually takes the turn, which is the only
thing the human has to go on while they wait. Classing writes no status entry,
because there is nothing to fall back from -- the next clerical gesture is
first-rung again with no entry to undo.

**Two wordless refusals move the channel; one is noise.** Applying and
dismissing carry no text, so no transcript condition sees them: a dismissal of
a first-rung proposal and a press onto the expert are counted alike, and the
second of them moves the map channel up through the same status entry the
escalation policy writes. One writes nothing, because one is noise. The count
and the entry it writes are both the log's: the count is read off the records
the two signals leave, so it is the session's and survives the backend
being replaced, and the entry is sticky, so a channel already moved is never
moved twice -- and the way back down stays the human's.

**An obligation the board can state is checked, not hoped for.** Where the
answer a turn is replying to named the decisions it puts in question, the reply
is measured against that list in code -- off the turn's own rulings. One that
left a decision unruled is handed up a tier once and asked again, narrowed to
what is left; a second reply that rules on nothing is said to the human as a
notice naming those decisions. A grill-master turn the board would not take
walks the same ladder, its own seat's one retry already spent -- whether what
arrived was not the document at all, or was the document naming something no
board of this session has.
Nothing here writes to the map: the insistence buys another agent turn, and the
human is told when it buys nothing.

**A ruling in flight holds what it rules on, and only one holds each.** A
marked answer starts one impact task per decision it puts in question, opened
on its turn's `composing` entry, and the replay keeps each target off the
frontier until its task ends. A later gesture whose own task would target a
decision already held supersedes the holding task on its `accepted` entry, in
the same hold of the append lock that accepts the gesture, so no batch and no
interleaving can leave two tasks holding one target. The superseded turn runs
on; what it owed on that target is no longer owed, and a result it sends for
it is dropped rather than folded.

The driver seam is the whole of what a tier has to implement. A turn is one
invocation: the driver runs, says what it has to say into the log, and returns
the sequence of the entry it appended -- which is the receipt the coverage check
reads this turn's rulings off, rather than reading them off a window on the log
that another turn's reply can land inside.
There is no polling loop and no resident agent process, because the orchestrator
is what decides when any agent gets a turn. The invocation happens off the
append lock and off the request path, so a slow or hung tier delays nothing the
human is waiting on -- their write is already durable and already answered with
a receipt by the time the driver starts.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

from grillui.dispatch import record_dispatch
from grillui.escalation import (
    ANSWER_KIND,
    INVALIDATE_KIND,
    distrust_count,
    in_expert_mode,
    judgment_class,
    mootness_obligation,
    policy_transferred,
    rulings_of,
    unruled,
)
from grillui.projector import (
    impact_tasks,
    replay,
    supersede_conflicts,
    superseded_targets,
    task_id,
)
from grillui.schemas import (
    ANSWERABLE_KINDS,
    APPLY_KIND,
    DISMISS_KIND,
    IMPACT_MODE,
    MAP_CHANNEL,
    OPENED_KEY,
    PRESSED_KEY,
    STATUS_KIND,
    STATUS_PHASE_ACCEPTED,
    STATUS_PHASE_COMPOSING,
    STATUS_PHASE_ERROR,
    STATUS_PHASE_REPLIED,
    STATUS_PHASE_SUPERSEDED,
    STATUS_PHASE_TRANSFERRED,
    TASKS_KEY,
    THREAD_FOLD_KIND,
    TIER_KEY,
    DispatchContext,
    is_proceed,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from grillui.log import SessionLog
    from grillui.schemas import (
        EventSubmission,
        Image2,
        LogEntry,
        MootnessObligation,
        Receipt,
        SupersedeConflict,
    )


# Enough of a diagnostic to name the fault, not enough to put a prompt or an
# environment into the log: it is read by a human on a status line, and a
# transport that failed with a page of output still failed once.
DIAGNOSTIC_LIMIT = 200

# How many wordless refusals of the first rung it takes to move the channel.
# One is noise -- a proposal the human simply did not want is not a seat that
# cannot do the work -- and the second is the pattern.
DISTRUST_THRESHOLD = 2

# What the lane says when the count is reached. It states the count rather than
# a condition, because that is what fired: unlike a transcript condition there
# is no sentence of the human's to quote back at them.
DISTRUST_MOVED = (
    "the escalation policy moved this channel to the expert tier: "
    "the first-rung seat's turn was refused twice"
)


def bounded(detail: str) -> str:
    """One line of what a transport said, cut to what a status line holds."""
    said = " ".join(detail.split())
    return said if len(said) <= DIAGNOSTIC_LIMIT else said[:DIAGNOSTIC_LIMIT] + "..."


class AgentUnreachableError(RuntimeError):
    """A tier that could not be reached at all.

    Distinct from a tier that answered badly: there is no turn to salvage and
    nothing to wait for, so the lane says so immediately instead of leaving the
    human watching a timer that will never stop.

    `detail` is what the transport said about it, bounded and on one line. A
    tier that exited non-zero, one that timed out, and one that printed a
    stream carrying no turn are three different mornings for whoever reads the
    lane, and collapsing them into one sentence throws away the only evidence
    anybody had.
    """

    def __init__(self, tier: str, detail: str = "") -> None:
        said = f"the {tier!r} tier could not be reached"
        super().__init__(f"{said}: {bounded(detail)}" if detail.strip() else said)


class DocumentRefusedError(RuntimeError):
    """A grill-master turn the board would not take, twice.

    Two faults arrive here and the ladder treats them alike: a reply that never
    came in the shape the board reads, and a document that read but named
    something no board of this session has. Both are a seat that was told what
    was wrong in the words it was refused with and answered no better.

    Distinct from a tier that could not be reached: a seat answered, twice, and
    what it said is unusable. It carries the tier it ended on because the ladder
    moves a refused turn up a rung -- the seat that failed last is the one the
    human is owed the name of, and it is not always the one the turn started on.
    """

    def __init__(self, tier: str, detail: str) -> None:
        super().__init__(f"the {tier!r} tier's turn did not reach the board: {detail}")
        self.tier = tier
        self.detail = detail


class TurnDriver(Protocol):
    """One tier's way of taking one turn.

    `tier` is what the lane names in its `composing` entry, so it is the string
    a human reads while waiting. `run` is given the recorded dispatch context --
    image 2 whole, as the agent got it -- and the log to say its piece into. It
    is called once per turn, from a thread of its own, and returns when the turn
    is over.

    What it returns is where its own turn landed: the sequence of the entry it
    appended, or nothing where it appended none. The obligation check reads this
    turn's rulings off that one entry, so a driver that appends and reports
    nothing is a turn credited with nothing -- which is the safe direction to be
    wrong in, since it costs an expert turn rather than discharging an
    obligation nobody ruled on.
    """

    tier: str

    def run(self, log: SessionLog, dispatch: Path, /) -> int | None: ...


class UnreachableDriver:
    """A tier with nothing behind it.

    The stub the error path is proved against, and the shape any real driver's
    transport failure takes: raising out of `run` is how a driver reports that
    it never got a turn at all.
    """

    tier = "unreachable"

    def run(self, _log: SessionLog, _dispatch: Path, /) -> int | None:
        raise AgentUnreachableError(self.tier)


class _Pressed(NamedTuple):
    """What one turn came back as: why the board would not take it, and where it
    landed.

    `refusal` may be nothing, because three outcomes have to be told apart and
    two of them are absences: the seat was not reached at all, the seat answered
    and its document was refused, and the seat answered properly. Collapsing the
    first two loses the distinction between a turn to fall back from and a turn
    to end the ladder on.

    `spoke` is the sequence of the entry this turn appended, and nothing where it
    appended none. It is what the coverage check correlates against, so it must
    be the driver's own receipt and never a position the lane read off the log
    around the turn.
    """

    refusal: str | None
    spoke: int | None = None


def _run(driver: TurnDriver, log: SessionLog, dispatch: Path) -> _Pressed:
    """One turn, with a refused document handed back rather than raised.

    A document that will not validate is not the end of the turn -- there is a
    rung above, and the ladder is the caller's to walk -- so it comes back as
    the fault it is. Every other failure still raises: a seat that could not be
    reached has no turn to press on.

    A refused turn appended nothing, so it names no entry: what the ladder does
    next is decided by the fault, and the coverage read never runs on it.
    """
    try:
        return _Pressed(None, driver.run(log, dispatch))
    except DocumentRefusedError as error:
        return _Pressed(error.detail)


def _lost(tier: str) -> str:
    """What the human is told when a turn was taken and nothing came of it.

    The seat's own bytes are deliberately not quoted at them: a reply the board
    could not read is not made readable by printing it, and what they can act on
    is that the gesture went unanswered.
    """
    return (
        f"The {tier!r} tier answered in a shape the board cannot read, twice, so nothing was "
        f"taken from its turn. Ask again, or ask on the map thread."
    )


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

    `proceed` is the human asking the expert to take a thread up as it stands,
    which names the seat whatever the channel's mode is.

    `tasks` is the ids of the impact tasks this turn's gesture started, which
    the turn's closing entry ends. `opened` is the sequence of the turn's own
    announcement, which that closing entry names.

    `mootness` is what the gesture this turn was scheduled for owes the rest of
    the board, read when it was scheduled and carried here rather than derived
    again when the turn runs. The board is mutable and the turn runs later: an
    agent reply landing on the map in between closes the window the obligation
    is read from, so a turn deriving it again would be handed nothing -- or the
    next gesture's obligation instead of its own.
    """

    channel: str
    concluding: str | None = None
    conflict: SupersedeConflict | None = None
    reassess: bool = False
    mootness: MootnessObligation | None = None
    proceed: bool = False
    tasks: tuple[str, ...] = ()
    opened: int | None = None


def turn_of(event: EventSubmission) -> Turn:
    """Which agent owes this gesture a turn."""
    if event.kind == THREAD_FOLD_KIND:
        return Turn(MAP_CHANNEL, concluding=event.channel)
    return Turn(event.channel, proceed=is_proceed(event))


def is_answerable(event: EventSubmission) -> bool:
    """Whether this event is a turn the backend owes a reply to.

    Both halves are load-bearing. The kind test excludes gestures that are not
    conversation -- ending a session is a human act that no agent answers. The
    actor test is what keeps the backend from answering itself.
    """
    return event.actor == "human" and event.kind in ANSWERABLE_KINDS


def _dismisses_on_the_map(event: EventSubmission) -> bool:
    """Whether this gesture is the human ending a queue entry on the map.

    The one gesture there that can be a wordless refusal of the first rung.
    Applying is agreement, and every other gesture the human makes on the map
    carries text a transcript condition already reads. Whether a given dismissal
    is that refusal is not asked here: this says only that the count has
    something new to read.
    """
    return event.actor == "human" and event.kind == DISMISS_KIND and event.channel == MAP_CHANNEL


def open_announcements(entries: Sequence[LogEntry]) -> list[LogEntry]:
    """Every `composing` entry that opened a turn no `replied` or `error` closed.

    A closing entry names the announcement it closes, because map turns run
    concurrently and the latest announcement on the channel is not always the
    turn that ended. A hand-up's announcement opens no turn of its own: the
    turn it continues is closed once. A closing entry that names nothing was
    written when a channel took one turn at a time, and closes every
    announcement open on its channel.
    """
    opened: dict[int, LogEntry] = {}
    for entry in entries:
        if entry.kind != STATUS_KIND:
            continue
        phase = entry.payload.get("phase")
        if phase == STATUS_PHASE_COMPOSING and not entry.payload.get(PRESSED_KEY):
            opened[entry.seq] = entry
        elif phase in (STATUS_PHASE_REPLIED, STATUS_PHASE_ERROR):
            closes = entry.payload.get(OPENED_KEY)
            # A closing entry only ever closes a turn on its own channel, so one
            # naming another channel's announcement closes nothing.
            ended = [
                seq
                for seq, one in opened.items()
                if one.channel == entry.channel and (not isinstance(closes, int) or seq == closes)
            ]
            for seq in ended:
                opened.pop(seq, None)
    return list(opened.values())


def unclosed_turns(entries: Sequence[LogEntry]) -> dict[str, LogEntry]:
    """The latest unclosed announcement on each channel still owed a turn."""
    return {one.channel: one for one in open_announcements(entries)}


def close_dead_turns(log: SessionLog) -> None:
    """Close out every turn a previous tenure announced and never answered.

    A turn is a thread inside one process, so a process that died mid-turn took
    the turn with it: nothing is composing, and nothing will ever write the
    `replied` that turn owed. Left alone, the channel reads as owing a reply for
    the rest of the session and the human watches a clock that counts up
    forever.

    Only a prior epoch's turn is closed. A turn this tenure announced is live,
    and the driver taking it will close the lane itself.

    Each dead turn gets a closing entry of its own, naming its announcement,
    and every impact task that turn left live fails on it. A failed task still
    holds its decision, so the board shows the same wait it showed before the
    restart; what changes is that nobody reads it as a ruling still coming.
    """
    entries = log.entries()
    live = impact_tasks(entries)
    for opened in open_announcements(entries):
        if opened.epoch == log.epoch:
            continue
        tier = opened.payload.get(TIER_KEY)
        whose = f"the {tier!r} tier's turn" if isinstance(tier, str) else "the turn"
        carried = opened.payload.get(TASKS_KEY)
        dead = [
            {"id": item["id"], "phase": STATUS_PHASE_ERROR}
            for item in (carried if isinstance(carried, list) else [])
            if isinstance(item, dict)
            and item.get("id") in live
            and live[item["id"]].phase == STATUS_PHASE_COMPOSING
        ]
        log.emit_status(
            STATUS_PHASE_ERROR,
            f"{whose} died with the process holding epoch {opened.epoch!r}, "
            f"which ended before it replied",
            opened.channel,
            tasks=dead,
            opened=opened.seq,
        )


class Lane:
    """The status lane over one session log, and the driver it schedules.

    A lane with no driver has no agent attached: nothing is composing, so it
    emits nothing and dispatches nothing. That is the state the backend is in
    until a tier is configured, and it is deliberately not disguised as a
    working one.

    `expert` is the tier a channel the human has transferred takes its turns on,
    and the choice is made per channel: transferring one thread must leave every
    other where it was, so the tier cannot be a property of the session or of
    the driver. A lane with no expert tier configured never escalates anything.

    `seats` is which driver occupies the first rung on a named channel, for the
    channels that do not take the session's own. It is the seat that varies and
    never the number of rungs: a channel seated here still hands a turn up to
    the one expert, because a first rung that is already the expert has nowhere
    to hand one.
    """

    def __init__(
        self,
        log: SessionLog,
        driver: TurnDriver | None = None,
        expert: TurnDriver | None = None,
        seats: Mapping[str, TurnDriver] | None = None,
    ) -> None:
        self.log = log
        self.driver = driver
        self.expert = expert
        self.seats = dict(seats or {})
        self._doctor = False

    def tier_for(self, channel: str, driver: TurnDriver, gesture: Turn | None = None) -> TurnDriver:
        """The tier this channel's next turn goes to: the expert one when the
        human has transferred this channel, asked the expert to proceed, or the
        gesture's own class names it,
        and this channel's own first-rung seat otherwise.

        Named before the `composing` entry is written rather than after, so the
        tier the human is told they are waiting on is the tier that takes the
        turn.

        `gesture` is the turn about to be taken, where the caller has one. A
        caller asking only which tier a channel is sitting on -- with no turn
        scheduled and so no gesture to class -- passes none and gets that.
        """
        seated = self.seats.get(channel, driver)
        if self.expert is None:
            return seated
        if in_expert_mode(self.log.entries(), channel):
            return self.expert
        if gesture is not None and (gesture.proceed or self._judgment(gesture) is not None):
            return self.expert
        return seated

    def _judgment(self, gesture: Turn) -> str | None:
        """Which judgment class this turn is, read off the board as it stands.

        Replayed here rather than at dispatch time because the seat has to be
        named before the turn is announced: a class read after the first rung
        had the turn is a class that arrived too late to skip it.
        """
        entries = self.log.entries()
        return judgment_class(
            replay(self.log.epoch, entries),
            entries,
            gesture.channel,
            concluding=gesture.concluding is not None,
            conflict=gesture.conflict is not None,
            reassess=gesture.reassess,
        )

    def accept(
        self, batch: Sequence[EventSubmission], epoch: str
    ) -> tuple[list[Receipt], list[threading.Thread]]:
        """Judge a batch, emit the lane for every human turn in it, and schedule
        each turn's dispatch.

        The receipts are settled and the lane is written before this returns;
        the driver has not been touched. The threads come back so a caller that
        needs to know when a turn finished can wait for it -- nothing in the
        request path does.

        The batch arrives already screened for payload shape: the write route is
        the one caller, and it runs that check before handing anything over. So
        there is no second check here, and a malformed batch reaching this
        method would raise out of the appender rather than come back receipted.
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
                if receipt.status != "accepted":
                    continue
                # Asked once the gesture has landed, because the count is read
                # off the entry it just left. Which dismissals are a refusal of
                # the first rung is the count's own question, so what decides
                # anything here is only whether a dismissal landed at all.
                if _dismisses_on_the_map(event):
                    self._signal()
                turn = turn_of(event)
                # Read once, here, and carried with the turn: the obligation is
                # a window on the log that the next agent reply closes, so the
                # turn must take it along rather than look for it again later.
                owed = self._owed(turn)
                if not is_answerable(event) and not self._owes_rulings(event, owed):
                    continue
                targets = _impact_targets(receipt.seq, owed)
                turn = turn._replace(
                    mootness=owed, tasks=tuple(task_id(receipt.seq, one) for one in targets)
                )
                # The tier is the dispatched channel's, and it is read after the
                # gesture landed: a turn carrying the human's transfer is itself
                # the escalation, and must not be composed by the tier they just
                # moved off. The gesture goes with it, so a judgment class names
                # the expert here rather than after a first-rung turn was
                # announced and taken.
                driver = self.tier_for(turn.channel, base, turn)
                # The two entries are addressed to two different channels, and
                # for every gesture but a fold they are the same one. `accepted`
                # answers the human's gesture, so it belongs where they made it.
                # `composing` says who owes a turn and names the tier taking it,
                # so it belongs on the channel that turn runs on -- the same
                # channel its `replied` or `error` will close, and the same one
                # whose expert mode chose the tier being named.
                #
                # A task already holding one of this gesture's targets is
                # superseded here, on the `accepted` entry, before the new task
                # opens: read and written under the one hold of the lock, so the
                # next gesture in the batch sees this one's task as the holder.
                self.log.emit_status(
                    STATUS_PHASE_ACCEPTED,
                    f"{event.kind} from the human accepted on channel {event.channel!r}",
                    event.channel,
                    tasks=self._supersede(targets),
                )
                announced = self._announce(
                    driver,
                    turn,
                    tasks=[
                        {
                            "id": task_id(receipt.seq, one),
                            "target": one,
                            "gesture": receipt.seq,
                            "basis": receipt.seq,
                            "mode": IMPACT_MODE,
                            "seat": driver.tier,
                            "phase": STATUS_PHASE_COMPOSING,
                        }
                        for one in targets
                    ],
                )
                turns.append((driver, turn._replace(opened=announced)))
        return receipts, [self._schedule(driver, turn) for driver, turn in turns]

    def _supersede(self, targets: Sequence[str]) -> list[dict[str, Any]]:
        """End every task holding one of these targets, as the entry ending them
        names them."""
        return [
            {"id": task.id, "phase": STATUS_PHASE_SUPERSEDED}
            for task in impact_tasks(self.log.entries()).values()
            if task.target in targets and task.holds
        ]

    def _announce(
        self,
        driver: TurnDriver,
        turn: Turn,
        *,
        pressed: bool = False,
        tasks: list[dict[str, Any]] | None = None,
    ) -> int:
        """Open the lane on a turn about to be taken, naming the seat taking it.

        Every turn is announced, including the two nobody spoke a gesture to
        start: the lane's pairing rule reads a `composing` and its closing
        `replied` as one turn, so a turn that closed without opening reads as a
        `replied` for a turn the page never saw begin -- and while it runs the
        human is waiting on a clock nobody wound.

        `pressed` marks the announcement of a turn handed up because the rung
        below it was refused, which is the record the distrust count reads that
        signal off. It rides this entry rather than one of its own: the hand-up
        announces anyway, and a second entry saying the same thing is one more
        thing for a reader of the lane to pair up.

        `tasks` is the impact tasks this turn carries, each described whole. A
        task opens where the seat weighing it is announced, so its start is
        when the human began waiting on that seat.

        Returns the announcement's sequence, which the turn's closing entry
        names.
        """
        payload: dict[str, Any] = {
            "phase": STATUS_PHASE_COMPOSING,
            "detail": f"the {driver.tier!r} tier is composing a reply",
            TIER_KEY: driver.tier,
        }
        if pressed:
            payload[PRESSED_KEY] = True
        if tasks:
            payload[TASKS_KEY] = tasks
        return self.log.record(STATUS_KIND, payload, turn.channel).seq

    def _owed(self, turn: Turn) -> MootnessObligation | None:
        """What the gesture this turn is being taken on owes the rest of the
        board, as the board stands at the moment the turn is scheduled.

        The map's only, because it is the only channel a ruling is owed on.
        """
        if turn.channel != MAP_CHANNEL:
            return None
        entries = self.log.entries()
        return mootness_obligation(replay(self.log.epoch, entries), entries, MAP_CHANNEL)

    @staticmethod
    def _owes_rulings(event: EventSubmission, owed: MootnessObligation | None) -> bool:
        """Whether this gesture is owed a turn it is not conversation for.

        Applying is the one. It is no message and the backend answers it with
        nothing -- unless it stranded a decision, which leaves rulings owed on
        that gesture and makes it one of the judgment classes. Without this the
        class names a seat for a turn nobody scheduled, and the rulings fall to
        whatever the human happens to do next, or to nothing at all if they do
        nothing.

        Scoped to the human's own apply on the map: no other channel has a queue
        to apply from, and an agent's entry is never a gesture.
        """
        return (
            owed is not None
            and event.actor == "human"
            and event.kind == APPLY_KIND
            and event.channel == MAP_CHANNEL
        )

    def _signal(self) -> None:
        """Count the wordless refusals of the first rung, and write the move the
        second of them buys.

        The count is read off the log every time rather than carried between
        signals, so it is the session's count and not one process's. Nothing is
        written for a signal below the threshold, which is exactly why a tally
        in memory cannot be trusted: a backend replaced after the first signal
        would start again at nothing, and the human would have to say it twice
        more to be heard once. Both signals leave a record for this to read --
        the human's own dismissal, and the marked announcement the press path
        writes as it hands the turn up.

        Called with the signal's own record already on the log, so the count
        includes the signal being answered here.

        Counting, asking and writing are one critical section, under the append
        lock the write takes anyway. Presses arrive from turn threads that run
        concurrently by design, and split apart these three steps let two of
        them read the same count and the same empty guard and both append: the
        entry is sticky, so "at most one" has to hold against the racing pair
        and not only against the sequential one. The lock is re-entrant, so the
        accepted path already holding it counts a dismissal at no extra cost.
        """
        if self.expert is None:
            return
        with self.log.appending():
            entries = self.log.entries()
            counted = distrust_count(entries, self.log.epoch, MAP_CHANNEL, self.expert.tier)
            if counted < DISTRUST_THRESHOLD:
                return
            if policy_transferred(entries, MAP_CHANNEL):
                return
            self.log.emit_status(STATUS_PHASE_TRANSFERRED, DISTRUST_MOVED, MAP_CHANNEL)

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
        turn = Turn(MAP_CHANNEL, reassess=True)
        driver = self.tier_for(MAP_CHANNEL, self.driver, turn)
        return self._schedule(driver, turn._replace(opened=self._announce(driver, turn)))

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
                mootness=turn.mootness,
            )
            took = self._press(driver, turn, dispatch, _run(driver, self.log, dispatch))
            if self._watching(turn):
                self._hand_back(took, standing)
            self._close(turn, STATUS_PHASE_REPLIED, f"the {took.tier!r} tier's turn is over")
        except DocumentRefusedError as error:
            # Named for the seat the ladder ended on rather than the one it
            # started from: that is the seat the human is owed the name of, and
            # on a turn handed up once it is not the same seat.
            self._close(turn, STATUS_PHASE_ERROR, f"the {error.tier!r} tier failed: {error!r}")
        except Exception as error:
            self._close(turn, STATUS_PHASE_ERROR, f"the {driver.tier!r} tier failed: {error!r}")
        finally:
            if turn.reassess:
                self._doctor = False

    def _close(self, turn: Turn, phase: str, detail: str) -> None:
        """Close the lane on a turn, ending each of its tasks still live in the
        same phase.

        A task a later gesture superseded while this turn ran was already ended
        by that gesture's `accepted` entry, and is left out here: it reads
        superseded for good, never replied and never failed.
        """
        with self.log.appending():
            known = impact_tasks(self.log.entries())
            ended = [
                {"id": one, "phase": phase}
                for one in turn.tasks
                if one in known and known[one].phase == STATUS_PHASE_COMPOSING
            ]
            self.log.emit_status(phase, detail, turn.channel, tasks=ended, opened=turn.opened)

    def _press(self, driver: TurnDriver, turn: Turn, dispatch: Path, reply: _Pressed) -> TurnDriver:
        """Press a turn that did not answer, and say so when no seat will.
        Returns whichever seat ended up taking it.

        Two failures press, and they press the same way. A reply that is not the
        grill-master's document is one; a valid one leaving a decision the
        dispatch named unruled is the other. Neither is a failure another turn on
        the same seat fixes -- the seat has already had its retry -- so the turn
        goes up one rung, narrowed to what is still outstanding, and no further:
        from the seat with nothing above it the human is told instead.

        The check is code's, and it is coverage rather than correctness: the
        obligation is a list of decision ids, and what the reply did with each is
        read off its own rulings. A ruling this would disagree with is not a
        ruling missing.

        Nothing here authors a map mutation. The expert is asked for the same
        rulings the first rung was, and where it declines too the human is told
        which decisions went unruled, so the change is theirs to ask for. A
        backend that minted the invalidates itself would be the sole-author rule
        broken by the code that enforces it.
        """
        obligation = DispatchContext.model_validate_json(
            dispatch.read_text(encoding="utf-8")
        ).mootness
        # The list shrinks as the ladder is walked. A turn handed up is measured
        # against what the rung below left unruled, never against the original
        # list, or a decision the first seat ruled on is reported as one nobody
        # did -- and the human is sent to argue about a verdict that was made.
        standing = [] if obligation is None else list(obligation.ids)
        refusal = reply.refusal
        if refusal is None:
            standing = self._unruled(standing, reply.spoke, obligation)
        if refusal is None and not standing:
            return driver
        if self.expert is not None and self.expert is not driver:
            self._hand_up(self.expert, turn)
            pressed = self._insist(self.expert, turn, obligation, standing)
            if pressed is not None:
                driver, refusal = self.expert, pressed.refusal
                if refusal is None:
                    standing = self._unruled(standing, pressed.spoke, obligation)
        if refusal is not None:
            self.log.record("informational", {"text": _lost(driver.tier)})
            raise DocumentRefusedError(driver.tier, refusal)
        # Something is only ever outstanding where an obligation stated it, so
        # the second test is the type system's rather than a case of its own.
        if standing and obligation is not None:
            self.log.record("informational", {"text": _unmet(obligation, standing)})
        return driver

    def _unruled(
        self, owed: Sequence[str], spoke: int | None, obligation: MootnessObligation | None
    ) -> list[str]:
        """Which of these decisions the turn just taken left unruled.

        Read off the single entry that turn appended, which its own driver named
        by sequence. A window on the log would not do: map turns run
        concurrently, so a second turn's reply can land between the moment this
        one was dispatched and the moment it answered, and coverage read from a
        window would then credit this turn with rulings made for another. A turn
        that appended nothing names no entry and credits nothing, which is the
        turn the ladder owes a hand-up.

        A decision a later gesture's task took over is not left unruled by this
        turn: the ruling on it is owed by the later turn now, and a press or a
        notice here would ask twice for one ruling.
        """
        entries = self.log.entries()
        moved = set(superseded_targets(entries, obligation))
        return [one for one in unruled(owed, *rulings_of(entries, spoke)) if one not in moved]

    def _hand_up(self, expert: TurnDriver, turn: Turn) -> None:
        """Announce the expert's turn on a gesture the rung below it could not
        answer, and on the map count that hand-up as a refusal of that rung.

        The record and the count it feeds are one hold of the append lock, which
        is what puts the hand-up on the log no later than the moment it is
        counted. Split apart, the count would be taken before the thing it is
        counting existed, and a successor process reading the log back would
        find one signal fewer than the human made.

        It is counted where the decision to hand up is made rather than on the
        way out: a seat that could not be reached still leaves the first rung's
        turn the one that was not enough. The map's count only, because the map
        is the channel the move is about -- a thread that cannot hold its own
        shape says nothing about the seat composing the board.
        """
        with self.log.appending():
            self._announce(expert, turn, pressed=True)
            if turn.channel == MAP_CHANNEL:
                self._signal()

    def _insist(
        self,
        expert: TurnDriver,
        turn: Turn,
        obligation: MootnessObligation | None,
        standing: Sequence[str],
    ) -> _Pressed | None:
        """One expert turn on the same gesture, carrying what is still unruled.

        The obligation is handed in rather than derived again: by now an agent
        has spoken on this channel, so nothing would derive it -- and it is
        narrowed to what is left, since re-asking for a ruling already made is
        asking the human to read the same verdict twice. A turn pressed only
        because its document would not validate carries the obligation whole,
        there being no ruling to narrow it by.

        The turn is already announced: the caller writes that announcement as
        the hand-up's own record, before the count that reads it.

        A tier that cannot be reached costs the insistence and nothing else. The
        human's turn was already answered by the first tier, and turning a
        reachability failure into the turn's own failure would report an answer
        they can read as an error.
        """
        narrowed = (
            None
            if obligation is None
            else obligation.model_copy(update={"ids": list(standing) or obligation.ids})
        )
        try:
            dispatch = record_dispatch(
                self.log,
                channel=turn.channel,
                concluding=turn.concluding,
                conflict=turn.conflict,
                reassess=turn.reassess,
                mootness=narrowed,
            )
            return _run(expert, self.log, dispatch)
        except Exception:
            return None

    def _board(self) -> Image2:
        return replay(self.log.epoch, self.log.entries())

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
                # A conflict is one of the judgment classes, so the seat is read
                # for it too rather than inherited from whoever raised it.
                turn = Turn(MAP_CHANNEL, conflict=conflict)
                seat = self.tier_for(MAP_CHANNEL, driver, turn)
                self._take_turn(seat, turn._replace(opened=self._announce(seat, turn)))


def _impact_targets(gesture: int, owed: MootnessObligation | None) -> list[str]:
    """The decisions this gesture starts an impact task on: those its own marked
    answer put in question.

    The obligation must be this gesture's own. A turn on the map can inherit an
    earlier answer's obligation while that answer is still unreplied, and the
    tasks for it were started by that answer; an applied invalidate owes
    rulings on what rested on the decision it killed, but starts no task.
    """
    if owed is None or owed.cause != ANSWER_KIND or owed.gesture != gesture:
        return []
    return list(owed.ids)


def _unmet(obligation: MootnessObligation, standing: Sequence[str]) -> str:
    """What the human is told when no seat ruled on what the gesture obliged.

    Named by id and by the gesture that left them there, because the human's
    move from here is to ask for the change on the map thread and a notice that
    described the case would leave them working out which decisions it meant.

    It says the decisions were not ruled on rather than that no invalidate was
    proposed: a turn ruling that all three stand has proposed nothing either, and
    that is a discharged obligation rather than this one.
    """
    named, them = ", ".join(standing), "it" if len(standing) == 1 else "them"
    if obligation.cause == INVALIDATE_KIND:
        return (
            f"{obligation.target} left the flow and {named} rested on it. {named} "
            f"{'was' if len(standing) == 1 else 'were'} not ruled on, so the board is offering "
            f"{them} again. Ask on the map thread if that is wrong."
        )
    return (
        f"The answer to {obligation.target} put {named} in question, and {named} "
        f"{'was' if len(standing) == 1 else 'were'} not ruled on, so the board is still "
        f"offering {them}. Ask on the map thread if that is wrong."
    )
