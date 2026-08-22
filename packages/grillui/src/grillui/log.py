"""The append-only session log: the single source of truth for one grilling.

The session *directory* is the session's identity and outlives any process
serving it. Its fixed file names are `log.jsonl`, `image1.json`, `image2.json`,
`handoff.json` and `result.json`; this module owns the first.

An *epoch* identifies one process's tenure over that directory and is minted at
construction, so a restart against an existing directory mints a new epoch and
continues the sequence that directory already reached. Sequence numbers are
never reset and never client-supplied.

Nothing here folds a projection. The appender's own indexes -- the idempotency
key index, and the decisions that exist with the options each of them offers --
are the questions a write has to be judged against, and they are maintained
entry by entry so that judging a write never reads a file.

One thing here does reach for the projector: an add-node's receipt echoes the
node it minted, built by the same reader the fold will use on the same durable
payload. Two readers for one node is how a receipt and a board come to disagree
about what an agent just wrote.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator, Sequence, Set
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from grillui.projector import Proposed, node_from_payload, queue
from grillui.schemas import (
    APPLY_KIND,
    FOLD_SHAPED,
    MAP_CHANNEL,
    PENDING_KEY,
    PROPOSABLE_KINDS,
    QUEUE_GESTURE_KINDS,
    REASON_EPOCH_MISMATCH,
    REASON_MISSING_KEY,
    REASON_PENDING_CONFLICT,
    REASON_UNKNOWN_PENDING,
    SESSION_START_KIND,
    STATUS_KIND,
    AcceptedReceipt,
    Applied,
    Decision,
    DuplicateReceipt,
    EventSubmission,
    FoldOutcome,
    LogEntry,
    RejectedReceipt,
    fold_outcomes,
    mint_targets,
    option_ids,
    rejection_reason,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any, Literal

    from grillui.schemas import Receipt

LOG_FILE = "log.jsonl"
IMAGE1_FILE = "image1.json"
IMAGE2_FILE = "image2.json"
HANDOFF_FILE = "handoff.json"
RESULT_FILE = "result.json"


class CorruptLogError(RuntimeError):
    """A malformed line before the log's end. Unlike a torn final line, this is
    not a crash artifact the appender could have produced, so resuming over it
    would silently drop accepted entries."""

    def __init__(self, path: Path, line_number: int) -> None:
        super().__init__(f"{path} line {line_number} is not a valid log entry")


def _now() -> str:
    """Backend clock at append time, to millisecond precision."""
    return datetime.now(UTC).isoformat(timespec="milliseconds")


# The two kinds that state what a decision is: one mints it, the other replaces
# what it offers. Both are what the index reads a node's options from.
NODE_STATING_KINDS = frozenset({"add-node", "revise"})


@dataclass
class LogIndex:
    """What a write is judged against, folded forward one entry at a time."""

    last_seq: int = 0
    keys: dict[str, int] = field(default_factory=dict)
    # Every decision the log has stated, mapped to the option ids it offers.
    # The options are here rather than only in the fold because an answer's
    # option is judged at append time: an answer onto an option the decision
    # never offered settles the board onto a choice nobody can read back.
    nodes: dict[str, frozenset[str]] = field(default_factory=dict)
    # Thread id to the decision it anchors, or None for a session-scoped one.
    # The anchor is here rather than only in the fold because an answer's
    # provenance is judged at append time: whether the thread this answer was
    # armed from is the thread that asked this question decides whether the
    # entry lands at all.
    threads: dict[str, str | None] = field(default_factory=dict)

    def absorb(self, entry: LogEntry) -> None:
        self.last_seq = entry.seq
        self.keys[entry.idempotency_key] = entry.seq
        if entry.kind == "thread-created":
            anchor = entry.payload.get("decision")
            self.threads[entry.channel] = anchor if isinstance(anchor, str) else None
        elif entry.kind in NODE_STATING_KINDS:
            self._state_node(entry.payload)
        elif entry.kind == SESSION_START_KIND:
            # A decision the briefing seeded is a decision on the board, so an
            # answer naming it is judged against the same node set as one
            # naming a node an agent minted later. Missing them here would
            # refuse the human's first answer of the session as an unknown node.
            plan = entry.payload.get("plan")
            decisions = plan.get("decisions", []) if isinstance(plan, dict) else []
            for decision in decisions:
                if isinstance(decision, dict):
                    self._state_node(decision)
        elif entry.kind in FOLD_SHAPED:
            # A node minted inside a fold is a node the board has, so an update
            # after the gesture may name it. Missing it here would refuse the
            # agent's next turn against a decision the human can already see.
            for update in entry.payload.get("updates", []):
                if isinstance(update, dict) and update.get("kind") in NODE_STATING_KINDS:
                    self._state_node(update)

    def _state_node(self, payload: Mapping[str, Any]) -> None:
        """The node this payload states, with the options it offers. A revise
        that supplies no options leaves the ones the decision already has."""
        minted = payload.get("target") or payload.get("id")
        if isinstance(minted, str) and (
            minted not in self.nodes or payload.get("options") is not None
        ):
            self.nodes[minted] = option_ids(payload)


class SessionLog:
    """One process's tenure over one session directory.

    Reading the log happens once, at construction. Everything after that is
    answered from memory, which is what lets the cheap status check stay cheap
    under a log of any size.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / LOG_FILE
        self.epoch = uuid4().hex
        # Re-entrant: the status lane reports on the append it rides alongside,
        # and is emitted from inside that same lock. A plain lock would deadlock
        # the session on exactly the path whose job is to keep it alive.
        self._lock = threading.RLock()
        self._entries: list[LogEntry] = []
        self._index = LogIndex()
        self._load()

    @property
    def seq(self) -> int:
        """The position the log has reached, in memory."""
        return self._index.last_seq

    def entries(self) -> list[LogEntry]:
        """A stable snapshot: taken under the append lock, so a reader folding
        it never sees a batch half-landed."""
        with self._lock:
            return list(self._entries)

    def entries_after(self, cursor: int) -> list[LogEntry]:
        with self._lock:
            return [entry for entry in self._entries if entry.seq > cursor]

    @contextmanager
    def appending(self) -> Iterator[None]:
        """Hold the append lock across more than one append.

        The status lane rides the append it reports on: emitting the lane's
        entries under the lock that appended the human turn is what makes it
        impossible for anything else to land between the turn and the word
        about it. Re-entrancy is what allows it -- `submit` and `emit_status`
        take the same lock from inside this block.
        """
        with self._lock:
            yield

    def submit(self, batch: Sequence[EventSubmission], epoch: str) -> list[Receipt]:
        """Judge and append a batch under one epoch, one receipt per event in
        submission order. The lock spans the batch so the sequence a receipt
        names is the sequence the entry actually landed at."""
        with self._lock:
            return [self._submit_one(event, epoch) for event in batch]

    def record(self, kind: str, payload: dict[str, Any], channel: str = MAP_CHANNEL) -> LogEntry:
        """Append one backend-authored entry, judged by nothing.

        The backend is the authority, so its own entries present no epoch and
        carry no client key -- they cannot be refused, and there is nobody to
        return a receipt to. Every backend-authored kind lands here: the status
        lane, and the lifecycle pair that brackets the session.

        Safe to call while already holding the append lock, which is where a
        status reporting on its own append is emitted from.
        """
        with self._lock:
            entry = LogEntry(
                seq=self._index.last_seq + 1,
                epoch=self.epoch,
                kind=kind,
                idempotency_key=f"{kind}-{uuid4().hex}",
                timestamp=_now(),
                actor="backend",
                channel=channel,
                payload=payload,
            )
            self._append(entry)
            return entry

    def emit_status(
        self, phase: str, detail: str, channel: str = MAP_CHANNEL, *, tier: str | None = None
    ) -> LogEntry:
        """Append one status entry.

        The lane is mechanical: it never waits on a model, so it cannot be slow.

        `tier` names who is taking the turn and is absent from a phase that has
        no tier to name; a page reading the lane learns which tier it is waiting
        on from the entry itself rather than from a lookup it could get wrong.
        """
        payload = {"phase": phase, "detail": detail}
        if tier is not None:
            payload["tier"] = tier
        return self.record(STATUS_KIND, payload, channel)

    def _submit_one(self, event: EventSubmission, epoch: str) -> Receipt:
        if epoch != self.epoch:
            return RejectedReceipt(
                idempotency_key=event.idempotency_key,
                epoch=self.epoch,
                reason=REASON_EPOCH_MISMATCH,
                detail=f"server epoch is {self.epoch!r}, presented epoch was {epoch!r}",
            )

        key = event.idempotency_key
        if not key:
            return RejectedReceipt(
                idempotency_key=None,
                epoch=self.epoch,
                reason=REASON_MISSING_KEY,
                detail="every client-originated event carries an idempotency key",
            )

        # Deliberately ahead of content validation: a replayed key is answered
        # from where it landed, whatever body the replay carries.
        landed = self._index.keys.get(key)
        if landed is not None:
            return DuplicateReceipt(idempotency_key=key, epoch=self.epoch, seq=landed)

        problem = rejection_reason(event, self._index.nodes, self._index.threads)
        queued = self._queue() if event.kind in QUEUE_GESTURE_KINDS else {}
        if problem is None and event.kind in QUEUE_GESTURE_KINDS:
            problem = _queue_gesture_problem(event, queued)
        if problem is not None:
            reason, detail = problem
            return RejectedReceipt(
                idempotency_key=key,
                epoch=self.epoch,
                reason=reason,
                detail=detail,
                # A refused fold still says what became of each sub-update: the
                # refused one names its reason, and the rest name the veto.
                updates=(
                    fold_outcomes(event, self._index.nodes) if event.kind in FOLD_SHAPED else None
                ),
            )

        previous = self._index.last_seq
        entry = LogEntry(
            seq=previous + 1,
            epoch=self.epoch,
            kind=event.kind,
            idempotency_key=key,
            timestamp=_now(),
            actor=event.actor,
            channel=event.channel,
            # Minted before the append, so the id the receipt echoes and the id
            # the projector materialises are the same durable bytes.
            payload=_resolve(mint_targets(event.payload, event.kind, previous + 1), event, queued),
        )
        self._append(entry)
        applied = _applied_updates(entry, previous, self._queued_ids(entry))
        as_, amendments = _amendment(entry.payload, previous, applied)
        return AcceptedReceipt(
            idempotency_key=key,
            epoch=self.epoch,
            seq=entry.seq,
            applied=Applied.model_validate(
                {
                    "kind": entry.kind,
                    "target": _target_of(entry),
                    "as": as_,
                    "amendments": amendments,
                }
            ),
            node=_echoed_node(entry.kind, entry.payload),
            updates=applied,
        )

    def _queue(self) -> dict[str, Proposed]:
        """The proposals waiting for the human, as of right now.

        Folded rather than indexed, because whether an update waits is a
        property of the board at the moment it arrived and this appender holds
        no board. One reader for the question means the queue a receipt is
        judged against and the queue the page is shown are the same answer.

        ponytail: one fold per queue gesture and per gesture that could produce
        one, which is a human-paced act over a log bounded by one grilling.
        """
        return queue(self._entries)

    def _queued_ids(self, entry: LogEntry) -> set[str]:
        """Which of this entry's updates went to the queue instead of the board.

        Read after the append, from the fold that now includes the entry, so the
        receipt cannot disagree with the board about what an agent's turn did --
        it is the same answer, read once.
        """
        if entry.actor == "human" or not (
            entry.kind in FOLD_SHAPED or entry.kind in PROPOSABLE_KINDS
        ):
            return set()
        # Exact key or key#N only: keys are client-chosen, so a bare
        # startswith would claim another entry's "k1a" for this entry's "k1".
        own = (entry.idempotency_key, f"{entry.idempotency_key}#")
        return {one for one in self._queue() if one == own[0] or one.startswith(own[1])}

    def _append(self, entry: LogEntry) -> None:
        """Durable first, in-memory second: an entry a caller has a receipt for
        is on disk before any projection could run against it."""
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json(by_alias=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._entries.append(entry)
        self._index.absorb(entry)

    def _load(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        entries = read_entries(self.path)
        for entry in entries:
            self._entries.append(entry)
            self._index.absorb(entry)
        self._discard_torn_tail(len(entries))

    def _discard_torn_tail(self, kept: int) -> None:
        """Remove a forgiven torn line from disk, not just from memory.

        Appends open the file in append mode, so bytes left after the last
        intact entry would sit in front of the next entry written — turning the
        forgivable torn *final* line into interior corruption a later load
        refuses, or fusing with the next entry into one unreadable line. Only
        the process holding the tenure may do this; the shared reader stays
        read-only.
        """
        if not self.path.exists():
            return
        raw = self.path.read_bytes()
        offset = 0
        seen = 0
        for line in raw.splitlines(keepends=True):
            if seen == kept:
                break
            offset += len(line)
            if line.strip():
                seen += 1
        if offset < len(raw):
            with self.path.open("rb+") as handle:
                handle.truncate(offset)


def read_entries(path: Path) -> list[LogEntry]:
    """The log as it is on disk, without claiming a tenure over it.

    The recovery source, so this is the one reader: a resuming process and a
    capture run pointed at a finished session read the same bytes by the same
    rules, including which torn line is forgivable.
    """
    if not path.exists():
        return []
    # ponytail: one linear read; a session log is human-paced and bounded by one
    # grilling, so nothing here needs an on-disk index.
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    entries: list[LogEntry] = []
    for position, line in enumerate(lines):
        try:
            entries.append(LogEntry.model_validate_json(line))
        except ValueError as error:
            if position == len(lines) - 1:
                # A torn final line is what a crash between write and fsync
                # leaves behind. The event it held has no receipt anywhere, so
                # dropping it loses nothing a client will not retry under its
                # own idempotency key.
                break
            raise CorruptLogError(path, position + 1) from error
    return entries


def _target_of(entry: LogEntry) -> str | None:
    """What the entry landed on: a node id for the map, the thread id otherwise."""
    target = entry.payload.get("target")
    if isinstance(target, str):
        return target
    return None if entry.channel == "map" else entry.channel


def _echoed_node(kind: str, payload: Mapping[str, Any]) -> Decision | None:
    """The materialised node an add-node's receipt echoes back.

    The agent chose the question and the options but not the id, so without the
    echo it has no way to revise other decisions against the node it just asked
    for -- it would have to read the whole board back to find out what its own
    write became.
    """
    target = payload.get("target")
    if kind != "add-node" or not isinstance(target, str):
        return None
    return node_from_payload(payload, target)


def _amendment(
    payload: Mapping[str, Any], previous_seq: int, updates: list[FoldOutcome] | None = None
) -> tuple[Literal["sent", "amended"], dict[str, str] | None]:
    """Whether the board had moved under an update between authoring and apply.

    An agent authors against the board it was dispatched with and says so in
    `basis`; by the time a human folds the turn, the board may have advanced.
    The update still applies -- to the board as it now is -- and the receipt
    says so, because an undocumented rewrite makes the agent's next turn reason
    from a board it did not author.
    """
    amendments: dict[str, str] = {}
    basis = payload.get("basis")
    if isinstance(basis, int) and not isinstance(basis, bool) and basis != previous_seq:
        amendments["basis"] = f"authored against seq {basis}, applied against seq {previous_seq}"
    for index, one in enumerate(updates or []):
        for name, rewrite in (one.amendments or {}).items():
            amendments[f"updates.{index}.{name}"] = rewrite
    return ("amended", amendments) if amendments else ("sent", None)


def _pending_ids(payload: Mapping[str, Any]) -> list[str]:
    """The queue entries a gesture names, in the order it named them.

    Deduplicated: a repeated id must not materialise the same proposal twice
    into the gesture's updates and double-apply it on the walk.
    """
    raw = payload.get(PENDING_KEY)
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(one for one in raw if isinstance(one, str)))


def _queue_gesture_problem(
    event: EventSubmission, queued: Mapping[str, Proposed]
) -> tuple[str, str] | None:
    """Judge an apply or a dismiss against the queue it is acting on.

    An id the queue does not hold is refused rather than skipped: a human told
    their apply landed when the proposal had already been applied, dismissed or
    never sent is exactly the acknowledgement over a silent no-op this protocol
    exists to make impossible.

    A proposal whose target the human changed while it waited is refused too,
    and only on an apply -- dismissing one changes nothing, so there is nothing
    to disagree with. Nothing here resolves the disagreement: the proposal stays
    queued, and what to do about it is a conversation between the human and the
    agent that wrote it.
    """
    for pending_id in _pending_ids(event.payload):
        found = queued.get(pending_id)
        if found is None:
            return (
                REASON_UNKNOWN_PENDING,
                f"no proposal {pending_id!r} is waiting in this session's queue; it was "
                f"already applied or dismissed, or it was never sent",
            )
        if found.conflicted and event.kind == APPLY_KIND:
            return (
                REASON_PENDING_CONFLICT,
                f"proposal {pending_id!r} was authored at sequence {found.pending.authored_at} "
                f"against decision {found.pending.target!r}, which the human has changed "
                f"since; it stays queued rather than overwriting that change",
            )
    return None


def _resolve(
    payload: dict[str, Any], event: EventSubmission, queued: Mapping[str, Proposed]
) -> dict[str, Any]:
    """An apply, with the proposals it named resolved into the updates it carries.

    Materialised before the append for the same reason a minted node id is: the
    receipt, the fold and the durable entry then read one set of bytes. Those
    bytes are the authoring agent's own, taken out of the queue rather than off
    the wire, so applying is the human choosing *that* an update lands and never
    choosing what it says.
    """
    if event.kind != APPLY_KIND:
        return payload
    return {**payload, "updates": [queued[one].update for one in _pending_ids(payload)]}


def _applied_updates(
    entry: LogEntry, previous_seq: int, queued: Set[str]
) -> list[FoldOutcome] | None:
    """What became of each update this entry carried.

    A refusal cannot reach here -- the gesture is accepted whole or not at all --
    so every outcome is `applied` or `queued`, and which it is comes from the
    fold that has already absorbed the entry rather than from a second judgment
    made here. A lone update that went to the queue gets an outcome too: without
    one its receipt would say a decision moved when none did.
    """
    if entry.kind in FOLD_SHAPED:
        updates = [
            (f"{entry.idempotency_key}#{index}", update)
            for index, update in enumerate(entry.payload.get("updates", []))
        ]
    elif queued:
        updates = [(entry.idempotency_key, {**entry.payload, "kind": entry.kind})]
    else:
        return None
    outcomes = []
    for pending_id, update in updates:
        kind = str(update.get("kind"))
        as_, amendments = _amendment(update, previous_seq)
        outcomes.append(
            FoldOutcome.model_validate(
                {
                    "kind": kind,
                    "target": update.get("target"),
                    "status": "queued" if pending_id in queued else "applied",
                    "as": as_,
                    "amendments": amendments,
                    "node": _echoed_node(kind, update),
                }
            )
        )
    return outcomes
