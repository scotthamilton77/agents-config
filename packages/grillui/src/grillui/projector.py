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
| `thread-fold`   | its channel's thread is `folded`; no decision moves            |
| `thread-park`   | its channel's thread is `parked`; no decision moves            |

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

`informational` and `elicit-alert` are the queue of what the human has not dealt
with yet, which is the `pending` array. Nothing here takes an item off that
queue, because nothing yet applies or supersedes one: a queue that emptied
itself on a rule nobody wrote would lose notices the human never saw.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from grillui.schemas import (
    FOLD_KIND,
    SESSION_START_KIND,
    THREAD_FOLD_KIND,
    THREAD_PARK_KIND,
    Answer,
    Decision,
    FoldedThreadStub,
    HistoryEntry,
    Image1,
    Image2,
    LogEntry,
    Option,
    PendingUpdate,
    SettledEntry,
    Thread,
    ThreadProjection,
    ThreadStub,
    read_turns,
)

_NOTICE_KINDS = frozenset({"informational", "elicit-alert"})
_REVISABLE_TEXT = ("short", "title", "body")


@dataclass
class _Board:
    """The fold's running state, keyed the way the images are read."""

    decisions: dict[str, Decision] = field(default_factory=dict)
    threads: dict[str, Thread] = field(default_factory=dict)
    history: dict[str, list[HistoryEntry]] = field(default_factory=dict)
    pending: list[PendingUpdate] = field(default_factory=list)

    def node(self, payload: Mapping[str, object]) -> Decision | None:
        target = payload.get("target")
        return self.decisions.get(target) if isinstance(target, str) else None


def fold(epoch: str, entries: Sequence[LogEntry]) -> Image2:
    """Fold the log into image 2. Image 1 is this, minus history."""
    board = _Board()
    seq = 0

    for entry in entries:
        seq = entry.seq
        if entry.kind == FOLD_KIND:
            # The gesture is one entry, so there is no state in which half of it
            # landed: either the log has it and every sub-update applies, or it
            # does not and none of them does.
            for index, update in enumerate(_updates(entry)):
                key = f"{entry.idempotency_key}#{index}"
                _apply(board, entry, str(update.get("kind")), update, key)
        else:
            _apply(board, entry, entry.kind, entry.payload, entry.idempotency_key)

    settled = [
        SettledEntry(id=node.id, answer=_answer_text(node))
        for node in board.decisions.values()
        if node.status == "settled"
    ]
    settled_ids = {item.id for item in settled}
    for node in board.decisions.values():
        if node.status == "open" and node.fog_until and node.fog_until not in settled_ids:
            node.status = "fogged"
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
    """
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
    elif kind in {THREAD_FOLD_KIND, THREAD_PARK_KIND}:
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


def conclusion_of(thread: Thread) -> str | None:
    """A folded thread's conclusion: the turn whose content was applied to the
    board. An open or parked thread has reached none.

    One reader, because the conclusion is quoted in three places -- the stub a
    sibling thread's agent sees, the dispatch that hands it to the grill-master,
    and the terminal result -- and three readers is how they come to disagree
    about what a thread concluded.
    """
    if thread.state != "folded" or not thread.turns:
        return None
    return thread.turns[-1].text


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
    thread.turns = [*thread.turns, *read_turns(entry.payload, entry.actor, entry.timestamp)]


def _set_thread_state(board: _Board, entry: LogEntry, kind: str) -> None:
    """The human's gesture on a thread, which is the only thing that ends one.

    A thread nobody opened is nothing to fold or park -- the gesture names its
    thread by the channel it arrived on, and a channel holding no thread is an
    entry the fold contributes nothing from rather than one it raises over.
    """
    thread = board.threads.get(_thread_id(entry))
    if thread is not None:
        thread.state = "folded" if kind == THREAD_FOLD_KIND else "parked"


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
