"""The shapes a grilling session is made of, and the gate a write must pass.

Three contracts live here: the event-log entry, the typed receipt every write
is answered with, and the two context images the projector folds. A *submitted*
event is deliberately laxer than a log entry -- `idempotency_key` is optional on
the wire so that its absence comes back as a typed rejection rather than as a
transport-level error, which is the whole point of a uniform receipt.

The rejection vocabulary is closed. A write is refused for exactly one of the
seven reasons named below, and a caller may switch on that string.
"""

from __future__ import annotations

from collections.abc import Mapping, Set
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MAP_CHANNEL = "map"

Actor = Literal["human", "grill-master", "thread-agent", "backend"]
DecisionStatus = Literal["open", "settled", "invalidated", "stale", "fogged"]
ThreadState = Literal["open", "parked", "folded"]

# The closed rejection vocabulary. `epoch mismatch` is named verbatim by the
# protocol; the other six are this package's wording for the same closed set.
REASON_MISSING_KEY = "missing idempotency key"
REASON_EPOCH_MISMATCH = "epoch mismatch"
REASON_UNKNOWN_KIND = "unknown event kind"
REASON_UNKNOWN_NODE = "unknown node id"
REASON_EMPTY_ANSWER = "answer without option or text"
REASON_THREAD_WITHOUT_TURN = "thread event without turn"
REASON_THREAD_MAP_MUTATION = "map mutation from thread agent"

REJECTION_REASONS = frozenset(
    {
        REASON_MISSING_KEY,
        REASON_EPOCH_MISMATCH,
        REASON_UNKNOWN_KIND,
        REASON_UNKNOWN_NODE,
        REASON_EMPTY_ANSWER,
        REASON_THREAD_WITHOUT_TURN,
        REASON_THREAD_MAP_MUTATION,
    }
)

# The kind registry. It is minimal on purpose: it carries the kinds the
# rejection vocabulary has to discriminate between, and nothing decides a
# payload's inner schema yet. Per-kind payload schemas, the page-derived
# gesture kinds and the status-lane kinds extend this registry; none of them
# narrows it.
MAP_MUTATION_KINDS = frozenset(
    {"add-node", "invalidate", "revise", "settle", "unsettle", "resolve-stale"}
)
THREAD_KINDS = frozenset({"thread-created", "thread-turn"})
NOTICE_KINDS = frozenset({"informational", "elicit-alert", "thinking"})
GESTURE_KINDS = frozenset({"answer"})
LIFECYCLE_KINDS = frozenset({"session-start", "session-end"})
KNOWN_KINDS = MAP_MUTATION_KINDS | THREAD_KINDS | NOTICE_KINDS | GESTURE_KINDS | LIFECYCLE_KINDS

# Kinds whose payload must carry a usable answer. `answer` is the human's
# gesture; `settle` is the agent asserting one.
ANSWER_KINDS = frozenset({"answer", "settle"})


class Strict(BaseModel):
    """Every shape here is a contract on the bytes: an unrecognised field is a
    refusal, not a courtesy."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EventSubmission(Strict):
    """One event as a client offers it. The backend owns `seq`, `epoch` and
    `timestamp`, so a submission may not carry them."""

    kind: str
    actor: Actor
    channel: str = MAP_CHANNEL
    idempotency_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class BatchWrite(Strict):
    """The write endpoint's body: a batch of events under one epoch."""

    epoch: str
    events: list[EventSubmission]


class LogEntry(Strict):
    """One line of the append-only log, never rewritten once appended."""

    seq: int
    epoch: str
    kind: str
    idempotency_key: str
    timestamp: str
    actor: Actor
    channel: str
    payload: dict[str, Any] = Field(default_factory=dict)


class Applied(Strict):
    """What an accepted write actually landed as. `amendments` is required when
    the backend rewrote the submission, so an agent's next turn never reasons
    from a board it did not author."""

    kind: str
    target: str | None
    as_: Literal["sent", "amended"] = Field(default="sent", alias="as")
    amendments: dict[str, str] | None = None


class AcceptedReceipt(Strict):
    status: Literal["accepted"] = "accepted"
    idempotency_key: str
    epoch: str
    seq: int
    applied: Applied


class DuplicateReceipt(Strict):
    """The key already landed. `seq` names where, and nothing was appended."""

    status: Literal["duplicate"] = "duplicate"
    idempotency_key: str
    epoch: str
    seq: int


class RejectedReceipt(Strict):
    """`idempotency_key` echoes the submission's key, so it is null whenever
    the submission carried none — always for the missing-key reason, and also
    for a keyless write refused earlier, e.g. on epoch mismatch."""

    status: Literal["rejected"] = "rejected"
    idempotency_key: str | None
    epoch: str
    reason: str
    detail: str


Receipt = Annotated[
    AcceptedReceipt | DuplicateReceipt | RejectedReceipt,
    Field(discriminator="status"),
]


