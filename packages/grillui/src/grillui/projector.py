"""The context images, folded from the log and nothing else.

`fold` is a pure function of an epoch and a sequence of entries: no clock, no
randomness, no I/O. The same log therefore always yields the same images, and an
image rebuilt from disk matches one held in memory. Writing an image to a file is
a separate step downstream of this module -- the image files are derived caches,
never a recovery source.

The fold tolerates any entry the appender accepted. An entry whose payload it
cannot read contributes what it can and no more, because a projector that raises
on an accepted entry takes the session down with it.

**What each update kind does to a decision.**

| kind            | effect                                                        |
|-----------------|---------------------------------------------------------------|
| `session-start` | the briefing's plan seeds the board, decision by decision      |
| `add-node`      | the node enters the board `open`                               |
| `revise`        | supplied fields replace; omitted ones and the status stand     |
| `invalidate`    | status `invalidated`, carrying the rationale it arrived with   |
| `answer`/`settle` | the answer is recorded and the status is `settled`           |
| `unsettle`      | back to `open`, its answer dropped, its dependents `stale`     |
| `resolve-stale` | out of `stale`: `settled` if an answer survived, else `open`   |
| `elicit-alert`  | the target's lock becomes this alert's blocking flag           |
| `informational` | nothing on the board; the human is told                        |
| `fold`          | its sub-updates, in order, all of them                         |
| `apply`         | the proposals it names, in order, and they leave the queue     |
| `dismiss`       | the proposals it names leave the queue, having changed nothing |
| `thread-fold`   | its channel's thread is `folded`; no decision moves            |
| `thread-park`   | its channel's thread is `parked`; no decision moves            |
| `thread-close`  | its channel's thread is `closed`; no decision moves            |

A human `answer` naming the thread it was armed from closes that thread in the
same entry that settles the decision, and the thread's conclusion is the answer
text. One entry rather than two: an answer and a close that half-land leave the
human looking at a settled decision whose thread still asks to be closed.

A human turn on a closed thread opens it again. Re-opening rides the turn path
rather than a gesture of its own because saying something in a thread the human
had finished with *is* picking it back up: a separate gesture would be a second
way to say the same thing, and a closed thread that took a turn and stayed
closed would drop that turn out of the end-of-session reckoning. An agent's
turn does not re-open one -- what the human is done with is not the agent's to
re-open.

Two of those rules are this projector's to state rather than the protocol's.
*Dependent staleness*: unsettling a decision makes every settled decision that
reaches it through `prereqs` stale, transitively, because an answer resting on a
withdrawn answer is exactly as unsupported at one remove as at none. *Fog*: an
open decision whose `fogUntil` is unsettled reads as `fogged`, so the status is
derived from the board rather than asserted by anyone.

The board is seeded through the log and never by re-reading the handoff file.
`session-start` carries the validated briefing, so a fresh process folding
`log.jsonl` alone reproduces the seeded board -- which is what makes the log the
only recovery source and leaves the handoff file with no authority the moment
that entry lands.

Neither thread gesture touches a decision, and that is the sole-author rule
holding: what a thread concluded reaches the board only through the grill-master
being dispatched with it.

**A map mutation an agent authors is a proposal, not a change.** One human
gesture is what puts a conversational turn's declared impact on the board, so an
agent's update lands by itself only where landing cannot overwrite what the
human decided. That test is drawn against the board *at arrival* rather than
when the update was written, because the board may have moved under it while it
was in flight -- and this fold, walking the log in order, is the only place
where "at arrival" is a fact rather than a guess.

| an agent's update    | on arrival                                       |
|----------------------|--------------------------------------------------|
| `add-node`           | lands: a new question overwrites nothing         |
| `resolve-stale`      | lands: it is the agent adjudicating a change the human already made |
| `revise`, `settle`   | lands only while the decision carries no answer  |
| `unsettle`, `invalidate` | always queued: undermining a decision is the human's call |
| `informational`, `elicit-alert` | land, and queue as the notices they are |

A queued proposal locks the decision it targets out of the frontier, so nobody
answers a question that has a change waiting on it, and it holds its update's
bytes until the human applies them -- `apply` puts them on the board as one
gesture the human authored, `dismiss` ends them having changed nothing. Both
name queue entries by id, so what lands is what the agent wrote.

Notices and proposals share the `pending` array, which is the queue of what the
human has not dealt with yet. Four things take an item off it or mark it, and
every one of them is a gesture somebody made.

*The human answering a decision* is the human dealing with every notice standing
against it: they were told, and then they decided. That is the only signal of it
there is -- merely reading a notice is presentation state the page owns and never
sends -- so a notice anchored to no decision stays queued for the session, which
is the honest reading of a queue nobody has acted on rather than a rule that
empties it.

*The author withdrawing its own notice* marks it superseded, in place. Which
notices an author may withdraw is its own: a response naming somebody else's
pending update is ignored, because superseding is an author revising itself.
When the human already answered the decision that notice was about, the
withdrawal and the board disagree, and that is a `SupersedeConflict` -- read out
of the log by `supersede_conflicts` and handed back to the authoring agent as a
dispatch. Nothing here resolves one: only the author knows what the rewrite was
for, and a projector that dropped the human's answer to make the withdrawal fit
would be rewriting a decision the human made.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from grillui.schemas import (
    APPLY_KIND,
    DISMISS_KIND,
    FOLD_SHAPED,
    FROM_THREAD_KEY,
    PENDING_KEY,
    PROPOSABLE_KINDS,
    PROPOSED_ANSWER_KEY,
    SESSION_START_KIND,
    SET_ASIDE_KINDS,
    SUPERSEDES_KEY,
    THREAD_CLOSE_KIND,
    THREAD_FOLD_KIND,
    THREAD_GESTURE_KINDS,
    THREAD_KINDS,
    THREAD_PARK_KIND,
    Answer,
    CatchUpEntry,
    ConvergedProposal,
    Decision,
    FoldedThreadStub,
    HistoryEntry,
    Image1,
    Image2,
    LogEntry,
    Option,
    PendingUpdate,
    SettledEntry,
    SupersedeConflict,
    Thread,
    ThreadProjection,
    ThreadState,
    ThreadStub,
    read_turns,
)

_NOTICE_KINDS = frozenset({"informational", "elicit-alert"})
_REVISABLE_TEXT = ("short", "title", "body")


@dataclass
class _Board:
    """The fold's running state, keyed the way the images are read.

    The last five fields are the fold's own bookkeeping and reach no image: who
    authored each queue entry, the update bytes a queued proposal is holding,
    which entries the human has since dealt with and when, when the human last
    changed each decision, and the withdrawals that arrived too late. Keeping
    them here rather than in image 1 is what lets the queue answer "whose was
    this?", "what would it do?" and "was this already acted on?" without either
    image growing a field the protocol never declared.
    """

    decisions: dict[str, Decision] = field(default_factory=dict)
    threads: dict[str, Thread] = field(default_factory=dict)
    history: dict[str, list[HistoryEntry]] = field(default_factory=dict)
    pending: list[PendingUpdate] = field(default_factory=list)
    seq: int = 0
    author_of: dict[str, str] = field(default_factory=dict)
    proposals: dict[str, dict[str, Any]] = field(default_factory=dict)
    dealt: dict[str, tuple[PendingUpdate, int]] = field(default_factory=dict)
    touched: dict[str, int] = field(default_factory=dict)
    conflicts: list[SupersedeConflict] = field(default_factory=list)

    def node(self, payload: Mapping[str, object]) -> Decision | None:
        target = payload.get("target")
        return self.decisions.get(target) if isinstance(target, str) else None

    def queued(self, pending_id: str) -> PendingUpdate | None:
        return next((one for one in self.pending if one.id == pending_id), None)


def _run(entries: Sequence[LogEntry]) -> _Board:
    """The walk both readers of the log share.

    One walk, because the queue's state and the conflicts it produced are the
    same fold seen twice: a second walk written to answer only the conflict
    question is a second answer to when a notice was dealt with.
    """
    board = _Board()
    for entry in entries:
        board.seq = entry.seq
        if entry.kind in FOLD_SHAPED:
            # The gesture is one entry, so there is no state in which half of it
            # landed: either the log has it and every sub-update applies, or it
            # does not and none of them does.
            for index, update in enumerate(_updates(entry)):
                key = f"{entry.idempotency_key}#{index}"
                _apply(board, entry, str(update.get("kind")), update, key)
        else:
            _apply(board, entry, entry.kind, entry.payload, entry.idempotency_key)
        if entry.kind in {APPLY_KIND, DISMISS_KIND}:
            _clear(board, entry)
    return board


def supersede_conflicts(entries: Sequence[LogEntry]) -> list[SupersedeConflict]:
    """Every withdrawal that landed after the human had already acted.

    A pure read of the log, in the order the withdrawals arrived, so the same
    log always names the same conflicts -- which is what lets a caller tell a
    conflict it has already handed back from one that has just appeared.
    """
    return _run(entries).conflicts


@dataclass(frozen=True)
class Proposed:
    """One queued map mutation, as the appender has to see it.

    `update` is the sub-update the agent authored, verbatim, so applying it puts
    the author's own bytes on the board rather than whatever the applying client
    sent. `conflicted` is the board having moved under it: the human changed its
    target after it was authored, so applying it now would overwrite the change
    they made while it waited. That is refused rather than resolved -- the
    proposal stays queued, and what to do about it is a conversation.
    """

    pending: PendingUpdate
    update: dict[str, Any]
    conflicted: bool


def queue(entries: Sequence[LogEntry]) -> dict[str, Proposed]:
    """The proposals waiting for the human, by id.

    A pure read of the log, like the conflict reader beside it, and the whole of
    what a caller needs to judge a gesture on the queue: whether the id names
    something still waiting, what it would do, and whether the board moved under
    it. Notices are not here -- a notice is not something to apply.
    """
    board = _run(entries)
    return {
        item.id: Proposed(
            pending=item,
            update=board.proposals[item.id],
            conflicted=board.touched.get(item.target or "", 0) > item.authored_at,
        )
        for item in board.pending
        if item.id in board.proposals
    }


def fold(epoch: str, entries: Sequence[LogEntry]) -> Image2:
    """Fold the log into image 2. Image 1 is this, minus history."""
    board = _run(entries)
    seq = board.seq

    settled = [
        SettledEntry(id=node.id, answer=_answer_text(node))
        for node in board.decisions.values()
        if node.status == "settled"
    ]
    settled_ids = {item.id for item in settled}
    for node in board.decisions.values():
        if node.status == "open" and node.fog_until and node.fog_until not in settled_ids:
            node.status = "fogged"
    # A decision with a change waiting on it is not a decision anyone should be
    # answering: the frontier already skips a locked node, so the queue's hold
    # on it is the same lock a blocking alert takes. A withdrawn proposal is not
    # one -- the author took it back, and the page has dropped it.
    for item in board.pending:
        blocked = board.decisions.get(item.target or "")
        if blocked is not None and item.id in board.proposals and not item.superseded:
            blocked.locked = True
    frontier = [
        node.id
        for node in board.decisions.values()
        if node.status == "open" and not node.locked and all(p in settled_ids for p in node.prereqs)
    ]

    return Image2(
        epoch=epoch,
        seq=seq,
        decisions=list(board.decisions.values()),
        frontier=frontier,
        settled=settled,
        threads=list(board.threads.values()),
        pending=board.pending,
        history=board.history,
    )


def _apply(
    board: _Board, entry: LogEntry, kind: str, payload: Mapping[str, object], key: str
) -> None:
    """One update against the board, whether it arrived alone or inside a fold.

    A fold's sub-updates share their gesture's sequence, timestamp and actor,
    because that is the truth of them: they landed together, in one entry, on
    one human gesture.

    An agent's update that would overwrite a decision the human made goes to
    the queue instead of the board, and contributes no history: history is what
    happened to a decision, and a proposal has not happened to one yet.
    """
    _supersede(board, entry, payload)
    if _proposes(board, entry.actor, kind, payload):
        _queue(board, entry, kind, payload, key)
        return
    if entry.actor == "human":
        _touch(board, entry, payload)
    if kind == SESSION_START_KIND:
        _seed(board, payload)
    elif kind == "add-node":
        _add_node(board, payload)
    elif kind == "revise":
        _revise(board, payload)
    elif kind == "invalidate":
        _invalidate(board, payload)
    elif kind in {"answer", "settle"}:
        _settle(board, payload)
        if kind == "answer" and entry.actor == "human":
            _dealt_with(board, entry, payload)
            _close_armed_thread(board, payload)
    elif kind == "unsettle":
        _unsettle(board, payload)
    elif kind == "resolve-stale":
        _resolve_stale(board, payload)
    elif kind in _NOTICE_KINDS:
        _notice(board, entry, kind, payload, key)
    elif kind == "thread-created":
        _create_thread(board, entry)
    elif kind == "thread-turn":
        _append_turns(board, entry)
    elif kind in THREAD_GESTURE_KINDS:
        _set_thread_state(board, entry, kind)
    _record_history(board, entry, kind, payload)


def _updates(entry: LogEntry) -> list[Mapping[str, object]]:
    raw = entry.payload.get("updates")
    if not isinstance(raw, list):
        return []
    return [update for update in raw if isinstance(update, Mapping)]


def to_image1(image: Image2) -> Image1:
    """Image 2 without its history, which is the only field that separates them."""
    return Image1(**image.model_dump(exclude={"history"}))


def catch_up(epoch: str, entries: Sequence[LogEntry], channel: str) -> list[CatchUpEntry]:
    """What the board moved while this thread was set aside, folded out of the log.

    A map event is an entry that moves a decision, and that is the whole of the
    definition: an entry is one exactly when folding the log through it changes
    image 1's decisions. So that is what is measured here -- one fold per entry
    of the interval, each compared against the fold before it -- rather than a
    list of kinds. A list would be a second definition of what changed the map,
    and it disagrees with the projector the first time a kind lands one way here
    and waits the other way there; the human would then be reading a board the
    catch-up does not describe.

    The one field a decision carries that a move does not touch is its lock,
    which is the queue's hold rather than anything that happened to the
    decision: an update waiting on the human is a map event at the `apply` that
    lands it and never at the entry that queued it.

    An entry that moved several decisions contributes one catch-up entry per
    decision, and each names the sequence, kind and rationale the log carries
    at that point. Nothing here is composed.

    ponytail: one fold per interval entry, which is O(interval) folds over a log
    bounded by one grilling and an interval bounded by two human gestures.
    """
    interval = _set_aside_interval(entries, channel)
    if interval is None:
        return []
    start, stop = interval
    caught: list[CatchUpEntry] = []
    before = _decision_state(epoch, entries[:start])
    for index in range(start, stop):
        after = _decision_state(epoch, entries[: index + 1])
        entry = entries[index]
        caught += [
            CatchUpEntry(seq=entry.seq, target=target, **_moved_by(entry, target))
            for target, state in after.items()
            if before.get(target) != state
        ]
        before = after
    return caught


def _set_aside_interval(entries: Sequence[LogEntry], channel: str) -> tuple[int, int] | None:
    """The half-open range of entries between this channel's last set-aside
    gesture and the turn that reopened it, or nothing where this dispatch is not
    that reopening.

    The interval is bounded by gestures rather than by wall time, and it is the
    *first* human turn after the gesture that reopens the thread: a second one
    is an ordinary turn on a thread nobody set aside any more, and a catch-up
    riding it would re-tell the thread what it was told last turn.
    """
    aside = [
        index
        for index, entry in enumerate(entries)
        if entry.channel == channel and entry.kind in SET_ASIDE_KINDS
    ]
    if not aside:
        return None
    start = aside[-1] + 1
    reopening = [
        index
        for index, entry in enumerate(entries[start:], start=start)
        if entry.channel == channel and entry.actor == "human" and entry.kind in THREAD_KINDS
    ]
    return (start, reopening[0]) if len(reopening) == 1 else None


def _decision_state(epoch: str, entries: Sequence[LogEntry]) -> dict[str, str]:
    return {
        node.id: node.model_dump_json(exclude={"locked"}) for node in fold(epoch, entries).decisions
    }


def _moved_by(entry: LogEntry, target: str) -> dict[str, str]:
    """The kind and rationale the log carries for what moved this decision.

    An entry carrying sub-updates is read through to the one naming this
    decision, which is what makes an applied proposal say `revise` at the
    sequence of the apply rather than `apply` at it. A decision moved as a
    consequence of another -- a node the settling of its prerequisite fogged --
    is named by the entry itself, since that is all the log says about it.
    """
    for update in _updates(entry) or [entry.payload]:
        if update.get("target") == target:
            return {"kind": str(update.get("kind", entry.kind)), "why": _text(update, "why")}
    return {"kind": entry.kind, "why": ""}


def conclusion_of(thread: Thread, applied: Mapping[str, str] | None = None) -> str | None:
    """What a thread concluded, by the two ways a thread reaches one.

    A folded thread's conclusion is the turn whose content was applied to the
    board. A thread closed by the answer it was armed from concluded that
    answer's text, which `applied` carries -- the answer is on the decision, not
    in the thread, so it takes the log to say which thread produced it. A thread
    the human simply closed produced nothing, and neither did an open or parked
    one.

    One reader, because the conclusion is quoted in three places -- the stub a
    sibling thread's agent sees, the dispatch that hands it to the grill-master,
    and the terminal result -- and three readers is how they come to disagree
    about what a thread concluded.
    """
    if thread.state == "closed":
        return (applied or {}).get(thread.id)
    if thread.state != "folded" or not thread.turns:
        return None
    return thread.turns[-1].text


def answers_from_threads(entries: Sequence[LogEntry]) -> dict[str, str]:
    """The answer text each thread was armed to produce, by thread id.

    Read off the log rather than off the image, because the image records the
    answer against the decision and says nothing about where the human got it.
    The last one wins: a thread reopened and answered again concluded what it
    concluded the second time.
    """
    applied: dict[str, str] = {}
    for entry in entries:
        named = entry.payload.get(FROM_THREAD_KEY)
        given = entry.payload.get("answer")
        if entry.kind != "answer" or not isinstance(named, str) or not isinstance(given, Mapping):
            continue
        applied[named] = _or_none(given.get("text")) or _or_none(given.get("option")) or ""
    return applied


def project_thread(image: Image2, channel: str) -> ThreadProjection:
    """Image 2 as one thread's agent is given it.

    A pure fold over an image that was itself a pure fold, so a dispatch is
    reproducible from the log alone. The board crosses unchanged: only the
    bodies of other threads are reduced, and only to what it takes to know a
    thread exists and whether to go and read it.
    """
    threads: list[FoldedThreadStub | ThreadStub | Thread] = []
    for thread in image.threads:
        if thread.id == channel:
            threads.append(thread)
        elif thread.state == "folded":
            threads.append(
                FoldedThreadStub(
                    id=thread.id,
                    decision=thread.decision,
                    title=thread.title,
                    conclusion=conclusion_of(thread) or "",
                )
            )
        elif thread.state != "parked":
            threads.append(
                ThreadStub(
                    id=thread.id,
                    decision=thread.decision,
                    title=thread.title,
                    state=thread.state,
                )
            )
    return _projection(image, threads)


def _projection(
    image: Image2, threads: list[FoldedThreadStub | ThreadStub | Thread]
) -> ThreadProjection:
    """The image's own sections, carried across by reference rather than
    rebuilt: a second construction of a decision is a second chance to differ
    from the image the completeness check compares against."""
    return ThreadProjection(
        epoch=image.epoch,
        seq=image.seq,
        decisions=image.decisions,
        frontier=image.frontier,
        settled=image.settled,
        threads=threads,
        pending=image.pending,
        history=image.history,
    )


def whole_board(image: Image2) -> ThreadProjection:
    """Image 2 with every thread's body intact: what the grill-master is given.

    The same shape a thread projection has, so one dispatch context describes
    both, and byte-identical to image 2 because nothing was reduced.
    """
    return _projection(image, list(image.threads))


def node_from_payload(payload: Mapping[str, object], node_id: str) -> Decision:
    """The node an add-node payload materialises into.

    Public because the receipt echoes exactly this node back to the agent that
    asked for it, and a second reader would be a second answer to what the
    board now holds.
    """
    return Decision(
        id=node_id,
        short=_text(payload, "short"),
        title=_text(payload, "title"),
        body=_text(payload, "body"),
        prereqs=_strings(payload.get("prereqs")),
        options=_options(payload.get("options")),
        mandate=_string_map(payload.get("mandate")),
        talk=_string_map(payload.get("talk")),
        fogUntil=_or_none(payload.get("fogUntil")),
        fogTitle=_or_none(payload.get("fogTitle")),
    )


def _seed(board: _Board, payload: Mapping[str, object]) -> None:
    """The briefing's plan, laid onto an empty board.

    Read through the same node reader an add-node uses, so a decision the
    handoff named and one an agent mints later are the same shape on the board;
    a second reader here is how the two come to differ in what a node carries.
    """
    plan = payload.get("plan")
    if not isinstance(plan, Mapping):
        return
    raw = plan.get("decisions")
    if not isinstance(raw, list):
        return
    for decision in raw:
        node_id = decision.get("id") if isinstance(decision, Mapping) else None
        if isinstance(node_id, str):
            board.decisions[node_id] = node_from_payload(decision, node_id)


def _add_node(board: _Board, payload: Mapping[str, object]) -> None:
    node_id = payload.get("target") or payload.get("id")
    if not isinstance(node_id, str):
        return
    board.decisions[node_id] = node_from_payload(payload, node_id)


def _revise(board: _Board, payload: Mapping[str, object]) -> None:
    """Supplied fields replace; omitted ones stand. A revise says what changed,
    so reading an absent field as an empty one would erase the question."""
    node = board.node(payload)
    if node is None:
        return
    for name in _REVISABLE_TEXT:
        value = payload.get(name)
        if isinstance(value, str):
            setattr(node, name, value)
    if isinstance(payload.get("prereqs"), list):
        node.prereqs = _strings(payload.get("prereqs"))
    if isinstance(payload.get("options"), list):
        node.options = _options(payload.get("options"))


def _invalidate(board: _Board, payload: Mapping[str, object]) -> None:
    node = board.node(payload)
    if node is None:
        return
    node.status = "invalidated"
    node.rationale = _text(payload, "why")


def _settle(board: _Board, payload: Mapping[str, object]) -> None:
    node = board.node(payload)
    if node is None:
        return
    raw = payload.get("answer")
    if not isinstance(raw, Mapping):
        return
    node.answer = Answer(option=_or_none(raw.get("option")), text=_or_none(raw.get("text")))
    node.status = "settled"
    node.rationale = _text(payload, "why") or None


def _unsettle(board: _Board, payload: Mapping[str, object]) -> None:
    """A settled decision returns to the frontier, and everything settled on top
    of it goes stale -- transitively, because an answer resting on a withdrawn
    answer is exactly as unsupported at one remove as at none."""
    node = board.node(payload)
    if node is None or node.status != "settled":
        return
    node.status = "open"
    node.answer = None
    node.rationale = _text(payload, "why") or None
    unsupported = [node.id]
    while unsupported:
        withdrawn = unsupported.pop()
        for dependent in board.decisions.values():
            if withdrawn in dependent.prereqs and dependent.status == "settled":
                dependent.status = "stale"
                unsupported.append(dependent.id)


def _resolve_stale(board: _Board, payload: Mapping[str, object]) -> None:
    """Out of stale and back to what the decision actually is: still answered if
    its answer survived the round trip, open if it did not."""
    node = board.node(payload)
    if node is None or node.status != "stale":
        return
    node.status = "settled" if node.answer is not None else "open"
    node.rationale = _text(payload, "why") or None


def _notice(
    board: _Board, entry: LogEntry, kind: str, payload: Mapping[str, object], key: str
) -> None:
    """A notice addressed to the human joins the pending queue; an alert that
    declares itself blocking also locks the decision it is about, so nobody
    answers a question the agent has just said is in question."""
    if kind == "elicit-alert":
        node = board.node(payload)
        if node is not None:
            node.locked = payload.get("blocking") is True
    board.pending.append(
        PendingUpdate(
            id=key,
            target=_or_none(payload.get("target")),
            kind=kind,
            superseded=False,
            authored_at=entry.seq,
        )
    )
    board.author_of[key] = entry.actor


def _proposes(board: _Board, actor: str, kind: str, payload: Mapping[str, object]) -> bool:
    """Whether this update waits for the human instead of landing now.

    Read against the board as it stands at this point in the walk, which is what
    makes the answer a property of the update's arrival rather than of its
    authoring: the same update queues or lands depending on what the human did
    while it was being written.

    The human's own gesture always lands -- that is what a gesture is -- so the
    actor test is the whole of the rule about who may change the board. What is
    left is one question asked of the update: would applying it overwrite an
    answer the board already carries? Undermining a decision is never asked, it
    is always the human's, because the point of an unsettle is that the answer
    it withdraws is one somebody committed to.
    """
    if actor == "human" or kind not in PROPOSABLE_KINDS:
        return False
    if kind in {"unsettle", "invalidate"}:
        return True
    if kind not in {"revise", "settle"}:
        return False
    node = board.node(payload)
    return node is not None and node.answer is not None


def _queue(
    board: _Board, entry: LogEntry, kind: str, payload: Mapping[str, object], key: str
) -> None:
    """Hold a proposed update, and its bytes, until the human says.

    The bytes are kept off the image because the queue the protocol declares
    says what is waiting rather than what it would do -- and because the human
    applies by naming the id, so nothing but this fold ever has to hold them.
    """
    board.pending.append(
        PendingUpdate(
            id=key,
            target=_or_none(payload.get("target")),
            kind=kind,
            superseded=False,
            authored_at=entry.seq,
        )
    )
    board.author_of[key] = entry.actor
    board.proposals[key] = {**payload, "kind": kind}


def _clear(board: _Board, entry: LogEntry) -> None:
    """The human's gesture on the queue: the named entries leave it.

    An applied proposal is remembered as dealt with, so an author withdrawing
    it afterwards learns that the human got there first rather than that no
    such proposal was ever sent -- only the first of those is a disagreement
    anyone has to reconcile. A dismissed one is not: the human said no and the
    author changed its mind, which is two ways of saying the same thing.
    """
    raw = entry.payload.get(PENDING_KEY)
    named = {one for one in raw if isinstance(one, str)} if isinstance(raw, list) else set()
    for item in [one for one in board.pending if one.id in named]:
        board.pending.remove(item)
        board.proposals.pop(item.id, None)
        if entry.kind == APPLY_KIND:
            board.dealt[item.id] = (item, entry.seq)


def _touch(board: _Board, entry: LogEntry, payload: Mapping[str, object]) -> None:
    """When the human last moved a decision.

    What a queued proposal is measured against: one authored before this and
    still waiting is a proposal whose board moved under it, and applying it
    would quietly overwrite the change the human made in between.
    """
    target = payload.get("target")
    if isinstance(target, str):
        board.touched[target] = entry.seq


def _dealt_with(board: _Board, entry: LogEntry, payload: Mapping[str, object]) -> None:
    """The human answered a decision, which deals with every notice standing
    against it: they were told, and then they decided.

    The notices leave the queue and are remembered here, so a withdrawal that
    arrives afterwards can tell "the human already acted on this" from "no such
    notice was ever sent" -- and only the first of those is a conflict.

    A proposal is not a notice and is not dealt with here. Answering a decision
    is not accepting a change to it, so a proposal the human answered around is
    still waiting -- and now waiting against a decision that moved under it,
    which is a disagreement to surface rather than an item to quietly drop.
    """
    target = payload.get("target")
    if not isinstance(target, str):
        return
    for item in [
        one for one in board.pending if one.target == target and one.id not in board.proposals
    ]:
        board.pending.remove(item)
        board.dealt[item.id] = (item, entry.seq)


def _supersede(board: _Board, entry: LogEntry, payload: Mapping[str, object]) -> None:
    """An author withdrawing notices it sent earlier.

    Only its own: a response naming a pending update somebody else authored is
    ignored, because superseding is an author revising itself rather than a way
    to reach into another's queue. A withdrawal of something still queued marks
    it and leaves it in place; one the human has already acted on is a conflict
    and changes nothing on the board.
    """
    raw = payload.get(SUPERSEDES_KEY)
    if not isinstance(raw, list):
        return
    for pending_id in raw:
        if not isinstance(pending_id, str) or board.author_of.get(pending_id) != entry.actor:
            continue
        queued = board.queued(pending_id)
        if queued is not None:
            queued.superseded = True
        elif pending_id in board.dealt:
            item, applied_at = board.dealt[pending_id]
            board.conflicts.append(
                SupersedeConflict(
                    update=item.model_copy(update={"superseded": True}), applied_at=applied_at
                )
            )


def _create_thread(board: _Board, entry: LogEntry) -> None:
    thread_id = _thread_id(entry)
    board.threads[thread_id] = Thread(
        id=thread_id,
        decision=_or_none(entry.payload.get("decision")),
        kind=_text(entry.payload, "kind"),
        title=_text(entry.payload, "title"),
        requires_action=entry.payload.get("requires_action") is True,
        turns=read_turns(entry.payload, entry.actor, entry.timestamp),
    )


def _append_turns(board: _Board, entry: LogEntry) -> None:
    thread_id = _thread_id(entry)
    thread = board.threads.get(thread_id)
    if thread is None:
        thread = Thread(id=thread_id)
        board.threads[thread_id] = thread
    said = read_turns(entry.payload, entry.actor, entry.timestamp)
    offer = _offer(board, entry, thread)
    if offer is not None and said:
        # On the turn that made it, which is the last thing this entry said:
        # liveness is position, so an offer parked anywhere else in the entry
        # would be retired by its own turn the moment it landed.
        said[-1] = said[-1].model_copy(update={"proposal": offer})
    thread.turns = [*thread.turns, *said]
    if thread.state == "closed" and entry.actor == "human":
        thread.state = "open"


def _offer(board: _Board, entry: LogEntry, thread: Thread) -> ConvergedProposal | None:
    """The converged answer this turn offered, or None where there is none to
    make.

    Dropped rather than refused, and only here: the write already carries what
    the agent said to the human, and refusing it over a malformed offer nobody
    has seen yet would throw away the turn to save the offer. Every reason to
    drop is a reason the offer cannot be acted on -- the grill-master asserts
    answers through the queue instead, a session-scoped thread anchors no
    decision to answer, and an option or a decision the board does not carry
    names nothing the page could arm.
    """
    raw = entry.payload.get(PROPOSED_ANSWER_KEY)
    if not isinstance(raw, Mapping) or entry.actor != "thread-agent" or thread.decision is None:
        return None
    try:
        offer = ConvergedProposal.model_validate(dict(raw))
    except ValidationError:
        return None
    if offer.decision != thread.decision:
        return None
    node = board.decisions.get(offer.decision)
    if node is None:
        return None
    if offer.option is not None and offer.option not in {one.id for one in node.options}:
        return None
    return offer


def _close_armed_thread(board: _Board, payload: Mapping[str, object]) -> None:
    """The thread the answer was armed from, closed by the answer itself.

    One entry does both: the decision settles by the ordinary path above and
    the thread reaches its closed state here, so the human never sees a settled
    decision whose thread still asks to be closed. The appender has already
    established that the thread exists and anchors this decision, so a miss
    here is a log the board does not hold rather than a case to decide.
    """
    named = payload.get(FROM_THREAD_KEY)
    thread = board.threads.get(named) if isinstance(named, str) else None
    if thread is not None:
        thread.state = "closed"


_GESTURE_STATE: dict[str, ThreadState] = {
    THREAD_FOLD_KIND: "folded",
    THREAD_PARK_KIND: "parked",
    THREAD_CLOSE_KIND: "closed",
}


def _set_thread_state(board: _Board, entry: LogEntry, kind: str) -> None:
    """The human's gesture on a thread, which is the only thing that ends one.

    A thread nobody opened is nothing to fold, park or close -- the gesture
    names its thread by the channel it arrived on, and a channel holding no
    thread is an entry the fold contributes nothing from rather than one it
    raises over.
    """
    thread = board.threads.get(_thread_id(entry))
    if thread is not None:
        thread.state = _GESTURE_STATE[kind]


def _record_history(
    board: _Board, entry: LogEntry, kind: str, payload: Mapping[str, object]
) -> None:
    """History is keyed by decision id, so an entry naming a node the board
    does not hold contributes none: image 2 crosses whole, and a phantom key
    is an invitation to reason about a decision nobody can answer.

    `why` is the rationale the causing event carried, which is what makes the
    record readable as a reason rather than as a diff."""
    node_id = payload.get("target")
    if not isinstance(node_id, str) or node_id not in board.decisions:
        return
    board.history.setdefault(node_id, []).append(
        HistoryEntry(
            seq=entry.seq,
            timestamp=entry.timestamp,
            kind=kind,
            actor=entry.actor,
            why=_text(payload, "why"),
        )
    )


def _thread_id(entry: LogEntry) -> str:
    return entry.channel


def _answer_text(node: Decision) -> str:
    if node.answer is None:
        return ""
    return node.answer.text or node.answer.option or ""


def _options(raw: object) -> list[Option]:
    if not isinstance(raw, list):
        return []
    return [
        Option(
            id=str(item.get("id", "")),
            text=str(item.get("text", "")),
            pcr=_pcr(item.get("pcr")),
            # An option that predicts nothing carries nothing, so an empty list
            # and an absent field reach the board as the same option.
            puts_in_question=_strings(item.get("puts_in_question")) or None,
        )
        for item in raw
        if isinstance(item, Mapping)
    ]


def _pcr(raw: object) -> list[str] | None:
    values = _strings(raw)
    return values if len(values) == 3 else None


def _string_map(raw: object) -> dict[str, str] | None:
    if not isinstance(raw, Mapping):
        return None
    return {str(key): str(value) for key, value in raw.items()} or None


def _strings(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def _or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
