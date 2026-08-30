"""Whether a turn should be handed up a tier, decided from the transcript and,
where a gesture leaves no transcript to read, from the board.

A model asked to judge whether a question exceeds its own ability judges
generously and answers anyway -- including on a question the human has just
finished saying they cannot resolve. So the recommendation is never the model's
opinion of itself. It is a condition evaluated here, in code, against what was
actually said and what the board actually looks like, and it is the sole basis
of the metadata a first-rung reply carries.

Three conditions, all decidable from the transcript and the board:

- the human asked for a commitment rather than another question, on a decision
  two or more other decisions depend on;
- the human rejected a reframing of the question, or said the trade-off itself
  is the thing they cannot resolve;
- three or more decisions have to be weighed at once.

Asking a sharpening question back is the ordinary move and is not one of them, so
a transcript satisfying none of the three yields no recommendation at all.

Recommending is the whole of what happens here. Who acts on it is the session's
escalation policy, and nothing in this module moves a turn to another tier
either way. Which tier a channel is on afterwards is the other question this
module answers, and it is read back off the log one channel at a time: the
human's own turn carrying the transfer key, or the backend's `transferred`
status entry where the policy moved the channel itself. An agent asserting a
transfer in its own reply is neither, and moves nothing.

Three of the map channel's escalations are not conditions on a transcript at
all, because the gestures they fire on carry no text for a condition to read.
Two of them are read here, off the board and before any model is called:

- **which seat a gesture is composed on.** The judgment classes are closed --
  a gesture that leaves the board decisions it is still offering, a thread's
  conclusion being folded in, a withdrawal the human got in front of, and the
  doctor -- and everything else is clerical and stays on the first rung. The
  class is a reading of the board and never a model's opinion of its own reach,
  for the reason the conditions above exist: a model asked whether a question
  exceeds it judges generously and answers anyway. Classing writes nothing, so
  the next clerical gesture is first-rung again with no entry to undo.
- **whether the human has said twice that the first rung was not enough.** A
  dismissal of a first-rung seat's proposal is the one wordless way they say a
  turn was wrong; the counter it feeds is the lane's, and what is read here is
  which dismissals are that gesture and whether the policy has already moved
  this channel. That second reading is what makes the move once-per-session:
  the entry is sticky by GUI-D35's own rule, so a channel the human took back
  down stays down rather than being bought again by the next signal.

One hand-up is not a recommendation at all. Where the human's gesture leaves
decisions the board should stop offering, what the next turn owes is a ruling
per decision, and a ruling can be checked after the fact. Two gestures leave one:
an answer taking an option that named the decisions it puts in question, and an
invalidate the human applied, which leaves whatever was resting on it standing on
nothing. So the obligation is stated here, and the reply is measured against it
here -- off the turn's own `rulings`, where a ruling of `stands` counts on its
`why` and a ruling of `invalidate` or `revise` counts only where the same turn
carried that update. What is left unruled is what the lane insists on. The
condition markers above are read lexically and may miss; this one cannot, because
nothing about it is read out of prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from grillui.schemas import (
    AGENT_ACTORS,
    DISCHARGING_KINDS,
    MAP_CHANNEL,
    PROPOSABLE_KINDS,
    RULING_STANDS,
    RULINGS_KEY,
    STATUS_KIND,
    STATUS_PHASE_TRANSFERRED,
    THREAD_KINDS,
    TIER_KEY,
    TRANSFER_FLAG,
    TRANSFER_SOURCE_POLICY,
    MootnessObligation,
    read_turns,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from grillui.schemas import Image2, LogEntry

# Whose turn carries a ruling. The map's author is the only agent that makes
# one, so a reader looking for the last ruling looks for its entry and no other.
GRILL_MASTER_ACTOR = "grill-master"

CONDITION_COMMITMENT = "commitment asked on a decision two or more decisions depend on"
CONDITION_IRREDUCIBLE = "reframing rejected, or the trade-off named as what cannot be resolved"
CONDITION_MULTIPLE = "three or more decisions weighed at once"

DEPENDENTS_THRESHOLD = 2
DECISIONS_THRESHOLD = 3

# ponytail: the conditions are read lexically off the turn text. The ceiling is
# phrasing outside these markers, which reads as "no recommendation" -- the safe
# direction, since the human still has the control. Upgrade path if real
# sessions show misses: a structured field the page sets when the human presses
# the commitment affordance, evaluated here beside the text.
COMMITMENT_MARKERS = (
    "just decide",
    "just pick",
    "pick one",
    "make the call",
    "make a call",
    "your call",
    "what should i do",
    "tell me which",
    "commit to one",
    "give me an answer",
    "stop asking and",
)

IRREDUCIBLE_MARKERS = (
    "not the question",
    "not what i asked",
    "you already asked",
    "you asked that already",
    "stop reframing",
    "i cannot resolve",
    "i can't resolve",
    "cannot decide between",
    "can't decide between",
    "the trade-off is what i",
    "the tradeoff is what i",
    "the part i cannot",
    "the part i can't",
)


@dataclass(frozen=True)
class Turn:
    """One conversational turn as this module reads it.

    `target` is the decision the turn is about, which is what the dependent
    count is measured from; a turn spoken in a thread names none, and the
    thread's anchor decision stands in for it.
    """

    who: str
    text: str
    target: str | None = None


@dataclass(frozen=True)
class Recommendation:
    """A named condition and the evidence for it.

    The condition is named rather than scored: a human deciding whether to spend
    an expert turn is owed the reason, and a number would not be one.
    """

    condition: str
    evidence: str

    def as_payload(self) -> dict[str, str]:
        return {"condition": self.condition, "evidence": self.evidence}


def turns_of(entries: Sequence[LogEntry], channel: str = MAP_CHANNEL) -> list[Turn]:
    """One channel's conversation, in log order.

    Read from the log rather than from the images, because a turn's target is
    what the dependent count needs and the images keep answers on the decision
    rather than on the turn that gave them.
    """
    turns: list[Turn] = []
    for entry in entries:
        if entry.channel != channel:
            continue
        if entry.kind in THREAD_KINDS:
            turns.extend(
                Turn(who=turn.who, text=turn.text)
                for turn in read_turns(entry.payload, entry.actor, entry.timestamp)
            )
        elif entry.kind == "answer":
            turns.append(_answer_turn(entry))
        elif entry.kind == "informational":
            text = entry.payload.get("text")
            if isinstance(text, str) and text:
                turns.append(Turn(who=entry.actor, text=text))
    return turns


def _moved_by(entries: Sequence[LogEntry], channel: str) -> LogEntry | None:
    """The entry that last said which tier this one channel is on.

    Two things may say it, and the later one wins. The human's own turn carrying
    the transfer key is one; the backend's `transferred` status entry -- the
    escalation policy moving the channel itself -- is the other. Nothing else
    counts: an agent's reply carrying the same key is a model claiming a
    transfer, and a payload key is open surface, so one that could set this
    would spend the human's subscription without being asked.

    Both branches name their author. The appender already refuses a client that
    offers a `status` kind -- it is outside the submission registry, so the
    rejection is `unknown event kind` -- which makes the actor test on the
    status branch unreachable through the wire today. It is written anyway, so
    that what this reader accepts and what the writer can produce are the same
    statement rather than two that happen to agree: a reader whose gate is the
    kind alone starts trusting agent-authored entries the moment the registry
    changes, and it does so silently.

    Scanning backwards is what makes both directions work with no state kept: a
    human's return to the first rung wins over an earlier policy transfer, and a
    later met condition escalates the channel again.
    """
    for entry in reversed(entries):
        if entry.channel != channel:
            continue
        if entry.actor == "human" and TRANSFER_FLAG in entry.payload:
            return entry
        if _policy_transfer(entry, channel):
            return entry
    return None


def _policy_transfer(entry: LogEntry, channel: str) -> bool:
    """Whether this entry is the policy's own move of this channel."""
    return (
        entry.channel == channel
        and entry.actor == "backend"
        and entry.kind == STATUS_KIND
        and entry.payload.get("phase") == STATUS_PHASE_TRANSFERRED
    )


