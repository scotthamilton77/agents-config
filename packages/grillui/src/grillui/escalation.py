"""Whether a turn should be handed up a tier, decided from the transcript.

A fast model asked to judge whether a question exceeds its own ability judges
generously and answers anyway -- including on a question the human has just
finished saying they cannot resolve. So the recommendation is never the model's
opinion of itself. It is a condition evaluated here, in code, against what was
actually said and what the board actually looks like, and it is the sole basis
of the metadata a fast reply carries.

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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from grillui.schemas import (
    MAP_CHANNEL,
    STATUS_KIND,
    STATUS_PHASE_TRANSFERRED,
    THREAD_KINDS,
    TRANSFER_FLAG,
    TRANSFER_SOURCE_POLICY,
    read_turns,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from grillui.schemas import Image2, LogEntry

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
    a heavy turn is owed the reason, and a number would not be one.
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
    would spend the human's subscription without being asked. A status entry is
    backend-authored by construction, since the kind is outside the submission
    registry and no client can offer one.

    Scanning backwards is what makes both directions work with no state kept: a
    human's return to the fast tier wins over an earlier policy transfer, and a
    later met condition escalates the channel again.
    """
    for entry in reversed(entries):
        if entry.channel != channel:
            continue
        if entry.actor == "human" and TRANSFER_FLAG in entry.payload:
            return entry
        if entry.kind == STATUS_KIND and entry.payload.get("phase") == STATUS_PHASE_TRANSFERRED:
            return entry
    return None


def in_expert_mode(entries: Sequence[LogEntry], channel: str) -> bool:
    """Whether this one channel is on the heavy tier.

    Per channel, and read from the log rather than held in memory: escalating
    one thread says nothing about any other, and a successor process must find
    the map still in expert mode if that is where it was left.

    The mode is the last gesture on that channel and stands until the opposite
    one is made -- a channel that fell back to the fast tier because the human
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
