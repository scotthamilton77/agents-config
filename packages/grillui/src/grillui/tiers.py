"""The two tiers: what each is told, which model it is, and what a turn is given.

**Configuration owns the model ids, and the efforts with them.** Nothing here
is written into a driver: what occupies each rung comes from configuration so
the choice can be re-made on cost-per-useful-turn without a code change. The
escalation policy sits beside them: whether a met condition needs the human's
gesture is a property of the session, not of the code, and it defaults to
needing it.

**A tier is a rung and a seat is who sits on it.** There are two rungs and only
two -- `fast` first, `heavy` as the expert -- and what varies per channel is the
seat on the first rung: a transport, a model, and an effort where the transport
takes one. A channel whose first rung was already the expert would have nowhere
to hand a turn up to, so the number of rungs is not configuration and the seat
is. The threads' first-rung seat is a hosted model over OpenRouter; the map's is
a mid-weight reasoning model on the Codex transport, because the map's turn is a
ruling rather than a facilitation; and the expert seat is one shared
configuration for every channel.

**A standing brief has two parts, and they vary independently.** The role's
part says what the turn is for and opens the brief; the tier's part says how the
turn is taken -- never assert what the context does not support, keep it short,
reply to what the human said rather than fishing for what they say next, and say
your piece in one turn and stop -- with the fast tier adding that it answers
fast. Nothing about what a turn is for rides on the tier: either tier may drive
the map or a thread, and a mandate hanging on the tier is inherited by whichever
role runs there -- which is how the map's author comes to be told to stop short
of deciding on the one turn whose whole work is a ruling. Every turn, whichever
tier and whichever role, closes on the register rule: plain sentences, the
answer first, no term the decision does not need. Whether a turn should have
gone up a tier is not the model's own judgment to make and is not asked of it
here; that is evaluated against the transcript in code.

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

from grillui.dispatch import GRILL_MASTER, THREAD_AGENT
from grillui.escalation import INVALIDATE_KIND, turns_of
from grillui.schemas import (
    FAST_TIER,
    FOLDABLE_KINDS,
    HEAVY_TIER,
    MAP_CHANNEL,
    MAP_THREAD_KIND,
    SESSION_START_KIND,
    Thread,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from grillui.schemas import DispatchContext, LogEntry, MootnessObligation


# The defaults: a non-Claude fast tier reached over OpenRouter, a Claude heavy
# tier driven through its own CLI at its deepest routine effort. The heavy tier
# is where the human sends a question the fast tier could not carry, so it is
# configured to think rather than to be quick -- an expert that answers as
# fast and as cheaply as the fast tier reads as a transfer that never happened.
# All three remain configuration rather than constants a session is stuck with,
# so the choice can be re-made on cost-per-useful-turn.
DEFAULT_FAST_MODEL = "google/gemini-3.5-flash-lite"
DEFAULT_HEAVY_MODEL = "claude-opus-5"
DEFAULT_HEAVY_EFFORT = "xhigh"

# The three transports a seat may sit on, and the whole of the set. A transport
# outside it is refused at launch rather than resolved to whichever driver the
# wiring happens to fall through to: a misspelled transport that quietly seated
# the map on the threads' model would be a session running a configuration
# nobody chose, attributed to one they did.
OPENROUTER_TRANSPORT = "openrouter"
CODEX_TRANSPORT = "codex"
CLAUDE_TRANSPORT = "claude"
TRANSPORTS = (OPENROUTER_TRANSPORT, CODEX_TRANSPORT, CLAUDE_TRANSPORT)

# The map's first-rung seat. It is a reasoning model rather than the threads'
# quick one because the map's turn is a ruling on what a gesture cost the rest
# of the board -- work the threads' seat is not asked for and does not do -- and
# it is mid-weight rather than the expert because the human is waiting on it.
# Where its rulings prove inadequate the step-up is this model, not another
# rung.
DEFAULT_MAP_TRANSPORT = CODEX_TRANSPORT
DEFAULT_MAP_MODEL = "gpt-5.6-luna"
DEFAULT_MAP_EFFORT = "medium"

# What each model can hold, in tokens, captured 2026-08-22: the Claude figures
# from the bundled `claude-api` reference's model table, the Gemini one from
# Google's published input-token window for that model. A table of numbers
# somebody else controls goes stale without saying so, which is why it is a
# floor rather than an authority -- the per-tier overrides below restate a
# window that has moved without waiting for this line to be edited, and a model
# that is not in here has no known limit at all rather than a guessed one.
# Guessing is the failure that matters: an invented ceiling either cries wolf
# for a whole session or stays silent through the one that actually degrades.
CONTEXT_LIMITS: dict[str, int] = {
    "google/gemini-3.5-flash-lite": 1_048_576,
    "claude-opus-5": 1_000_000,
    # The CLI's own spelling of the same model at the same window.
    "claude-opus-5[1m]": 1_000_000,
}

# How full a tier's window may get before the backend says so. Three quarters,
# because the warning has to arrive while there is still room to act on it: a
# threshold at the ceiling is an obituary. A constant rather than configuration,
# since nothing about a session makes an earlier or later warning the right one
# -- what varies between sessions is the window, and that is what takes the
# overrides.
CONTEXT_WARN_FRACTION = 0.75

# The conversion used when the provider counted nothing for us. Four bytes to
# the token is the rough ratio for English prose, and it is only ever a
# sanity check: an estimate is labelled as one wherever it is reported, because
# a number nobody counted must not be read as one somebody did.
BYTES_PER_TOKEN = 4

# Who acts on a met escalation condition. Under `gated` the condition highlights
# the transfer control and nothing moves until the human presses it; under
# `autonomous` the backend moves that channel itself. Gated is the default
# because the other direction spends the owner's subscription on a condition
# they never watched fire -- and a session where they take every recommendation
# can turn this on rather than pay a confirmation gesture per turn.
POLICY_GATED = "gated"
POLICY_AUTONOMOUS = "autonomous"
ESCALATION_POLICIES = (POLICY_GATED, POLICY_AUTONOMOUS)
DEFAULT_ESCALATION_POLICY = POLICY_GATED

FAST_MODEL_ENV = "GRILLUI_FAST_MODEL"
HEAVY_MODEL_ENV = "GRILLUI_HEAVY_MODEL"
HEAVY_EFFORT_ENV = "GRILLUI_HEAVY_EFFORT"
MAP_TRANSPORT_ENV = "GRILLUI_MAP_TRANSPORT"
MAP_MODEL_ENV = "GRILLUI_MAP_MODEL"
MAP_EFFORT_ENV = "GRILLUI_MAP_EFFORT"
ESCALATION_POLICY_ENV = "GRILLUI_ESCALATION_POLICY"
FAST_CONTEXT_LIMIT_ENV = "GRILLUI_FAST_CONTEXT_LIMIT"
HEAVY_CONTEXT_LIMIT_ENV = "GRILLUI_HEAVY_CONTEXT_LIMIT"
API_KEY_ENV = "OPENROUTER_API_KEY"

DEFAULT_API_BASE = "https://openrouter.ai/api/v1"
CLAUDE_CLI = "claude"
CODEX_CLI = "codex"

# The CLI's own closed vocabulary for `--effort`. An effort outside it is a
# misconfiguration, and the CLI would refuse the turn rather than pick for us.
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


class UnknownTierError(ValueError):
    """A tier name outside the two this configuration defines."""

    def __init__(self, tier: str) -> None:
        super().__init__(f"unknown tier: {tier!r}")


class UnknownEffortError(ValueError):
    """An effort level the CLI would not accept."""

    def __init__(self, effort: str, name: str = HEAVY_EFFORT_ENV) -> None:
        super().__init__(
            f"unknown effort: {effort!r}; {name} must be one of {', '.join(EFFORT_LEVELS)}"
        )


class UnknownTransportError(ValueError):
    """A transport outside the three a seat may sit on."""

    def __init__(self, transport: str) -> None:
        super().__init__(
            f"unknown transport: {transport!r}; {MAP_TRANSPORT_ENV} must be one of "
            f"{', '.join(TRANSPORTS)}"
        )


class UnreadableLimitError(ValueError):
    """A context limit the environment stated in something that is not a count."""

    def __init__(self, name: str, raw: str) -> None:
        super().__init__(
            f"unreadable context limit: {name}={raw!r} must be a whole number of tokens"
        )


class UnknownPolicyError(ValueError):
    """An escalation policy outside the two this configuration defines."""

    def __init__(self, policy: str) -> None:
        super().__init__(
            f"unknown escalation policy: {policy!r}; {ESCALATION_POLICY_ENV} must be one of "
            f"{', '.join(ESCALATION_POLICIES)}"
        )


def _limit(source: Mapping[str, str], name: str) -> int | None:
    """One context-limit override, as the environment states it.

    Unset and empty both mean "no override"; anything else has to be a count.
    A typo that fell back to the table would put the warning back on the number
    the operator was overriding precisely because they knew it was wrong.
    """
    raw = source.get(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as error:
        raise UnreadableLimitError(name, raw) from error


@dataclass(frozen=True)
class Seat:
    """Who occupies a rung on one channel: a transport, a model, and an effort.

    Frozen for the same reason the configuration is: the turn is attributed to
    what it was asked of, and a seat that could be edited mid-turn is a log
    naming a model the request never went to.

    `effort` is nothing where the transport does not take one, and that is the
    honest shape rather than a missing field: an effort recorded on a turn that
    never sent one is an attribution nobody can act on, since it reads exactly
    like one that did.
    """

    transport: str
    model: str
    effort: str | None = None


@dataclass(frozen=True)
class TierConfig:
    """Which model each tier is, how hard the heavy one thinks, and how much
    each can be given before the backend starts saying so.

    Frozen because a turn must not be able to change the tier it is being
    attributed to halfway through: the id in the log is the id the request was
    made with.

    The two context limits are overrides and default to nothing, which is not
    the same as a limit of zero: unset means the shipped table answers, and the
    table answering with nothing means this model's window is unknown and no
    warning is owed about it.
    """

    fast_model: str = DEFAULT_FAST_MODEL
    heavy_model: str = DEFAULT_HEAVY_MODEL
    heavy_effort: str = DEFAULT_HEAVY_EFFORT
    map_transport: str = DEFAULT_MAP_TRANSPORT
    map_model: str = DEFAULT_MAP_MODEL
    map_effort: str = DEFAULT_MAP_EFFORT
    escalation_policy: str = DEFAULT_ESCALATION_POLICY
    fast_context_limit: int | None = None
    heavy_context_limit: int | None = None

    def __post_init__(self) -> None:
        # Refused here rather than at the first heavy turn: a session that got
        # its effort wrong should fail while the human is still watching the
        # launch, not silently run at an effort nobody chose. The policy is
        # refused the same way and for a sharper reason -- a misspelling that
        # fell back to a default would decide, silently, who is allowed to spend
        # the heavy tier's money.
        if self.heavy_effort not in EFFORT_LEVELS:
            raise UnknownEffortError(self.heavy_effort)
        if self.map_effort not in EFFORT_LEVELS:
            raise UnknownEffortError(self.map_effort, MAP_EFFORT_ENV)
        if self.map_transport not in TRANSPORTS:
            raise UnknownTransportError(self.map_transport)
        if self.escalation_policy not in ESCALATION_POLICIES:
            raise UnknownPolicyError(self.escalation_policy)

    @property
    def autonomous(self) -> bool:
        """Whether a met condition moves its channel without the human's gesture."""
        return self.escalation_policy == POLICY_AUTONOMOUS

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
            heavy_effort=source.get(HEAVY_EFFORT_ENV) or DEFAULT_HEAVY_EFFORT,
            map_transport=source.get(MAP_TRANSPORT_ENV) or DEFAULT_MAP_TRANSPORT,
            map_model=source.get(MAP_MODEL_ENV) or DEFAULT_MAP_MODEL,
            map_effort=source.get(MAP_EFFORT_ENV) or DEFAULT_MAP_EFFORT,
            escalation_policy=source.get(ESCALATION_POLICY_ENV) or DEFAULT_ESCALATION_POLICY,
            fast_context_limit=_limit(source, FAST_CONTEXT_LIMIT_ENV),
            heavy_context_limit=_limit(source, HEAVY_CONTEXT_LIMIT_ENV),
        )

    @property
    def thread_seat(self) -> Seat:
        """The first-rung seat every thread channel takes its turns on."""
        return Seat(OPENROUTER_TRANSPORT, self.fast_model)

    @property
    def map_seat(self) -> Seat:
        """The first-rung seat the map channel takes its turns on.

        An OpenRouter seat carries no effort whatever the effort is configured
        to be, because that transport is not sent one here: seating the map on
        the threads' seat is a transport and a model, and an effort left over
        from the seat before it would be attributed to a turn that never sent
        it.
        """
        if self.map_transport == OPENROUTER_TRANSPORT:
            return Seat(self.map_transport, self.map_model)
        return Seat(self.map_transport, self.map_model, self.map_effort)

    @property
    def expert_seat(self) -> Seat:
        """The one seat on the second rung, shared by every channel."""
        return Seat(CLAUDE_TRANSPORT, self.heavy_model, self.heavy_effort)

    def seat_for(self, channel: str) -> Seat:
        """Which first-rung seat this channel's next turn is composed by."""
        return self.map_seat if channel == MAP_CHANNEL else self.thread_seat

    def model_for(self, tier: str) -> str:
        if tier == FAST_TIER:
            return self.fast_model
        if tier == HEAVY_TIER:
            return self.heavy_model
        # A tier this configuration has never heard of must not be silently
        # billed to -- and attributed as -- the heavy model.
        raise UnknownTierError(tier)

    def limit_for(self, tier: str, model: str | None = None) -> int | None:
        """How many tokens this turn's model holds, or nothing if nobody knows.

        The override wins over the table, because the table is a snapshot of
        numbers this code does not own. Nothing at all is a real answer and the
        one that must not be rounded up into a number: a session on a model this
        table has never heard of gets no warning rather than a warning measured
        against a ceiling somebody made up.

        The model is asked for rather than derived from the tier, because a rung
        no longer names one model: the first rung seats the map and the threads
        separately, and reading the threads' window against the map seat's turn
        would warn -- or stay silent -- about a ceiling that is not this model's.
        The override stays keyed to the rung, since that is the knob an operator
        has.
        """
        if tier == FAST_TIER:
            return self.fast_context_limit or CONTEXT_LIMITS.get(model or self.fast_model)
        if tier == HEAVY_TIER:
            return self.heavy_context_limit or CONTEXT_LIMITS.get(model or self.heavy_model)
        raise UnknownTierError(tier)


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

