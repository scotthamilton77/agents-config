"""The shapes a grilling session is made of, and the gate a write must pass.

Four contracts live here: the event-log entry, the per-kind payload shapes, the
typed receipt every write is answered with, and the two context images the
projector folds. A *submitted* event is deliberately laxer than a log entry --
`idempotency_key` is optional on the wire so that its absence comes back as a
typed rejection rather than as a transport-level error, which is the whole point
of a uniform receipt.

The rejection vocabulary is closed. A write is refused for exactly one of the
seven reasons named below, and a caller may switch on that string. That closure
is what decides where a malformed payload lands: a payload fault one of the
seven names is a typed receipt (an answer carrying neither option nor text, a
thread event carrying no turn), and a payload fault none of them names -- an
add-node with one option, an invalidate with no rationale -- is refused at the
envelope, whole batch, the same way an unknown envelope field is. Inventing an
eighth reason to make it a receipt would break every caller switching on the
vocabulary.

The envelope is closed and the payload is not: an unrecognised field on a
submission is a refusal, while an unrecognised field *inside* a payload is
carried through untouched, so a page or an agent may ship a field a later
version reads without this one refusing it.

The handoff and the terminal result bracket the session and are closed at every
level, payloads included. Neither is a running conversation between two ends
that may extend ahead of each other: the handoff is written once and read once,
and a field the backend does not understand there is a briefing the human
believes was delivered and was not.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from typing import Annotated, Any, Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAP_CHANNEL = "map"

Actor = Literal["human", "grill-master", "thread-agent", "backend"]
ACTORS: frozenset[str] = frozenset(get_args(Actor))
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

# The kind registry: the closed set of kinds a client may submit.
#
# A kind is a map mutation when applying it changes a decision on the board,
# which is what the sole-author rule is about -- `elicit-alert` is one because
# its blocking flag locks a decision, and `fold` is one because it carries map
# mutations inside it. `informational` is not: it addresses the human and
# leaves every decision as it was.
#
# The thinking indicator is deliberately absent. It is not a kind an agent
# sends: the status lane fires it mechanically the moment a turn is picked up,
# so a client offering one is refused as an unknown kind rather than believed.
MAP_MUTATION_KINDS = frozenset(
    {
        "add-node",
        "invalidate",
        "revise",
        "settle",
        "unsettle",
        "resolve-stale",
        "elicit-alert",
        "fold",
    }
)
THREAD_KINDS = frozenset({"thread-created", "thread-turn"})
NOTICE_KINDS = frozenset({"informational", "elicit-alert"})
GESTURE_KINDS = frozenset({"answer"})

# The lifecycle pair. `session-start` is the backend's alone: it is the entry
# that strips the handoff file of its authority, so a client that could send one
# could reseed a board mid-session. `session-end` is a human gesture; an agent
# that judges `stop_when` satisfied says so to the human and does not end the
# grilling itself.
SESSION_START_KIND = "session-start"
SESSION_END_KIND = "session-end"
LIFECYCLE_KINDS = frozenset({SESSION_START_KIND, SESSION_END_KIND})
KNOWN_KINDS = MAP_MUTATION_KINDS | THREAD_KINDS | NOTICE_KINDS | GESTURE_KINDS | LIFECYCLE_KINDS

# One human gesture applying a conversational turn's declared impact -- a
# revise, an add-node and an informational together -- all of it or none of it.
# Atomicity is structural rather than transactional: the whole gesture is one
# log entry carrying its sub-updates in order, so there is no state in which
# half of it landed. A fold does not nest, and it carries no thread event: a
# thread turn is a conversation, not an impact on the board.
FOLD_KIND = "fold"
FOLDABLE_KINDS = (MAP_MUTATION_KINDS | NOTICE_KINDS) - {FOLD_KIND}

# What an add-node's minted node id looks like. Ids are minted from the
# sequence the entry lands at -- and from its position within a fold -- because
# the fold that materialises the node must arrive at the same id as the receipt
# that echoed it, from the log alone and with no clock or randomness in reach.
MINTED_PREFIX = "n-"


def minted_id(seq: int, index: int | None = None) -> str:
    """The id an add-node at this position mints, deterministic from the log."""
    return f"{MINTED_PREFIX}{seq}" if index is None else f"{MINTED_PREFIX}{seq}-{index}"


# The status lane. A status entry is backend-authored and carries a `phase` and
# a human-readable `detail`; the `composing` phase additionally names the tier
# that is composing, and `error` is the phase a projection, persistence or
# agent-transport failure surfaces as. The kind is deliberately absent from the
# submission registry above: no status entry is ever produced by a model, so a
# client offering one is refused as an unknown kind rather than believed.
STATUS_KIND = "status"
STATUS_PHASE_ACCEPTED = "accepted"
STATUS_PHASE_COMPOSING = "composing"
STATUS_PHASE_ERROR = "error"

# The kinds that constitute a conversational turn: a human answering a decision,
# a human opening a thread, a human speaking in one. Only a turn from the
# `human` actor is owed a reply -- the page also opens agent-authored threads,
# and those are recorded and left alone so the backend never answers itself.
# Answerability is separate from acceptance: every kind here is accepted from
# either actor, and only the human's is answered.
ANSWERABLE_KINDS = frozenset({"answer", "thread-created", "thread-turn"})

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


class Option(Strict):
    id: str
    text: str
    pcr: list[str] | None = Field(default=None, min_length=3, max_length=3)


class Answer(Strict):
    option: str | None = None
    text: str | None = None


class Decision(Strict):
    """The same node shape in the handoff and in both images; the status, answer,
    rationale and lock fields exist only in the images.

    `rationale` is the `why` of the last event that changed this decision's
    status, which is what keeps an invalidation and its justification one item
    rather than two: the block and the reasoning for it reach the page together.
    `locked` is the standing blocking flag of the most recent elicit-alert on
    this decision, and a locked decision is not answerable now.
    """

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
    rationale: str | None = None
    locked: bool = False


class Mandate(Strict):
    """Any answer to this decision opens a side thread, and that thread's
    conclusion is the only way to settle it."""

    thread_id: str = Field(alias="threadId")
    scope: str
    title: str
    notice: str


class Talk(Strict):
    """Seed text the page offers when the human wants the question opened up."""

    why: str
    zoom: str


class HandoffDecision(Strict):
    """A decision node as the handoff states it.

    The same shape as a board node minus the fields the board owns: status,
    answer, rationale and the alert lock exist only in the images, so a handoff
    that carried one would be asserting board state nothing has decided yet.
    """

    id: str = Field(min_length=1)
    short: str
    title: str
    # Present and possibly empty, rather than optional: a leaf decision says so
    # by naming no prereqs, and a handoff that simply left the field out would
    # be indistinguishable from one whose author forgot the dependency.
    prereqs: list[str]
    body: str
    options: list[Option] = Field(min_length=2, max_length=3)
    mandate: Mandate | None = None
    talk: Talk | None = None
    fog_until: str | None = Field(default=None, alias="fogUntil")
    fog_title: str | None = Field(default=None, alias="fogTitle")


class HandoffSession(Strict):
    id: str = Field(min_length=1)
    title: str
    created: str
    author: str


class GrillingBrief(Strict):
    """How hard to push, and when to stop.

    `stop_when` is what keeps a session finite: an agent asked to find weaknesses
    finds them indefinitely, so the termination condition is briefed rather than
    discovered.
    """

    posture: str
    stop_when: str


class Plan(Strict):
    statement: str
    decisions: list[HandoffDecision] = Field(min_length=1)


class Handoff(Strict):
    """The whole of what crosses the gap from the main agent to the backend.

    Read once. After the backend appends `session-start` the file has no further
    authority: editing it mid-session changes nothing, and a backend whose log is
    non-empty never opens it.
    """

    handoff_version: Literal[1]
    session: HandoffSession
    impetus: str
    context: str
    constraints: list[str]
    grilling_brief: GrillingBrief
    plan: Plan


class Applied(Strict):
    """What an accepted write actually landed as. `amendments` is required when
    the backend rewrote the submission, so an agent's next turn never reasons
    from a board it did not author."""

    kind: str
    target: str | None
    as_: Literal["sent", "amended"] = Field(default="sent", alias="as")
    amendments: dict[str, str] | None = None


class FoldOutcome(Strict):
    """One sub-update's own outcome inside an atomic fold.

    It says everything a receipt says except the three fields the gesture holds
    once -- the idempotency key, the epoch and the assigned sequence -- because
    a fold is one event with one key at one position. `vetoed` is the outcome of
    a sub-update that was well-formed and did not apply anyway, because a
    sibling was refused and the gesture is all-or-none; its `detail` names the
    sibling. It carries no `reason`: a veto is not one of the seven, and the
    vocabulary a caller switches on stays closed.
    """

    kind: str
    target: str | None = None
    status: Literal["applied", "rejected", "vetoed"]
    as_: Literal["sent", "amended"] = Field(default="sent", alias="as")
    amendments: dict[str, str] | None = None
    reason: str | None = None
    detail: str | None = None
    node: Decision | None = None


class AcceptedReceipt(Strict):
    """`node` is the add-node echo: the node as the fold will materialise it,
    so the agent can revise other decisions against an id it never chose.
    `updates` is a fold's per-sub-update outcomes, absent on every other kind."""

    status: Literal["accepted"] = "accepted"
    idempotency_key: str
    epoch: str
    seq: int
    applied: Applied
    node: Decision | None = None
    updates: list[FoldOutcome] | None = None


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
    updates: list[FoldOutcome] | None = None