class Option(Strict):
    id: str
    text: str
    pcr: list[str] | None = Field(default=None, min_length=3, max_length=3)


class Answer(Strict):
    option: str | None = None
    text: str | None = None


class Decision(Strict):
    """The same node shape in the handoff and in both images; the status and
    answer fields exist only in the images."""

    id: str
    short: str = ""
    title: str = ""
    prereqs: list[str] = Field(default_factory=list)
    body: str = ""
    options: list[Option] = Field(default_factory=list)
    mandate: dict[str, str] | None = None
    talk: dict[str, str] | None = None
    fog_until: str | None = Field(default=None, alias="fogUntil")
    fog_title: str | None = Field(default=None, alias="fogTitle")
    status: DecisionStatus = "open"
    answer: Answer | None = None


class ThreadTurn(Strict):
    who: Actor
    text: str
    timestamp: str


class Thread(Strict):
    id: str
    decision: str | None = None
    kind: str = ""
    title: str = ""
    requires_action: bool = False
    state: ThreadState = "open"
    turns: list[ThreadTurn] = Field(default_factory=list)


class SettledEntry(Strict):
    id: str
    answer: str


class PendingUpdate(Strict):
    id: str
    target: str
    kind: str
    superseded: bool
    authored_at: int


class HistoryEntry(Strict):
    seq: int
    timestamp: str
    kind: str
    actor: str
    why: str


class Image1(Strict):
    """The current map snapshot: a pure fold, byte-identical for a given log."""

    epoch: str
    seq: int
    decisions: list[Decision] = Field(default_factory=list)
    frontier: list[str] = Field(default_factory=list)
    settled: list[SettledEntry] = Field(default_factory=list)
    threads: list[Thread] = Field(default_factory=list)
    pending: list[PendingUpdate] = Field(default_factory=list)


class Image2(Image1):
    """Image 1 plus per-decision evolution history. This is the reverse handoff,
    and it crosses to the grill-master whole."""

    history: dict[str, list[HistoryEntry]] = Field(default_factory=dict)


class SessionStatus(Strict):
    """The cheap check: epoch and position, answered from memory."""

    epoch: str
    seq: int


class StateRead(Strict):
    epoch: str
    seq: int
    image1: Image1


class UpdateRead(Strict):
    """Entries past the cursor, plus the position they were read at -- an empty
    tail still tells the caller where the log now is."""

    epoch: str
    seq: int
    entries: list[LogEntry]


def rejection_reason(submission: EventSubmission, known_nodes: Set[str]) -> tuple[str, str] | None:
    """Judge one submission's content, returning `(reason, detail)` or None.

    The missing-key and epoch-mismatch reasons are decided by the appender,
    which is what holds the key index and the epoch; everything else is a
    property of the submission itself and is decided here.
    """
    if submission.kind not in KNOWN_KINDS:
        return (REASON_UNKNOWN_KIND, f"{submission.kind!r} is not an event kind of this protocol")

    if submission.kind in MAP_MUTATION_KINDS and (
        submission.actor == "thread-agent" or submission.channel != MAP_CHANNEL
    ):
        return (
            REASON_THREAD_MAP_MUTATION,
            f"{submission.kind!r} mutates the map, which only the grill-master authors on "
            f"the {MAP_CHANNEL!r} channel; got actor {submission.actor!r} on channel "
            f"{submission.channel!r}",
        )

    if submission.kind in THREAD_KINDS:
        return _thread_turn_problem(submission)

    target = submission.payload.get("target")
    if isinstance(target, str) and submission.kind != "add-node" and target not in known_nodes:
        return (REASON_UNKNOWN_NODE, f"no decision node {target!r} exists in this session")

    if submission.kind in ANSWER_KINDS or "answer" in submission.payload:
        return _answer_problem(submission.payload.get("answer"))

    return None


def _thread_turn_problem(submission: EventSubmission) -> tuple[str, str] | None:
    """A thread event says something or it says nothing. The page speaks in a
    `turns[]` array of who/text pairs; a backend-authored reply may carry bare
    text. One reader handles both, because a backend written against only one
    of them passes a scripted check and rejects the real page."""
    turns = submission.payload.get("turns")
    said = bool(submission.payload.get("text"))
    if isinstance(turns, list):
        said = said or any(isinstance(t, Mapping) and t.get("text") for t in turns)
    if said:
        return None
    return (
        REASON_THREAD_WITHOUT_TURN,
        f"{submission.kind!r} carries neither a non-empty turns[] entry nor bare text",
    )


def _answer_problem(answer: object) -> tuple[str, str] | None:
    if isinstance(answer, Mapping) and (answer.get("option") or answer.get("text")):
        return None
    return (
        REASON_EMPTY_ANSWER,
        "an answer must carry an option id, answer text, or both",
    )