# What the human pays to read a turn. A model asked to reason hard writes like
# it is reasoning hard, and the answer arrives buried in a clause of a sentence
# built for a reader with the whole context loaded. The human driving the board
# has half a minute and one pass, so the register is stated to every turn rather
# than left to the tier: it is the heavy tier, thinking longest, that drifts
# furthest from a sentence read once.
REGISTER_RULE = (
    "Write plainly: short, professional sentences a busy human reads once. Put the answer "
    "first and the reasoning after it. Use no term the decision does not need -- where one "
    "is unavoidable, say what it means in the same sentence."
)

ONE_TURN_RULE = (
    "This is one turn. Answer, then stop -- you are invoked again when there is "
    "something new to answer. Do not wait for anything, do not ask to be called back, "
    "and do not check for updates: nothing arrives while you are speaking."
)

# The reply is a reply. A model left to its own conversational instincts closes
# every turn with a question, because a question reads as engagement -- and the
# human, who came to think out loud, gets handed the work back each time. The two
# cases below are the whole licence; a third would be read as a licence for the
# trailing "which of these do you want?" this rule exists to end.
DIALOGUE_RULE = (
    "Your turn answers what the human just said; it is not a prompt for their next turn. "
    "Engage with the statement itself -- agree, disagree, name what it costs, say what it "
    "turns on. Ask a question in two cases only: when you cannot answer without knowing "
    "what they are actually asking, and when there is something they are not considering "
    "and should be. No other question belongs in a reply. Do not close by handing the "
    "options back, asking which they prefer, or asking whether there is anything else. A "
    "turn that ends on a statement is finished."
)