Receipt = Annotated[
    AcceptedReceipt | DuplicateReceipt | RejectedReceipt,
    Field(discriminator="status"),
]


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
    """One notice the human has not yet dealt with. `target` is null for a
    notice anchored to no decision, the way a thread's `decision` is."""

    id: str
    target: str | None = None
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


class TerminalSession(Strict):
    id: str
    title: str
    created: str
    ended: str


class References(Strict):
    """Where the durable record is, relative to the session directory. The
    result is what the main agent receives beside these paths -- never a
    transcript dump, which is why the transcript is referenced and not carried.
    """

    log: str
    image1: str
    image2: str


class CapturedDecision(Strict):
    id: str
    title: str
    answer: str | None
    status: DecisionStatus
    rationale: str


class OpenItem(Strict):
    """One decision unsettled when the session ended, and what stopped it."""

    id: str
    blocker: str


class CapturedThread(Strict):
    id: str
    title: str
    state: ThreadState
    conclusion: str | None


class TerminalResult(Strict):
    """What a captured session leaves behind, written beside the log.

    Everything but `summary` is pure code over the log, which is what lets a
    fresh process pointed at a session directory alone produce the same bytes
    twice. `summary` is the one prose field, and it is a briefing rather than a
    transcript.
    """

    session: TerminalSession
    references: References
    decisions: list[CapturedDecision]
    open_items: list[OpenItem]
    threads: list[CapturedThread]
    summary: str
    stop_reason: str