def policy_transferred(entries: Sequence[LogEntry], channel: str) -> bool:
    """Whether the policy has ever moved this channel up.

    Asked before writing another such entry, and answered over the whole log
    rather than from the mode the channel is in now. The two are different
    questions the moment the human uses the transfer control: the way back down
    is theirs, and a second entry written on the next signal would buy the
    channel again on a decision they have already reversed. Log-derived, so a
    successor process asks it of the same record and reaches the same answer --
    the counter feeding it is one tenure's, and this is what keeps a restart
    from spending the transfer twice.
    """
    return any(_policy_transfer(entry, channel) for entry in entries)


def dismisses_first_rung(
    image: Image2, entries: Sequence[LogEntry], pending: Sequence[str], expert_tier: str
) -> bool:
    """Whether this dismissal is the human saying a first-rung turn was wrong.

    Read off the queue as it stands with the item still in it, so the caller
    asks before the gesture lands rather than after the fold has removed what
    the question is about.

    Two things in that queue are not this gesture. The queue holds notices as
    well as proposals -- the backend's own word that a turn left decisions
    unruled among them -- and a notice is something the human was told rather
    than something a seat offered them, so the kind is checked here and not left
    to the appender's separate refusal of a notice as a thing to dismiss. And a
    proposal the expert authored says nothing about the rung below it: an
    unattributed one is not the expert's and counts, since every seat that takes
    a turn names itself and an entry that named none was authored by no seat at
    all.
    """
    named = set(pending)
    seats = {entry.seq: entry.payload.get(TIER_KEY) for entry in entries}
    return any(
        item.id in named
        and item.kind in PROPOSABLE_KINDS
        and seats.get(item.authored_at) != expert_tier
        for item in image.pending
    )