# How the fast tier takes a turn, and the whole of what is particular to it.
# What a turn is *for* is the role's, below: a mandate written here is inherited
# by whichever role happens to be running on this tier.
FAST_TIER_MANDATE = (
    "Answer from the context you were given, fast. This is the quick tier: the human is "
    "mid-thought and waiting on you, so a turn that arrives late has already cost them "
    "more than the detail it spent that time on is worth."
)

FACILITATION_MANDATE = (
    "You facilitate the discussion. Answer from the context you were given and keep the "
    "human moving. The moment a question crosses into reasoning, decisioning or implied "
    "design, stop short of deciding it: say what the question turns on and leave the "
    "decision with the human."
)

# What the grill-master's turn is for, on either tier. The sole-author line is
# the load-bearing one: an agent that does not know it owns the map reads its own
# ruling as a remark, and the board goes on offering decisions its reply called
# dead.
GRILL_MASTER_MANDATE = (
    "You are the grill-master: the author of the map and the only agent that changes it. "
    "The human answers decisions; you rule on what each answer does to the rest of the "
    "plan and keep the map honest after every gesture. Push on the axis the posture "
    "names. You speak to the human only in notices; when you judge the stop condition "
    "met, say so, and leave ending the session to them."
)

# The one step of the house grilling method the board does not already mechanise.
# The tree, the frontier, the round and the recommendation are the board's;
# fact-finding is impossible in a single call with no tools. What is left is what
# an answer does to everything it was not about, which is the turn's whole work.
RESHAPE_STEP = (
    "An answer settles its decision; say what else it did. Rule on every decision the "
    "dispatch names and on any other the answer undermines -- dead, changed, or standing, "
    "each with one line of why. Where the answer implies a decision the map lacks, add it "
    "with its prerequisites and what its options would put in question. Say whether the "
    "stop condition is met."
)