class DispatchContext(Strict):
    """What one agent dispatch is given, and the shape recorded on disk for it.

    Image 2 is carried as the whole model rather than as anything derived from
    it. There is no elision path and no budget that can create one: a context
    that trimmed settled decisions would lose human decisions silently, and
    nothing downstream could detect the loss.
    """

    agent: str
    channel: str = MAP_CHANNEL
    epoch: str
    seq: int
    image2: Image2


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


class Payload(BaseModel):
    """The base of every per-kind payload shape.

    Extra fields are allowed here and forbidden on the envelope, and the
    asymmetry is deliberate: the envelope is this protocol's own vocabulary,
    while a payload is content two ends may extend ahead of each other.
    """

    model_config = ConfigDict(extra="allow")


class OptionPayload(Payload):
    """An option as an agent offers it. `pcr` is read leniently -- the trio is a
    contract on what renders, not on what may be written."""

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class AddNodePayload(Payload):
    """A question, its options and its prereqs. `target` and `id` are optional
    because the id is the backend's to mint; a supplied one is honoured, so a
    board seeded from a handoff keeps the ids the handoff named.

    Two to three options is the board's rule, not the renderer's: an agent that
    offers one option has made the decision rather than posed it, and a fourth
    is a decision that has not been narrowed.
    """

    title: str = Field(min_length=1)
    options: list[OptionPayload] = Field(min_length=2, max_length=3)
    prereqs: list[str] = Field(default_factory=list)
    target: str | None = Field(default=None, min_length=1)
    id: str | None = Field(default=None, min_length=1)