# What each closed judgment class is called on the lane. Named rather than
# counted: the class is the reason a gesture skipped the first rung, and a human
# reading why their first-rung seat was passed over is owed the reason.
JUDGMENT_UNRULED = "the gesture leaves decisions the board is still offering"
JUDGMENT_FOLD = "a thread's conclusion is being folded into the board"
JUDGMENT_CONFLICT = "a withdrawal the human got in front of"
JUDGMENT_DOCTOR = "the board is being reassessed whole"


def judgment_class(
    image: Image2,
    entries: Sequence[LogEntry],
    channel: str,
    *,
    concluding: bool = False,
    conflict: bool = False,
    reassess: bool = False,
) -> str | None:
    """Which judgment class this turn is, or nothing where it is clerical.

    The set is closed and every member is readable off the board before a model
    is called, which is the whole of why the classing may decide a seat: there
    is no transcript at this point to read, and a class inferred from the
    human's prose would be the self-assessment the conditions above replace.

    The three flags are the turns nobody spoke a channel gesture to start, or
    spoke on another channel: a fold is answered on the map because only the
    grill-master authors map mutations, a conflict is handed back to the author
    that raised it, and the doctor is the whole board reassessed at once. Each
    is a judgment the first rung has no standing to make.

    The fourth class is the gesture that leaves the board offering decisions its
    own answer moved -- an option whose mark resolves to one still live, or an
    applied invalidate that stranded a dependent. It is the obligation the next
    turn owes, asked for here rather than restated: a class drawn wider than the
    obligation would send the expert a turn with nothing to rule on, and one
    drawn narrower would leave the first rung a ruling it was passed over for.

    Only the map's, because the map is the only channel these gestures reach:
    a thread agent authors no map mutation and is owed no ruling.
    """
    if channel != MAP_CHANNEL:
        return None
    if concluding:
        return JUDGMENT_FOLD
    if conflict:
        return JUDGMENT_CONFLICT
    if reassess:
        return JUDGMENT_DOCTOR
    if mootness_obligation(image, entries, channel) is not None:
        return JUDGMENT_UNRULED
    return None