# How to read a board that moved. A thread agent is handed the record of every
# change and no key to it, and the failure that follows is not invention out of
# nothing: it is a plausible cause composed from `prereqs` while the actual
# rationale sits in the same bytes, unquoted.
BOARD_LEGEND = (
    "The board you are given is a record, not a summary. A decision's `status`, "
    "`rationale` and `history` are what happened to it and why: answer a question about "
    "why the board moved by quoting them, or by saying the record does not say -- never "
    "by inferring a cause. `prereqs` is what a decision waits on. `puts_in_question` on "
    "an option is the plan author's prediction that taking that option puts those "
    "decisions in question, which the grill-master rules on -- a mark, not a dependency. "
    "`pending` is what the human has not dealt with, including a notice this thread "
    "may have been opened from. A change in `history` carries `proposed_by`, the agent "
    "whose queued update the human's apply landed, and, where a ruling produced it, that "
    "`verdict` and its why -- so who proposed a move and what was ruled is quoted rather "
    "than inferred, and an entry carrying neither is a move nobody proposed and no ruling "
    "produced."
)

# The reply contract, and the whole of how a map mutation comes to exist. It is
# stated to the grill-master alone: a thread agent that emitted one would have it
# refused by the appender, and telling it the shape would be inviting the refusal.
#
# There is no prose mode, and the five keys are always present. A turn free to
# answer in prose answers in prose on the turn that mattered -- the incident is a
# reply that narrated three decisions as dead and moved none of them, which no
# checker could credit and no human could act on.
#
# What it must not say is that sending an update changes the board. Some land and
# some wait for the human, the split is drawn by the backend against the board at
# the moment the reply arrives, and a turn that believed its updates had landed
# would tell the human a decision was settled that is sitting in their queue.
DOCUMENT_FORMAT_RULE = (
    "Every turn you take is one JSON object and nothing else: no prose outside it, no "
    "markdown around it, and no key beyond the five below. All five are present on every "
    "turn -- put an empty list or string where you have nothing to say.\n"
    "- `text`: what you are saying to the human, under the concision rule. Empty where the "
    "board already says it.\n"
    '- `updates`: the map updates you are proposing, each like {"kind": "revise", "target": '
    f'"d1", ...}}. `kind` is one of {", ".join(sorted(FOLDABLE_KINDS))} and nothing else; the '
    "backend refuses a kind outside that list, and the refusal takes the whole turn with it.\n"
    "- `supersedes`: the ids of pending items of yours you are withdrawing.\n"
    "- `rulings`: your judgement on the decisions this gesture put in question, each {"
    '"decision": "d2", "ruling": "invalidate" | "revise" | "stands", "why": "one line"}.\n'
    '- `stop`: {"met": false, "why": ""} until you judge the stop condition met, and then '
    '{"met": true, "why": "why it is met"}.\n'
    "Sending an update is not making the change. An update that cannot overwrite anything "
    "the human decided lands when it arrives; one that can -- and every `unsettle` and "
    "`invalidate`, always -- waits in their queue until they apply it, and a decision with "
    "something waiting on it cannot be answered until they do. Your receipt says which of "
    "yours did which, so say what you are proposing and why rather than announcing that the "
    "board has changed."
)

