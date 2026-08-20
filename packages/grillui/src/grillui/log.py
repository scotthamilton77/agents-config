"""The append-only session log: the single source of truth for one grilling.

The session *directory* is the session's identity and outlives any process
serving it. Its fixed file names are `log.jsonl`, `image1.json`, `image2.json`,
`handoff.json` and `result.json`; this module owns the first.

An *epoch* identifies one process's tenure over that directory and is minted at
construction, so a restart against an existing directory mints a new epoch and
continues the sequence that directory already reached. Sequence numbers are
never reset and never client-supplied.

Nothing here folds a projection. The appender's own indexes -- the idempotency
key index and the set of node ids that exist -- are the two questions a write
has to be judged against, and they are maintained entry by entry so that judging
a write never reads a file.

One thing here does reach for the projector: an add-node's receipt echoes the
node it minted, built by the same reader the fold will use on the same durable
payload. Two readers for one node is how a receipt and a board come to disagree
about what an agent just wrote.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from grillui.projector import node_from_payload
from grillui.schemas import (
    FOLD_KIND,
    MAP_CHANNEL,
    REASON_EPOCH_MISMATCH,
    REASON_MISSING_KEY,
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


@dataclass
class LogIndex:
    """What a write is judged against, folded forward one entry at a time."""

    last_seq: int = 0
    keys: dict[str, int] = field(default_factory=dict)
    nodes: set[str] = field(default_factory=set)

    def absorb(self, entry: LogEntry) -> None:
        self.last_seq = entry.seq
        self.keys[entry.idempotency_key] = entry.seq
        if entry.kind == "add-node":
            self._mint(entry.payload)
        elif entry.kind == SESSION_START_KIND:
            # A decision the briefing seeded is a decision on the board, so an
            # answer naming it is judged against the same node set as one
            # naming a node an agent minted later. Missing them here would
            # refuse the human's first answer of the session as an unknown node.
            plan = entry.payload.get("plan")
            decisions = plan.get("decisions", []) if isinstance(plan, dict) else []
            for decision in decisions:
                if isinstance(decision, dict):
                    self._mint(decision)
        elif entry.kind == FOLD_KIND:
            # A node minted inside a fold is a node the board has, so an update
            # after the gesture may name it. Missing it here would refuse the
            # agent's next turn against a decision the human can already see.
            for update in entry.payload.get("updates", []):
                if isinstance(update, dict) and update.get("kind") == "add-node":
                    self._mint(update)

    def _mint(self, payload: Mapping[str, Any]) -> None:
        minted = payload.get("target") or payload.get("id")
        if isinstance(minted, str):
            self.nodes.add(minted)


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

        problem = rejection_reason(event, self._index.nodes)
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
                    fold_outcomes(event, self._index.nodes) if event.kind == FOLD_KIND else None
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
            payload=mint_targets(event.payload, event.kind, previous + 1),
        )
        self._append(entry)
        applied = _applied_updates(entry, previous)
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
        for entry in read_entries(self.path):
            self._entries.append(entry)
            self._index.absorb(entry)


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


def _applied_updates(entry: LogEntry, previous_seq: int) -> list[FoldOutcome] | None:
    """A fold's sub-updates as they landed. Reached only once the gesture is
    accepted whole, so every outcome here is an applied one."""
    if entry.kind != FOLD_KIND:
        return None
    outcomes = []
    for update in entry.payload.get("updates", []):
        kind = str(update.get("kind"))
        as_, amendments = _amendment(update, previous_seq)
        outcomes.append(
            FoldOutcome.model_validate(
                {
                    "kind": kind,
                    "target": update.get("target"),
                    "status": "applied",
                    "as": as_,
                    "amendments": amendments,
                    "node": _echoed_node(kind, update),
                }
            )
        )
    return outcomes