class TargetedPayload(Payload):
    """Every kind that acts on a decision names it."""

    target: str = Field(min_length=1)


class RevisePayload(TargetedPayload):
    """Supplied fields replace; omitted ones are left alone."""

    options: list[OptionPayload] | None = Field(default=None, min_length=2, max_length=3)


class InvalidatePayload(TargetedPayload):
    """Invalidating a decision is the heaviest thing an agent can do short of
    unsettling one, so the rationale rides in this payload rather than in a note
    on a neighbouring node: the human must not have to read the block and its
    justification as two unrelated items."""

    why: str = Field(min_length=1)


class InformationalPayload(Payload):
    """A notice to the human. `target` is optional: not every informational is
    about a decision."""

    text: str = Field(min_length=1)


class ElicitAlertPayload(TargetedPayload):
    """An alert against one decision. `blocking` is required rather than
    defaulted, because a lock the sender did not ask for and a lock they did are
    the same bytes once a default fills it in."""

    text: str = Field(min_length=1)
    blocking: bool


class FoldPayload(Payload):
    """The gesture's ordered sub-updates, each a kind and that kind's payload."""

    updates: list[dict[str, Any]] = Field(min_length=1)


PAYLOAD_SHAPES: dict[str, type[Payload]] = {
    "add-node": AddNodePayload,
    "revise": RevisePayload,
    "invalidate": InvalidatePayload,
    "informational": InformationalPayload,
    "elicit-alert": ElicitAlertPayload,
    "settle": TargetedPayload,
    "unsettle": TargetedPayload,
    "resolve-stale": TargetedPayload,
    "answer": TargetedPayload,
    FOLD_KIND: FoldPayload,
}


def fault_summary(error: ValidationError, whole: str) -> str:
    """Every fault a validation found, each naming the field it is about.

    The field path is the whole of what makes a refusal actionable: "refused" on
    its own sends the author back to diff their file against a schema, while
    `plan.decisions.2.body: Field required` is a one-line fix. `whole` is what a
    fault against the document itself is called, since such a fault has no path.
    """
    return "; ".join(
        f"{'.'.join(str(part) for part in fault['loc']) or whole}: {fault['msg']}"
        for fault in error.errors()
    )


def payload_problem(kind: str, payload: Mapping[str, Any]) -> str | None:
    """Judge a payload against its kind's shape, returning a message or None.

    A kind with no shape stated here -- an unknown one, or a thread or lifecycle
    kind the closed rejection vocabulary already speaks for -- has no shape to
    fail, and is left to the typed receipt path.
    """
    shape = PAYLOAD_SHAPES.get(kind)
    if shape is None:
        return None
    try:
        shape.model_validate(payload)
    except ValidationError as error:
        return f"{kind!r} payload: {fault_summary(error, 'payload')}"
    if kind != FOLD_KIND:
        return None
    return _fold_payload_problem(payload)