# What a seat is told when its own last reply could not be read. Quoting the
# fault is the whole of the retry's value: a model told only that it was wrong
# guesses at a second shape, while one told which key was missing supplies it.
RETRY_RULE = (
    "Your last reply was refused because it is not the reply document. Send the same turn "
    "again as one JSON object carrying exactly `text`, `updates`, `supersedes`, `rulings` and "
    "`stop`, and nothing else. The fault was:"
)

# What an answer costs the rest of the board. A killing answer is the easiest
# thing to describe and the easiest to leave undone: saying that a run of
# decisions is now dead reads, to the agent writing it, as having dealt with
# them -- while the board goes on offering every one of them on the frontier for
# the human to answer. Naming and proposing are not the same act, and only the
# second moves anything.
MOOTNESS_RULE = (
    "When the human's answer bears on decisions other than the one they answered, rule on "
    "each of those in that same turn: `invalidate` where the answer leaves it no question to "
    "ask, carrying their answer as the rationale; `revise` where the answer changes what it "
    "asks; `stands` where it survives the answer intact. Do not merely say that a decision is "
    "dead, dropped or no longer applies: naming one changes nothing, and an `invalidate` or a "
    "`revise` moves it only when the same turn also carries that update."
)

# The same obligation as the rule above, on the one turn that owes it, naming
# the decisions rather than describing the case. The standing rule is a
# paragraph an agent has to recognise its own turn in; this is a list, and a
# list is both harder to read past and checkable afterwards -- which is what
# lets a fast reply that ignored it be handed up rather than believed.
MOOTNESS_OBLIGATION_RULE = (
    "Rule on each decision named above, in this turn, in your `rulings`: `invalidate` where "
    "the answer leaves it no question to ask, `revise` where the answer changes what it asks, "
    "or `stands` where it survives the answer intact. Each ruling carries one line of `why`. "
    "A ruling of `invalidate` or `revise` counts only where this same turn also carries that "
    "update against that decision -- saying a decision is dead is not proposing its death. A "
    "ruling of `stands` counts on its `why` alone, and that line is put on the decision for "
    "the human to read. The board is still offering every one of them: any you leave unruled, "
    "they are asked to answer."
)