def in_expert_mode(entries: Sequence[LogEntry], channel: str) -> bool:
    """Whether this one channel is on the heavy tier.

    Per channel, and read from the log rather than held in memory: transferring
    one thread says nothing about any other, and a successor process must find
    the map still in expert mode if that is where it was left.

    The mode is the last gesture on that channel and stands until the opposite
    one is made -- a channel that fell back to the first rung because the human
    said nothing this turn would quietly undo the transfer they paid for.
    """
    moved = _moved_by(entries, channel)
    if moved is None:
        return False
    # A `transferred` entry only ever moves a channel up; the way back down is
    # the human's, and it is their own turn that carries it.
    return moved.kind == STATUS_KIND or moved.payload[TRANSFER_FLAG] is True


def transfer_source(entries: Sequence[LogEntry], channel: str) -> str | None:
    """What moved this channel to the heavy tier, when it was not the human.

    `"policy"` where the escalation policy moved it, and nothing at all where
    the human's gesture did: the transfer flag on their own turn already names
    them, so a session that never escalates by itself writes the log it always
    wrote, byte for byte.
    """
    moved = _moved_by(entries, channel)
    return TRANSFER_SOURCE_POLICY if moved is not None and moved.kind == STATUS_KIND else None


def recommend(
    image: Image2, turns: Sequence[Turn], channel: str = MAP_CHANNEL
) -> Recommendation | None:
    """The condition this turn meets, or None when it meets none.

    Only the human's own last turn is judged. What the agent said back is not
    evidence about the question's weight -- it is the thing that would turn this
    into the self-assessment the conditions exist to replace.
    """
    latest = next((turn for turn in reversed(turns) if turn.who == "human"), None)
    if latest is None:
        return None
    # The typed apostrophe and the curly one a page produces are the same word.
    text = latest.text.lower().replace("\u2019", "'")
    target = latest.target or _anchor(image, channel)

    dependents = _dependents(image, target)
    if len(dependents) >= DEPENDENTS_THRESHOLD and _matched(text, COMMITMENT_MARKERS):
        return Recommendation(
            condition=CONDITION_COMMITMENT,
            evidence=(
                f"the human asked for a commitment on {target!r}, which "
                f"{', '.join(dependents)} depend on"
            ),
        )

    matched = _matched(text, IRREDUCIBLE_MARKERS)
    if matched is not None:
        return Recommendation(
            condition=CONDITION_IRREDUCIBLE,
            evidence=f"the human said {matched!r}, which is not a question the next one sharpens",
        )

    weighed = _referenced(image, text, target)
    if len(weighed) >= DECISIONS_THRESHOLD:
        return Recommendation(
            condition=CONDITION_MULTIPLE,
            evidence=f"the turn puts {', '.join(weighed)} in play at once",
        )
    return None


ANSWER_KIND = "answer"
INVALIDATE_KIND: Final = "invalidate"
REVISE_KIND = "revise"

# A decision the board has stopped offering. Everything else -- open, locked,
# stale, fogged -- is still a question the human can be asked, which is what
# makes an unproposed invalidate on it a decision they are left answering after
# their own answer killed it.
DEAD_STATUSES = frozenset({"settled", "invalidated"})

# A change already waiting in the queue is a decision the turn has nothing left
# to be asked about, so it never enters the obligation in the first place. Both
# lists take the same two kinds: a decision may die with the gesture, or change
# under it, and re-asking for either would put the same withdrawal in front of
# the human twice.
DISCHARGING = DISCHARGING_KINDS


def mootness_obligation(
    image: Image2, entries: Sequence[LogEntry], channel: str = MAP_CHANNEL
) -> MootnessObligation | None:
    """What the gesture this turn is being taken on owes the rest of the board.

    Two gestures owe one. An answer taking an option that names what it puts in
    question owes an `invalidate` for each of those still being offered. An
    invalidate the human applied owes the decisions that were resting on it: the
    board no longer holds them -- a prereq that has left the flow gates nothing,
    or they would wait for the rest of the session -- so each is either dead with
    it or standing without it, and saying which is a map turn's job.

    Both are read off structure the board already carries rather than out of
    anything an agent said. The answer's list is the option's own pre-marks; the
    invalidate's is the `prereqs` edges pointing at a decision that has gone.

    Only the grill-master's channel has one, because it is the only agent that
    may author a map mutation, and only while the gesture is still unanswered
    there: an obligation that outlived its own turn would re-open on every later
    turn and spend an expert turn per gesture for the rest of the session. Where
    both are outstanding the answer wins -- it is the turn the human is waiting
    on a reply to, and the invalidate's dependents are already unblocked.
    """
    if channel != MAP_CHANNEL:
        return None
    window = _unreplied(entries)
    answered = next((one for one in window if one.kind == ANSWER_KIND), None)
    obliged = None if answered is None else _answer_obligation(image, answered)
    if obliged is not None:
        return obliged
    killed = next((one for one in window if _invalidations(one)), None)
    return None if killed is None else _resting_obligation(image, killed)