def _fold_payload_problem(payload: Mapping[str, Any]) -> str | None:
    for index, update in enumerate(payload["updates"]):
        kind = update.get("kind")
        if not isinstance(kind, str):
            return f"fold sub-update {index} names no kind"
        problem = payload_problem(kind, update)
        if problem is not None:
            return f"fold sub-update {index}: {problem}"
    return None


def batch_payload_problem(submissions: Sequence[EventSubmission]) -> str | None:
    """The whole batch's first payload fault, judged before anything is appended.

    Refusing here rather than event by event is what keeps the append and the
    receipt honest: a batch half-appended and then refused at the envelope would
    leave entries in the log that no caller ever got a receipt for.
    """
    for index, submission in enumerate(submissions):
        problem = payload_problem(submission.kind, submission.payload)
        if problem is not None:
            return f"event {index}: {problem}"
    return None


def fold_outcomes(submission: EventSubmission, known_nodes: Set[str]) -> list[FoldOutcome]:
    """Judge every sub-update of a fold together, all-or-none.

    The sub-updates are judged in order against a node set that grows as they
    go, so an add-node earlier in the gesture is a node the ones after it may
    name. One refusal vetoes the gesture: the refused sub-update carries its own
    reason and every other carries a veto naming it, so a reader of the receipt
    can tell which sub-update was the problem from the receipt alone.
    """
    nodes = set(known_nodes)
    outcomes: list[FoldOutcome] = []
    for update in submission.payload.get("updates", []):
        kind = str(update.get("kind"))
        target = update.get("target")
        problem = _sub_update_problem(submission, kind, update, nodes)
        if kind == "add-node" and isinstance(target, str):
            nodes.add(target)
        outcomes.append(
            FoldOutcome(
                kind=kind,
                target=target if isinstance(target, str) else None,
                status="rejected" if problem else "applied",
                reason=problem[0] if problem else None,
                detail=problem[1] if problem else None,
            )
        )

    refused = next((index for index, one in enumerate(outcomes) if one.status == "rejected"), None)
    if refused is None:
        return outcomes
    veto = (
        f"the gesture applies whole or not at all; sub-update {refused} "
        f"({outcomes[refused].kind!r}) was refused"
    )
    return [
        one
        if one.status == "rejected"
        else one.model_copy(update={"status": "vetoed", "detail": veto})
        for one in outcomes
    ]


def _sub_update_problem(
    submission: EventSubmission, kind: str, update: Mapping[str, Any], nodes: Set[str]
) -> tuple[str, str] | None:
    """A sub-update is judged exactly as the same update would be on its own,
    once it is established that a fold may carry it at all. A fold does not
    nest, and it carries no thread event: a thread turn is a conversation, not
    an impact on the board."""
    if kind not in FOLDABLE_KINDS:
        return (REASON_UNKNOWN_KIND, f"{kind!r} is not a kind a fold may carry")
    return rejection_reason(
        EventSubmission(
            kind=kind,
            actor=submission.actor,
            channel=submission.channel,
            idempotency_key=submission.idempotency_key,
            payload={key: value for key, value in update.items() if key != "kind"},
        ),
        nodes,
    )


def mint_targets(payload: Mapping[str, Any], kind: str, seq: int) -> dict[str, Any]:
    """A copy of the payload with every add-node's node id materialised.

    Minting at append time rather than at fold time is what makes the id one
    fact instead of two: the receipt echoes what the projector will build,
    because both read the same durable bytes.
    """
    minted = dict(payload)
    if kind == "add-node":
        # An explicit null is a request to mint, same as absence -- setdefault
        # would keep the null and the node would silently never materialise.
        minted["target"] = minted.get("target") or minted.get("id") or minted_id(seq)
    elif kind == FOLD_KIND:
        minted["updates"] = [
            (
                {**update, "target": update.get("target") or update.get("id") or minted_id(seq, i)}
                if update.get("kind") == "add-node"
                else update
            )
            for i, update in enumerate(payload.get("updates", []))
        ]
    return minted