# The same obligation for the other gesture that leaves decisions the board
# should stop offering. The three rulings are the same three; what differs is
# what each means here. A decision resting on one that died may stand without it,
# or may keep the dead prereq and survive the loss anyway, and choosing among the
# three is the judgement the turn is being asked for. A vocabulary of one verdict
# presses the agent to kill work that survives its prereq.
MOOTNESS_RESTING_RULE = (
    "Rule on each decision named above, in this turn, in your `rulings`: `invalidate` where "
    "it dies with the prereq that left the flow, `revise` where it survives once the dead "
    "prereq is dropped, or `stands` where it keeps the dead prereq and survives the loss "
    "anyway. Each ruling carries one line of `why`. A ruling of `invalidate` or `revise` "
    "counts only where this same turn also carries that update against that decision; a "
    "ruling of `stands` counts on its `why`. A prereq that has left the flow holds nothing, "
    "so the board is offering every one of them again: any you leave unruled, the human is "
    "asked to answer a question that may have died with its footing."
)

BASIS_RULE = (
    "Carry `basis`, the board's `seq` as you were given it, on each update. A proposal can "
    "wait while the human moves, and the basis is what lets the backend tell them your change "
    "was written against an older board rather than applying it over their work in silence."
)

SUPERSEDE_RULE = (
    "The board carries the queue of what the human has not dealt with yet -- your notices and "
    "the changes of yours still waiting -- each with its id. To withdraw ones you sent "
    "earlier, name those ids in `supersedes`. Withdraw rather than repeat yourself: the human "
    "is looking at that queue."
)

SUPERSEDE_CONFLICT_RULE = (
    "You withdrew something the human had already acted on, so your rewrite and their answer "
    "disagree. Only you can reconcile that -- nothing has been changed on the board and "
    "nothing will be until you say so. Say what still stands, and send the updates that make "
    "it true."
)

REASSESS_RULE = (
    "The human called for a full reassessment: go over every decision and everything in the "
    "queue above, say what no longer holds, and send the updates that fix it. Their board is "
    "frozen until you answer, so do it in this turn."
)

CATCH_UP_RULE = (
    "This thread was set aside and has just been picked back up. The board above is current; "
    "the list is what moved on it while you were away, so read it as the correction to "
    "whatever you last reasoned from. Answer the human's turn under the board as it now is."
)

# The one thread whose subject is the map itself. It rides the composed prompt
# rather than the role's standing brief because it is a property of the channel
# this turn runs on, and the role is the same one every side thread has: it
# authors nothing, and what it produces is a statement precise enough for the
# grill-master to act on. Told to steer without that reminder, the agent agrees
# to make the change -- which is the failure the thread exists to end.
MAP_THREAD_MANDATE = (
    "This thread is where the human asks for a change to the map itself. Your work is to "
    "turn what they want into a concrete statement of which decisions change and how: name "
    "each decision by its id, say what happens to it -- invalidated, revised, unsettled, "
    "added -- and why, and put anything you had to assume to the human rather than deciding "
    "it yourself. You still author nothing, and this thread anchors no decision: folding it "
    "is what hands your statement to the grill-master, which proposes the updates. So write "
    "the conclusion to be acted on by an agent that will not see this conversation."
)

CONCLUSION_ROUTING_RULE = (
    "A thread conclusion reaches you because you are the only agent that may act on it. "
    "Decide what it costs the board: fold it in as updates, or take it as context and say "
    "in your reply that nothing on the board changes and why. Both are answers; silence "
    "is not."
)

# What a thread agent is told about the threads it is not having. The stubs are
# there to be consulted rather than reasoned around, and the read surface is what
# turns a relevant stub into the body it stands for -- without which the agent
# either invents the other thread's content or ignores it.
THREAD_AGENT_MANDATE = (
    "You are a side-thread agent, working one thread of a grilling. The board crosses to "
    "you whole, and so does your own thread; every other live thread appears only as a "
    "stub naming its anchor decision, its title, its state and its conclusion if it "
    "reached one. Consult the stubs. When one is relevant to your thread, read that "
    "thread's full body through the backend's read surface rather than guessing at it. "
    "You recommend and never author changes to the map: a conclusion you reach goes to "
    "the grill-master when the human folds this thread, and a map update from you is "
    "refused. If the human asks you to change the map -- to invalidate, revise or settle a "
    "decision -- say plainly that you cannot, and that folding this thread is what puts "
    "your conclusion in front of the grill-master, who acts on it. Agreeing to do it is a "
    "promise nothing keeps."
)