def _answer_obligation(image: Image2, answered: LogEntry) -> MootnessObligation | None:
    """The decisions the option the human took named, still standing.

    The same fact the page pre-marked on hover, which is why nothing here is
    inferred from prose and nothing is a model's reading of a rule.
    """
    target = answered.payload.get("target")
    answer = answered.payload.get(ANSWER_KIND)
    if not isinstance(target, str) or not isinstance(answer, dict):
        return None
    decision = next((one for one in image.decisions if one.id == target), None)
    taken = None if decision is None else answer.get("option")
    option = next((one for one in (decision.options if decision else []) if one.id == taken), None)
    if option is None or not option.puts_in_question:
        return None
    standing = _still_standing(image, option.puts_in_question)
    if not standing:
        return None
    note = answer.get("text")
    return MootnessObligation(
        target=target,
        answer=note if isinstance(note, str) and note else option.text,
        ids=standing,
    )


def _resting_obligation(image: Image2, gesture: LogEntry) -> MootnessObligation | None:
    """What an applied invalidate owes the decisions that were resting on it.

    The list is read off the board after the gesture landed, scoped to what the
    gesture itself killed: one apply may carry several invalidates, so what the
    turn owes is a proposal per decision left standing on one of them. Decisions
    resting on an older invalidation were obliged when that one landed, and are
    not pressed again on every later one. A gesture that stranded nobody owes
    nothing, which is the ordinary case and costs no turn.
    """
    dead = _invalidations(gesture)
    gone = {one.get("target") for one in dead}
    standing = _still_standing(
        image, [one.id for one in image.decisions if gone.intersection(one.prereqs)]
    )
    if not standing:
        return None
    # Which of the gesture's invalidates to quote as the rationale: one that a
    # decision still standing was actually resting on, rather than whichever of
    # them the apply happened to carry first.
    held = {p for one in image.decisions if one.id in standing for p in one.prereqs}
    blamed = next((one for one in dead if one.get("target") in held), dead[0])
    return MootnessObligation(
        target=str(blamed.get("target")),
        answer=str(blamed.get("why")),
        ids=standing,
        cause=INVALIDATE_KIND,
    )


def rulings_of(entries: Sequence[LogEntry], channel: str = MAP_CHANNEL) -> tuple[list[Any], ...]:
    """The rulings the last grill-master turn on this channel made, and the
    updates it carried.

    Read off the turn's own log entry, which is where a ruling lives: the check
    is on what the document said, not on what the board happens to look like
    afterwards. A turn that ruled and a turn whose proposal the human applied in
    between are different facts, and only the first is coverage.
    """
    for entry in reversed(entries):
        if entry.channel != channel or entry.actor != GRILL_MASTER_ACTOR:
            continue
        return _dicts(entry.payload.get(RULINGS_KEY)), _dicts(entry.payload.get("updates"))
    return [], []


