"""The two tiers: what each is told, which model it is, and what a turn is given.

**Configuration owns the model ids.** Neither id is written into a driver: the
fast tier is a non-Claude model reached over OpenRouter and the heavy tier is a
Claude model driven as CLI turns, and which model each is comes from
configuration so the choice can be re-made on cost-per-useful-turn without a
code change.

**The prompts are the tiers' whole standing brief.** Both carry the same three
rules -- never assert what the context does not support, keep it short, and say
your piece in one turn and stop -- and the fast tier additionally carries the
facilitation mandate: answer from the context you were given, and stop short of
deciding. Whether a turn should have gone up a tier is not the model's own
judgment to make and is not asked of it here; that is evaluated against the
transcript in code.

**A turn is given the briefing, the board and the channel's conversation.** The
briefing is read out of the session's own opening log entry rather than the
handoff file, which loses its authority the moment that entry lands -- and the
termination condition it carries is what keeps a grilling finite, so it travels
with every turn. The board crosses as the recorded dispatch bytes, verbatim, so
what the model was given and what the audit record shows are the same bytes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from grillui.escalation import turns_of
from grillui.schemas import SESSION_START_KIND

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from grillui.schemas import LogEntry

FAST_TIER = "fast"
HEAVY_TIER = "heavy"

# The defaults: a non-Claude fast tier reached over OpenRouter, a Claude heavy
# tier driven through its own CLI. The heavy figure that makes a resumed chain
# worth holding open is a floor for a heavier default, not a ceiling -- which is
# the reason both ids are configuration rather than constants a session is stuck
# with.
DEFAULT_FAST_MODEL = "google/gemini-3.5-flash-lite"
DEFAULT_HEAVY_MODEL = "claude-sonnet-5"

FAST_MODEL_ENV = "GRILLUI_FAST_MODEL"
HEAVY_MODEL_ENV = "GRILLUI_HEAVY_MODEL"
API_KEY_ENV = "OPENROUTER_API_KEY"

DEFAULT_API_BASE = "https://openrouter.ai/api/v1"
CLAUDE_CLI = "claude"


@dataclass(frozen=True)
class TierConfig:
    """Which model each tier is.

    Frozen because a turn must not be able to change the tier it is being
    attributed to halfway through: the id in the log is the id the request was
    made with.
    """

    fast_model: str = DEFAULT_FAST_MODEL
    heavy_model: str = DEFAULT_HEAVY_MODEL

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> TierConfig:
        """Configuration as the environment states it, defaulted field by field.

        Taken as a mapping rather than read from the process directly, so what a
        session is configured with is something a caller can state.
        """
        source = os.environ if environ is None else environ
        return cls(
            fast_model=source.get(FAST_MODEL_ENV) or DEFAULT_FAST_MODEL,
            heavy_model=source.get(HEAVY_MODEL_ENV) or DEFAULT_HEAVY_MODEL,
        )

    def model_for(self, tier: str) -> str:
        return self.fast_model if tier == FAST_TIER else self.heavy_model


NO_MANUFACTURE_RULE = (
    "Never assert anything the context you were given does not support. If a fact you "
    "would need is not in it, say what you lack instead of supplying it. An invented "
    "detail is worse than an admitted gap, because the human cannot tell it apart from "
    "one they told you."
)

CONCISION_RULE = (
    "At most three sentences, unless the human explicitly asks for detail. Say the one "
    "thing that moves the decision; leave out the preamble, the recap and the summary "
    "of what you are about to say."
)

ONE_TURN_RULE = (
    "This is one turn. Answer, then stop -- you are invoked again when there is "
    "something new to answer. Do not wait for anything, do not ask to be called back, "
    "and do not check for updates: nothing arrives while you are speaking."
)

FACILITATION_MANDATE = (
    "You facilitate the discussion. Answer from the context you were given, quickly, and "
    "keep the human moving. The moment a question crosses into reasoning, decisioning or "
    "implied design, stop short of deciding it: say what the question turns on and leave "
    "the decision with the human. Asking one sharpening question back is the ordinary "
    "move."
)

GRILL_MASTER_MANDATE = (
    "You are the grill-master. You interrogate the plan decision by decision until every "
    "decision is either settled or parked with a named blocker, and you are the only "
    "agent that authors changes to the map. Push on the axis the posture names. When you "
    "judge the stop condition met, say so to the human -- ending the grilling is theirs "
    "to do, not yours."
)

FAST_SYSTEM_PROMPT = "\n\n".join(
    [FACILITATION_MANDATE, NO_MANUFACTURE_RULE, CONCISION_RULE, ONE_TURN_RULE]
)

HEAVY_SYSTEM_PROMPT = "\n\n".join(
    [GRILL_MASTER_MANDATE, NO_MANUFACTURE_RULE, CONCISION_RULE, ONE_TURN_RULE]
)

SYSTEM_PROMPTS: dict[str, str] = {
    FAST_TIER: FAST_SYSTEM_PROMPT,
    HEAVY_TIER: HEAVY_SYSTEM_PROMPT,
}

NO_BRIEFING = "No briefing was recorded for this session."


def briefing(entries: Sequence[LogEntry]) -> str:
    """The session's opening briefing, as the log holds it.

    The handoff file is not consulted: it loses its authority the moment the
    opening entry lands, so a process that never saw the file and one that read
    it brief their agents identically. The termination condition is the field
    that must not go missing -- an agent asked to find weaknesses finds them
    indefinitely, and this is the only thing that tells it when to stop.
    """
    opening = next((entry for entry in entries if entry.kind == SESSION_START_KIND), None)
    if opening is None:
        return NO_BRIEFING
    payload = opening.payload
    brief = payload.get("grilling_brief")
    brief = brief if isinstance(brief, dict) else {}
    plan = payload.get("plan")
    plan = plan if isinstance(plan, dict) else {}
    raw = payload.get("constraints")
    constraints = "; ".join(str(one) for one in raw) if isinstance(raw, list) else ""
    return "\n".join(
        [
            f"What is being designed: {plan.get('statement', '')}",
            f"Why it is being grilled now: {payload.get('impetus', '')}",
            f"What you cannot infer: {payload.get('context', '')}",
            f"Do not propose against: {constraints or 'nothing stated'}",
            f"Posture: {brief.get('posture', '')}",
            f"Stop when: {brief.get('stop_when', '')}",
        ]
    )


def compose(recorded: str, channel: str, entries: Sequence[LogEntry]) -> str:
    """One turn's prompt: the briefing, the board, and this channel's turns.

    The board crosses as the recorded dispatch bytes rather than as anything
    rebuilt from them. There is no elision path: a prompt that trimmed settled
    decisions would lose decisions the human made minutes ago, and neither the
    human nor the audit record would show which ones went missing.
    """
    conversation = "\n".join(f"{turn.who}: {turn.text}" for turn in turns_of(entries, channel))
    return "\n\n".join(
        [
            "## Briefing",
            briefing(entries),
            "## The board, whole",
            recorded,
            f"## This channel ({channel}), in order",
            conversation or "Nothing has been said on this channel yet.",
            "## Your turn",
            "Answer the last thing the human said, under the rules you were given.",
        ]
    )