# When a thread agent may offer its decision's answer, and how. The condition is
# stated as a property of the human's turns rather than as a judgment call,
# because a licence to compose is a licence to decide -- and the offer is framed
# as a thing the turn does rather than a thing it asks, so the human is never
# handed the work of declining one.
CONVERGENCE_RULE = (
    "When the human's own turns already carry the answer to this thread's anchor decision -- "
    "they stated the qualification themselves, or accepted in their own words one you put to "
    "them -- write it back as a `proposed_answer` object beside `text`: `decision`, this "
    "thread's anchor decision id; `option`, an option the decision already carries, or null "
    "where the answer stands on none; `text`, the answer in their words; and `because`, one "
    "line on why the thread reached it. Restating what they said is the whole of the licence. "
    "Composing an answer they have not endorsed is you deciding and calling it convergence, "
    "and proposing an option the decision does not carry is a change to the map, which is not "
    "yours to make. One proposal per turn, on this thread's anchor decision and never on any "
    "other -- a thread anchored to no decision, such as the one about the board itself, has "
    "no answer to offer and takes no `proposed_answer` at all. Build it on an "
    "option the decision already carries, or none. Never ask whether to write one: say what "
    "you take the thread to have settled and stop. The offer is the affordance, and putting "
    "it as a question hands them the work of declining it."
)

# How each tier takes a turn, and nothing about what the turn is for. The four
# rules are shared because they are properties of a turn rather than of a model;
# what the fast tier adds is its own speed and no mandate.
_TURN_RULES = [NO_MANUFACTURE_RULE, CONCISION_RULE, DIALOGUE_RULE, ONE_TURN_RULE]

FAST_SYSTEM_PROMPT = "\n\n".join([FAST_TIER_MANDATE, *_TURN_RULES])

HEAVY_SYSTEM_PROMPT = "\n\n".join(_TURN_RULES)

SYSTEM_PROMPTS: dict[str, str] = {
    FAST_TIER: FAST_SYSTEM_PROMPT,
    HEAVY_TIER: HEAVY_SYSTEM_PROMPT,
}

# What each agent's turn is for, stated to it first and identically on either
# tier. Held as a table so there is one place a role's brief is written and one
# place a test reads it from: a role composed inline per tier is a role that can
# be keyed to one.
ROLE_PROMPTS: dict[str, str] = {
    GRILL_MASTER: "\n\n".join([GRILL_MASTER_MANDATE, RESHAPE_STEP]),
    THREAD_AGENT: "\n\n".join([THREAD_AGENT_MANDATE, FACILITATION_MANDATE, BOARD_LEGEND]),
}

# The rules that follow from the role rather than describing it: what each agent
# may emit, and what it owes when it does. They sit after the tier's part because
# they are the contract for the reply, read once the turn knows what it is for.
ROLE_RULES: dict[str, list[str]] = {
    GRILL_MASTER: [DOCUMENT_FORMAT_RULE, MOOTNESS_RULE, BASIS_RULE, SUPERSEDE_RULE],
    THREAD_AGENT: [CONVERGENCE_RULE],
}


def system_prompt(tier: str, agent: str) -> str:
    """The standing brief for one turn: whose turn it is, then how it is taken.

    A tier is how a turn is taken and a role is what the turn is for, and the two
    vary independently -- either tier may drive the map or a thread. The role
    comes first, and it is the same text on both tiers: a mandate keyed to the
    tier is inherited by whichever role runs there, which is what puts the map's
    author under "stop short of deciding" on the turn whose work is a ruling.

    The register rule is joined here, once, rather than into either role's rules
    or either tier's prompt: what a turn costs the human to read is a property
    of every turn, and a rule copied per role is a rule that goes missing from
    the next one.
    """
    role = THREAD_AGENT if agent == THREAD_AGENT else GRILL_MASTER
    return "\n\n".join([ROLE_PROMPTS[role], SYSTEM_PROMPTS[tier], *ROLE_RULES[role], REGISTER_RULE])


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


def thread_kind(context: DispatchContext, channel: str) -> str:
    """What kind of thread a channel is, as the dispatched board says.

    Read off the context rather than the log because the context is what the
    agent was given: a turn briefed from one board and told what its channel is
    from another could be told it is steering the map by a thread the board it
    was handed does not carry. The map channel is no thread and answers "", and
    so does a thread that reached this context as a stub: a stub is another
    thread, and no turn runs on one.
    """
    return next(
        (
            one.kind
            for one in context.image2.threads
            if one.id == channel and isinstance(one, Thread)
        ),
        "",
    )


