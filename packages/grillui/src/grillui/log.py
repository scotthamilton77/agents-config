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
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from grillui.schemas import (
    MAP_CHANNEL,
    REASON_EPOCH_MISMATCH,
    REASON_MISSING_KEY,
    STATUS_KIND,
    AcceptedReceipt,
    Applied,
    DuplicateReceipt,
    EventSubmission,
    LogEntry,
    RejectedReceipt,
    rejection_reason,
)

if TYPE_CHECKING:
    from grillui.schemas import Receipt

LOG_FILE = "log.jsonl"
IMAGE1_FILE = "image1.json"
IMAGE2_FILE = "image2.json"


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
            minted = entry.payload.get("target") or entry.payload.get("id")
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

    def submit(self, batch: Sequence[EventSubmission], epoch: str) -> list[Receipt]:
        """Judge and append a batch under one epoch, one receipt per event in
        submission order. The lock spans the batch so the sequence a receipt
        names is the sequence the entry actually landed at."""
        with self._lock:
            return [self._submit_one(event, epoch) for event in batch]

    def emit_status(self, phase: str, detail: str, channel: str = MAP_CHANNEL) -> LogEntry:
        """Append one backend-authored status entry, judged by nothing.

        The lane is mechanical: it carries no client key, presents no epoch and
        never waits on a model, so it cannot be refused and cannot be slow. It
        is safe to call while already holding the lock -- which is where a
        status reporting on its own append is emitted from.
        """
        with self._lock:
            entry = LogEntry(
                seq=self._index.last_seq + 1,
                epoch=self.epoch,
                kind=STATUS_KIND,
                idempotency_key=f"{STATUS_KIND}-{uuid4().hex}",
                timestamp=_now(),
                actor="backend",
                channel=channel,
                payload={"phase": phase, "detail": detail},
            )
            self._append(entry)
            return entry

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
                idempotency_key=key, epoch=self.epoch, reason=reason, detail=detail
            )

        entry = LogEntry(
            seq=self._index.last_seq + 1,
            epoch=self.epoch,
            kind=event.kind,
            idempotency_key=key,
            timestamp=_now(),
            actor=event.actor,
            channel=event.channel,
            payload=event.payload,
        )
        self._append(entry)
        return AcceptedReceipt(
            idempotency_key=key,
            epoch=self.epoch,
            seq=entry.seq,
            applied=Applied(kind=entry.kind, target=_target_of(entry)),
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
        if not self.path.exists():
            return
        # ponytail: one linear read at startup; a session log is human-paced and
        # bounded by one grilling, so nothing here needs an on-disk index.
        lines = [
            line for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        for position, line in enumerate(lines):
            try:
                entry = LogEntry.model_validate_json(line)
            except ValueError as error:
                if position == len(lines) - 1:
                    # A torn final line is what a crash between write and fsync
                    # leaves behind. The event it held has no receipt anywhere,
                    # so dropping it loses nothing a client will not retry
                    # under its own idempotency key.
                    break
                raise CorruptLogError(self.path, position + 1) from error
            self._entries.append(entry)
            self._index.absorb(entry)


def _target_of(entry: LogEntry) -> str | None:
    """What the entry landed on: a node id for the map, the thread id otherwise."""
    target = entry.payload.get("target")
    if isinstance(target, str):
        return target
    return None if entry.channel == "map" else entry.channel