def unruled(
    ids: Sequence[str],
    rulings: Sequence[Mapping[str, Any]],
    updates: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Which of these decisions the turn did not rule on.

    Ids rather than the obligation, because the list shrinks as the ladder is
    walked: a turn handed up carries what the rung below left unruled, and
    measuring the second reply against the original list would report a decision
    the first rung ruled on as one nobody did.

    The whole of the check on a reply, and the reason it needs no prose parsing.
    A `stands` ruling is credited by its `why`, which the shape already requires
    to be there; an `invalidate` or a `revise` is credited only where the same
    document carries that update against that decision, because a verdict that
    says a decision is dead and queues nothing has changed nothing -- and
    crediting the word alone is exactly the failure the ruling exists to catch.

    Coverage and never correctness: a ruling the backend would disagree with is
    not a ruling missing, and no code here reads what a `why` means.
    """
    queued = {
        (one.get("kind"), one.get("target")) for one in updates if one.get("kind") in DISCHARGING
    }
    credited = {
        one.get("decision")
        for one in rulings
        if one.get("ruling") == RULING_STANDS or (one.get("ruling"), one.get("decision")) in queued
    }
    return [one for one in ids if one not in credited]


def _dicts(raw: object) -> list[Any]:
    return [one for one in raw if isinstance(one, dict)] if isinstance(raw, list) else []


def _still_standing(
    image: Image2, ids: Sequence[str], kinds: frozenset[str] = DISCHARGING
) -> list[str]:
    proposed = {item.target for item in image.pending if item.kind in kinds and not item.superseded}
    # An id resolving to no node is dropped rather than carried: a pre-mark may
    # name a decision nobody wrote, and an invalidate on one would be an update
    # with no target.
    live = {one.id for one in image.decisions if one.status not in DEAD_STATUSES}
    return [one for one in dict.fromkeys(ids) if one in live and one not in proposed]


def _invalidations(entry: LogEntry) -> list[dict[str, object]]:
    """The invalidates this entry put on the board, and nothing for any other.

    An invalidate the human applied arrives as a sub-update of their `apply`,
    which is how every one of them arrives: the proposal is the agent's and the
    gesture is theirs. One they authored themselves would arrive as the entry,
    and is read the same way rather than being a second shape to miss.
    """
    if entry.actor != "human":
        return []
    updates = entry.payload.get("updates")
    carried = updates if isinstance(updates, list) else [{**entry.payload, "kind": entry.kind}]
    return [
        one
        for one in carried
        if isinstance(one, dict) and one.get("kind") == INVALIDATE_KIND and one.get("target")
    ]


def _unreplied(entries: Sequence[LogEntry]) -> list[LogEntry]:
    """The human's map gestures since the last thing an agent said there, latest
    first.

    Scanning backwards and stopping at the first agent turn is what bounds an
    obligation to the turn it was made on. The backend's own lane entries are
    passed over: they say a turn was announced, not that one was taken.
    """
    window = []
    for entry in reversed(entries):
        if entry.channel != MAP_CHANNEL:
            continue
        if entry.actor in AGENT_ACTORS:
            break
        if entry.actor == "human":
            window.append(entry)
    return window


def _answer_turn(entry: LogEntry) -> Turn:
    """A human's answer as a turn: the note they wrote, or the option they took.

    An option with no note still says something -- it is the commitment itself --
    so it becomes the turn's text rather than an empty one.
    """
    answer = entry.payload.get("answer")
    text = ""
    if isinstance(answer, dict):
        text = str(answer.get("text") or "") or f"option {answer.get('option')}"
    target = entry.payload.get("target")
    return Turn(who=entry.actor, text=text, target=target if isinstance(target, str) else None)


def _anchor(image: Image2, channel: str) -> str | None:
    """The decision a thread channel hangs off, and nothing for the map."""
    if channel == MAP_CHANNEL:
        return None
    return next((thread.decision for thread in image.threads if thread.id == channel), None)


def _dependents(image: Image2, target: str | None) -> list[str]:
    if target is None:
        return []
    return [decision.id for decision in image.decisions if target in decision.prereqs]


def _matched(text: str, markers: Sequence[str]) -> str | None:
    return next((marker for marker in markers if marker in text), None)


def _referenced(image: Image2, text: str, target: str | None) -> list[str]:
    """Which board decisions this turn puts in play.

    A decision counts as referenced when the turn names its id or its label. The
    decision under discussion counts too: weighing three against the one being
    answered is the same load as naming all four.
    """
    named = [
        decision.id
        for decision in image.decisions
        if decision.id.lower() in text
        or (decision.short and decision.short.lower() in text)
        or (decision.title and decision.title.lower() in text)
    ]
    if target is not None and target not in named:
        named.append(target)
    return named