def compose(recorded: str, context: DispatchContext, entries: Sequence[LogEntry]) -> str:
    """One turn's prompt: the briefing, the board, and this channel's turns.

    The board crosses as the recorded dispatch bytes rather than as anything
    rebuilt from them. There is no elision path: a prompt that trimmed settled
    decisions would lose decisions the human made minutes ago, and neither the
    human nor the audit record would show which ones went missing.

    A dispatch sent to route a thread's conclusion says so in a section of its
    own, and so do the two the backend raises rather than the human: a
    withdrawal they got in front of, and the map doctor. Each of the three is
    inside those bytes either way, and a turn asked to find it there is a turn
    that may not -- the doctor's board in particular looks exactly like any
    other, and a turn left to infer that it was called would not.

    A dispatch reopening a set-aside thread says what moved while it was away in
    a section of its own, for the same reason and one more: the board is a
    snapshot, and a snapshot states what is true and never what changed.

    A dispatch carrying a mootness obligation says which decisions the answer
    it is replying to put in question, by id, in a section of its own. The
    standing brief already states the rule; what the fast tier does not do is
    find the pre-marks inside the board and work out that the rule is about this
    turn. Naming them is the same fact, stated where the turn cannot read past
    it.

    A turn running on the map thread is told what that thread is for. It rides
    here rather than in the role's standing brief because it is a property of
    the channel and not of the role: the same agent on the same tier is an
    ordinary side thread's the next turn.
    """
    channel = context.channel
    conversation = "\n".join(f"{turn.who}: {turn.text}" for turn in turns_of(entries, channel))
    concluded = context.conclusion
    conflict = context.conflict
    return "\n\n".join(
        [
            "## Briefing",
            briefing(entries),
            "## The board, whole",
            recorded,
            f"## This channel ({channel}), in order",
            conversation or "Nothing has been said on this channel yet.",
            *(
                ["## What this thread is for", MAP_THREAD_MANDATE]
                if thread_kind(context, channel) == MAP_THREAD_KIND
                else []
            ),
            *(
                []
                if concluded is None
                else [
                    f"## The conclusion of thread {concluded.thread!r}, to route",
                    concluded.text or "The thread reached no conclusion.",
                    CONCLUSION_ROUTING_RULE,
                ]
            ),
            *(
                []
                if conflict is None
                else [
                    "## A withdrawal the human got in front of",
                    f"You withdrew your {conflict.update.kind!r} notice "
                    f"{conflict.update.id!r} on decision {conflict.update.target!r}; the human "
                    f"had already answered it, at sequence {conflict.applied_at}.",
                    SUPERSEDE_CONFLICT_RULE,
                ]
            ),
            *(
                []
                if not context.catch_up
                else [
                    "## What moved while this thread was set aside",
                    "\n".join(
                        f"{item.seq}: {item.kind} on {item.target}"
                        + (f" -- {item.why}" if item.why else "")
                        for item in context.catch_up
                    ),
                    CATCH_UP_RULE,
                ]
            ),
            *(["## The map doctor", REASSESS_RULE] if context.reassess else []),
            *_mootness_section(context.mootness),
            "## Your turn",
            "Answer the last thing the human said, under the rules you were given.",
        ]
    )


def _mootness_section(obligation: MootnessObligation | None) -> list[str]:
    """The decisions this turn owes a proposal for, named by id.

    Two gestures leave one and they do not owe the same thing, so the section
    says which gesture it is about and what discharges it. Both name the ids
    rather than describing the case: the standing brief already states the rule,
    and what the fast tier does not do is find the structure in the board and
    work out that the rule is about this turn.
    """
    if obligation is None:
        return []
    named = ", ".join(obligation.ids)
    them = "it" if len(obligation.ids) == 1 else "them"
    if obligation.cause == INVALIDATE_KIND:
        return [
            "## What the invalidate the human just applied left standing",
            f"{obligation.target} has left the flow: {obligation.answer!r}. {named} "
            f"list a decision that has left the flow among their prereqs, and the board is "
            f"offering {them} again -- a dead prereq holds nothing.",
            MOOTNESS_RESTING_RULE,
        ]
    return [
        "## What the answer you are replying to puts in question",
        f"The human answered {obligation.target} with {obligation.answer!r}. That option "
        f"names {named}, and the board is still offering {them}.",
        MOOTNESS_OBLIGATION_RULE,
    ]