def rejection_reason(submission: EventSubmission, known_nodes: Set[str]) -> tuple[str, str] | None:
    """Judge one submission's content, returning `(reason, detail)` or None.

    The missing-key and epoch-mismatch reasons are decided by the appender,
    which is what holds the key index and the epoch; everything else is a
    property of the submission itself and is decided here.
    """
    if submission.kind not in KNOWN_KINDS:
        return (REASON_UNKNOWN_KIND, f"{submission.kind!r} is not an event kind of this protocol")

    if submission.kind in LIFECYCLE_KINDS:
        return _lifecycle_problem(submission)

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

    if submission.kind == FOLD_KIND:
        # A fold is refused for whatever refused the first of its sub-updates:
        # the gesture is all-or-none, so one refusal is the gesture's refusal,
        # and it is named from the closed vocabulary like any other.
        refused = next(
            (one for one in fold_outcomes(submission, known_nodes) if one.status == "rejected"),
            None,
        )
        return None if refused is None else (str(refused.reason), str(refused.detail))

    target = submission.payload.get("target")
    if isinstance(target, str) and submission.kind != "add-node" and target not in known_nodes:
        return (REASON_UNKNOWN_NODE, f"no decision node {target!r} exists in this session")

    if submission.kind in ANSWER_KINDS or "answer" in submission.payload:
        return _answer_problem(submission.payload.get("answer"))

    return None


def read_turns(payload: Mapping[str, Any], actor: Actor, timestamp: str) -> list[ThreadTurn]:
    """Both shapes a thread event carries its content in, read as one list.

    The page speaks in a `turns[]` array of who/text pairs; a backend-authored
    reply may carry bare text. One reader handles both, and it is this one --
    the accept path judges a thread event by what this returns and the fold
    builds the thread's turn list from it, so an event cannot be accepted for
    saying something and then project as having said nothing.

    `who` falls back to the entry's own actor. The appender judges a thread
    event on whether it says anything, never on who it claims said it, so an
    unknown attribution is already durable by the time the fold sees it, and
    raising over something that already has a receipt would take the session
    down.
    """
    raw = payload.get("turns")
    if isinstance(raw, list):
        return [
            ThreadTurn(
                who=_who(turn.get("who"), actor),
                text=str(turn.get("text", "")),
                timestamp=str(turn.get("timestamp", timestamp)),
            )
            for turn in raw
            if isinstance(turn, Mapping) and turn.get("text")
        ]
    text = payload.get("text")
    if isinstance(text, str) and text:
        return [ThreadTurn(who=actor, text=text, timestamp=timestamp)]
    return []


def _who(raw: object, fallback: Actor) -> Actor:
    return cast("Actor", raw) if isinstance(raw, str) and raw in ACTORS else fallback


def _lifecycle_problem(submission: EventSubmission) -> tuple[str, str] | None:
    """Who may bracket a session.

    Only the human may end one, and nobody but the backend may start one. Both
    refusals are named `unknown event kind` rather than a reason of their own:
    the rejection vocabulary is closed and a caller switches on it, and an
    eighth reason minted for this would break every one of them. The wording is
    exact anyway -- a lifecycle kind is not part of the vocabulary the refused
    sender has.
    """
    if submission.kind == SESSION_END_KIND and submission.actor == "human":
        return None
    rule = (
        "ending a grilling is a human gesture; an agent that judges `stop_when` "
        "satisfied says so to the human and does not end the session itself"
        if submission.kind == SESSION_END_KIND
        else "the backend appends it once, when it reads the handoff"
    )
    return (
        REASON_UNKNOWN_KIND,
        f"{submission.kind!r} is not a kind {submission.actor!r} may send: {rule}",
    )


def _thread_turn_problem(submission: EventSubmission) -> tuple[str, str] | None:
    """A thread event says something or it says nothing, judged by the same
    reader that will project it."""
    if read_turns(submission.payload, submission.actor, ""):
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
