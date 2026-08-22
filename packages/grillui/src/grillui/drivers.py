"""The two tiers as drivers: one turn each, one invocation, then gone.

Both implement the same seam, and neither holds an agent open between turns. A
turn is picked up, answered into the log, and over -- there is no resident
process, no loop, and nothing an agent waits on, because the orchestrator is
what decides when any agent gets a turn. An agent that spent its turn asking
whether there was anything to do would spend the turn on transport.

**The fast tier** is one HTTP call to a hosted model, at about a second and a
fraction of a cent. Whether its reply should have gone up a tier is not asked of
the model: the conditions are evaluated against the transcript in code, and what
they produce rides on the reply as metadata. Who acts on that metadata is the
session's escalation policy -- the human, by default, and the backend itself
under `autonomous`, which puts the channel on the heavy tier through the lane so
the move is on the record rather than in memory.

**The heavy tier** is one CLI turn against a resumed chain. The chain's identity
is written into the session directory rather than held in memory, so a backend
restarted over that directory picks the same conversation back up instead of
starting a cold one; the cold turn costs about ten times a resumed one, which is
what makes that file worth writing. One turn at a time, always: the discount
lives in a cache one process holds, and two processes talking over each other on
the same chain forfeit it. One turn is opened cold on purpose: the one reopening
a thread whose board moved while it was set aside, whose chain reasoned from a
board that no longer holds.

**A reply may declare map updates, and only the grill-master's are heard at
all.** A turn answers in prose, or in an object carrying prose and the updates
it wants made; the second is submitted as one gesture, so what the human is
told and what the turn declared arrive together or not at all. The gesture is
submitted on the channel the turn ran on, through the same appender the page
writes through, which is what makes the sole-author rule structural: a thread
agent's updates are refused there, and no driver holds a second way to the
board.

Declaring is not applying. What an agent's update does on arrival -- land, or
wait in the human's queue for their gesture -- is decided against the board by
the fold, not here. No driver may pre-empt that: one that decided for itself
which of its updates were safe would be the agent applying its own turn again,
by a longer route.

**A reply that says nothing is a failure, not a turn.** Whatever the cause --
transport, an empty completion, an appender that refused the reply -- it raises,
and the lane surfaces it as an error in milliseconds rather than as silence the
human watches a timer against.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

import httpx

from grillui.escalation import in_expert_mode, recommend, transfer_source, turns_of
from grillui.lane import AgentUnreachableError
from grillui.projector import fold
from grillui.schemas import (
    EFFORT_KEY,
    FAST_TIER,
    FOLD_KIND,
    FOLLOWED_TRANSFER_KEY,
    HEAVY_TIER,
    MAP_CHANNEL,
    MODEL_KEY,
    PROPOSED_ANSWER_KEY,
    RECOMMENDATION_KEY,
    STATUS_PHASE_TRANSFERRED,
    SUPERSEDES_KEY,
    TIER_KEY,
    TRANSFER_SOURCE_KEY,
    DispatchContext,
    EventSubmission,
    RejectedReceipt,
)
from grillui.tiers import (
    API_KEY_ENV,
    CLAUDE_CLI,
    DEFAULT_API_BASE,
    TierConfig,
    compose,
    system_prompt,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from grillui.log import SessionLog
    from grillui.schemas import Receipt

RESUME_FILE = "heavy-resume.json"
REQUEST_TIMEOUT = 60.0

# A hosted model asked for an object commonly sends it inside a markdown fence,
# because that is how it was trained to present JSON to a reader. The fence is
# presentation, not content: a turn whose updates were dropped over three
# backticks is a turn the human watched arrive as prose with the board unmoved.
FENCED = re.compile(r"\A```[^\n]*\n(?P<body>.*?)\n?```\Z", re.DOTALL)


class ReplyRefusedError(RuntimeError):
    """A turn that produced nothing the log would take.

    An empty completion and a refused append are the same thing from the
    human's side -- they asked something and no answer exists -- so both surface
    rather than being written off as a turn that happened.
    """

    def __init__(self, tier: str, detail: str) -> None:
        super().__init__(f"the {tier!r} tier produced no reply: {detail}")


class MalformedCompletionError(TypeError):
    """A completion whose content is not text.

    A `TypeError` so the transport's own failure path catches it beside the
    other ways a response can be unusable: from the human's side they are one
    outcome -- no reply exists.
    """


class FastTransport(Protocol):
    """One completion from a hosted model."""

    def __call__(self, *, model: str, system: str, prompt: str) -> str: ...


class ClaudeCli(Protocol):
    """One CLI invocation, returning what it printed."""

    def __call__(self, argv: Sequence[str], /) -> str: ...


@dataclass
class OpenRouterTransport:
    """The fast tier's transport: one chat completion, no streaming, no retry.

    A turn is the unit of work, so a failed one is reported as a failed turn --
    the human is looking at the lane and can ask again, which is cheaper and
    more honest than a driver that quietly spends three times the budget.

    `client` exists so the transport can be exercised against a scripted server:
    the parsing and the failure paths are where this can go wrong, and they are
    worth running for real.
    """

    api_key: str | None = None
    api_base: str = DEFAULT_API_BASE
    client: httpx.Client | None = None
    environ: Mapping[str, str] | None = None

    def __call__(self, *, model: str, system: str, prompt: str) -> str:
        source = os.environ if self.environ is None else self.environ
        key = self.api_key or source.get(API_KEY_ENV)
        if not key:
            raise AgentUnreachableError(FAST_TIER)
        body = request_body(model, system, prompt)
        headers = {"Authorization": f"Bearer {key}"}
        try:
            if self.client is not None:
                response = self.client.post(self._url, json=body, headers=headers)
            else:
                with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                    response = client.post(self._url, json=body, headers=headers)
            response.raise_for_status()
            return read_completion(response.json())
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
            raise AgentUnreachableError(FAST_TIER) from error

    @property
    def _url(self) -> str:
        return f"{self.api_base}/chat/completions"


def request_body(model: str, system: str, prompt: str) -> dict[str, Any]:
    """The completion request. The standing brief is a system message rather
    than a preamble on the prompt, so it cannot be read as something the human
    said."""
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }


def read_completion(document: Any) -> str:
    """The reply text out of a completion response."""
    content = document["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise MalformedCompletionError
    return content


def claude_argv(model: str, effort: str, system: str, prompt: str, resume: str | None) -> list[str]:
    """One CLI turn's arguments.

    Structured output is asked for because the chain's identity comes back in
    it: the reply alone would leave the next turn no way to continue this
    conversation rather than open a new one. The effort is passed on every turn
    rather than only the first: a resumed chain does not inherit it.
    """
    argv = [CLAUDE_CLI, "-p", "--output-format", "json", "--model", model, "--effort", effort]
    argv += ["--append-system-prompt", system]
    if resume is not None:
        argv += ["--resume", resume]
    return [*argv, prompt]


def run_claude_cli(argv: Sequence[str], /) -> str:
    """The heavy tier's transport: one process, run to completion."""
    try:
        finished = subprocess.run(  # noqa: S603 -- argv is built here, never a shell string
            list(argv), capture_output=True, text=True, check=True, timeout=REQUEST_TIMEOUT
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AgentUnreachableError(HEAVY_TIER) from error
    return finished.stdout


def read_cli_reply(printed: str) -> tuple[str, str | None]:
    """The reply and the chain's identity, out of what the CLI printed."""
    try:
        document = json.loads(printed)
        text = document["result"]
    except (ValueError, KeyError, TypeError) as error:
        raise AgentUnreachableError(HEAVY_TIER) from error
    if not isinstance(text, str):
        # The same contract as the fast tier's non-text completion: a result
        # that is not text is a malformed transport reply, never something to
        # stringify into the log as if the model said it.
        raise AgentUnreachableError(HEAVY_TIER)
    session_id = document.get("session_id")
    return text, session_id if isinstance(session_id, str) else None


@dataclass
class FastDriver:
    """The fast tier: facilitate, do not decide, and say when to hand up."""

    config: TierConfig = field(default_factory=TierConfig)
    transport: FastTransport = field(default_factory=OpenRouterTransport)
    tier: str = FAST_TIER

    def run(self, log: SessionLog, dispatch: Path, /) -> None:
        recorded = dispatch.read_text(encoding="utf-8")
        context = DispatchContext.model_validate_json(recorded)
        channel = context.channel
        entries = log.entries()
        model = self.config.fast_model
        reply = self.transport(
            model=model,
            system=system_prompt(FAST_TIER, context.agent),
            prompt=compose(recorded, context, entries),
        )
        attribution: dict[str, Any] = {TIER_KEY: self.tier, MODEL_KEY: model}
        advice = recommend(fold(log.epoch, entries), turns_of(entries, channel), channel)
        if advice is not None:
            attribution[RECOMMENDATION_KEY] = advice.as_payload()
        # The reply and the transfer it triggers land under one hold of the
        # append lock -- the same discipline the lane uses to keep a turn and
        # the word about it adjacent. Two separate appends leave a window: a
        # human turn accepted inside it is scheduled against a log where this
        # channel is still fast, so the turn the policy just bought is composed
        # by the tier it moved off.
        #
        # The transfer is emitted second, and only if the reply landed: a turn
        # nobody could record is not a turn whose recommendation is worth
        # spending the heavy tier on. Under the lock that costs nothing --
        # a refusal raises out of the block before the transfer is written, and
        # nothing else could have read the log in between.
        with log.appending():
            record_reply(log, self.tier, channel, reply, attribution)
            if advice is not None and self.config.autonomous:
                log.emit_status(
                    STATUS_PHASE_TRANSFERRED,
                    "the escalation policy moved this channel to the expert tier: "
                    f"{advice.condition}",
                    channel,
                )


@dataclass
class HeavyDriver:
    """The heavy tier: one resumed CLI turn, one at a time.

    The lock is the single-process rule made structural. Two heavy turns racing
    on one chain is not a slow session but a wrong one -- the second resumes a
    conversation the first is still adding to.
    """

    config: TierConfig = field(default_factory=TierConfig)
    cli: ClaudeCli = run_claude_cli
    tier: str = HEAVY_TIER
    _turn: threading.Lock = field(default_factory=threading.Lock, repr=False, init=False)

    def run(self, log: SessionLog, dispatch: Path, /) -> None:
        recorded = dispatch.read_text(encoding="utf-8")
        context = DispatchContext.model_validate_json(recorded)
        channel = context.channel
        entries = log.entries()
        model = self.config.heavy_model
        effort = self.config.heavy_effort
        # A thread reopened across a board that moved opens a cold chain rather
        # than resuming one formed against the older board. The catch-up and the
        # thread's turns both cross in this dispatch, so nothing is lost; what is
        # dropped is a chain carrying a dozen older snapshots, which has no
        # reason to read the newest as a correction rather than as more of the
        # same. The old record is discarded as the turn opens rather than kept
        # for a null session id to fall back on.
        cold = bool(context.catch_up)
        with self._turn:
            if cold:
                forget_resume(log.directory, channel)
            printed = self.cli(
                claude_argv(
                    model,
                    effort,
                    system_prompt(HEAVY_TIER, context.agent),
                    compose(recorded, context, entries),
                    None if cold else read_resume(log.directory, channel),
                )
            )
            reply, session_id = read_cli_reply(printed)
            if session_id is not None:
                write_resume(log.directory, channel, session_id)
        attribution: dict[str, Any] = {
            TIER_KEY: self.tier,
            MODEL_KEY: model,
            EFFORT_KEY: effort,
            # Whether this heavy turn followed a transfer, read off the same
            # channel mode the lane routed it by: no agent escalates itself, and
            # a heavy turn nobody moved the channel for must not be able to
            # claim it was asked for.
            FOLLOWED_TRANSFER_KEY: in_expert_mode(entries, channel),
        }
        # Only where the policy moved the channel. A human gesture writes no
        # source, so the log a `gated` session keeps is unchanged.
        source = transfer_source(entries, channel)
        if source is not None:
            attribution[TRANSFER_SOURCE_KEY] = source
        record_reply(log, self.tier, channel, reply, attribution)


def read_resume(directory: Path, channel: str) -> str | None:
    """The chain this channel is already having, if there is one.

    Read from the directory on every turn rather than remembered, so the
    successor of a killed process resumes what its predecessor started.
    """
    found = _chains(directory / RESUME_FILE).get(channel)
    return found if isinstance(found, str) else None


# One lock over the resume file's read-modify-write. Every channel keeps its own
# key but they share one file, so two rewrites at once would each read the whole
# map and the later rename would drop the other channel's chain -- that channel
# then pays for a cold start nothing recorded and nobody asked for. The heavy
# tier's turn lock keeps two turns apart today, but that lock exists to stop two
# processes talking over one chain, and this file's consistency must not rest on
# a guarantee made for something else.
#
# ponytail: one lock for the process, which serves one session directory;
# per-directory locks if a process ever serves several.
_REWRITE = threading.Lock()


def write_resume(directory: Path, channel: str, session_id: str) -> None:
    """Remember the chain, per channel: the map's and each thread's are separate
    conversations and must not resume into each other."""
    path = directory / RESUME_FILE
    with _REWRITE:
        _write_chains(path, {**_chains(path), channel: session_id})


def forget_resume(directory: Path, channel: str) -> None:
    """Drop this channel's chain, leaving every other channel's alone.

    What a cold turn does on the way in. Dropping it now rather than letting the
    turn's own session id overwrite it is the difference that matters when the
    turn returns none: the channel then holds no chain, instead of falling back
    to the one the cold turn was opened to get away from.
    """
    path = directory / RESUME_FILE
    with _REWRITE:
        chains = _chains(path)
        if chains.pop(channel, None) is not None:
            _write_chains(path, chains)


def _chains(path: Path) -> dict[str, Any]:
    """Every channel's chain, or none of them: a torn write costs a cold start
    and nothing else, which is cheaper than refusing a turn over a cache file."""
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_chains(path: Path, chains: dict[str, Any]) -> None:
    # Written whole and renamed into place: a crash mid-write must cost the
    # documented cold start, never leave half a file racing the reader.
    scratch = path.with_suffix(".tmp")
    scratch.write_text(json.dumps(chains), encoding="utf-8")
    scratch.replace(path)


def declared_updates(
    reply: str,
) -> tuple[str, list[dict[str, Any]], list[str], dict[str, Any] | None]:
    """What the turn said, the map updates it declared, what it withdrew, and
    the answer it offered.

    A reply is prose unless it is an object carrying `text` and at least one of
    the three -- anything else, including JSON that is not this shape, is what
    the agent said and is recorded as such. Guessing at a half-shaped object
    would author board changes out of a reply that never asked for any.

    A markdown fence around that object is read through, because what the turn
    declared is a property of what it said and not of how the model chose to
    present it. Only the fence comes off: what is inside still has to be the
    shape, and a fenced reply that is not gets recorded as prose, fence and all,
    exactly as the model wrote it.

    Withdrawing is separate from updating because the common case carries no
    board change at all: a turn that supersedes what it said last time and
    nothing else is a turn whose whole effect is on the queue. An offered answer
    is separate from both for the same reason and one more: it is the only one
    of the three a thread agent may make, so a reply carrying it and nothing
    else is the ordinary declaring shape on a thread channel.

    Whether the offer is usable is not judged here. This reads what the turn
    said; the fold decides what the board can do with it, so an offer and the
    prose it rode in on cannot be judged by two readers that disagree.
    """
    fenced = FENCED.match(reply.strip())
    try:
        document = json.loads(fenced.group("body") if fenced else reply)
    except ValueError:
        return reply, [], [], None
    if not isinstance(document, dict):
        return reply, [], [], None
    prose = document.get("text")
    updates = document.get("updates")
    superseded = document.get(SUPERSEDES_KEY)
    offered = document.get(PROPOSED_ANSWER_KEY)
    declared = updates if isinstance(updates, list) else None
    withdrew = superseded if isinstance(superseded, list) else None
    proposal = offered if isinstance(offered, dict) else None
    if not isinstance(prose, str) or (declared is None and withdrew is None and proposal is None):
        return reply, [], [], None
    return (
        prose,
        [one for one in declared or [] if isinstance(one, dict)],
        [one for one in withdrew or [] if isinstance(one, str)],
        proposal,
    )


def record_reply(
    log: SessionLog, tier: str, channel: str, text: str, attribution: dict[str, Any]
) -> None:
    """Put the turn into the log, attributed.

    An agent is a client of the same appender the page writes through, so a
    reply is judged like any other write and a refusal is not swallowed: the
    human asked something, and a reply nobody can read is not an answer.

    A reply declaring map updates is submitted as one gesture carrying them and
    the prose together, and it is submitted on the channel the turn ran on --
    which is what makes the sole-author rule structural rather than advisory. A
    thread agent that declared updates has them refused by the same appender
    that refuses them over the wire, and the lane says so; there is no second
    path to the board for a driver to take.

    Which of the declared updates land and which wait for the human is not this
    function's question and must not become one: it is a property of the board
    at the moment the gesture arrives, answered once by the fold.

    What the reply withdrew rides on the turn's own spoken entry, and so does
    the answer it offered, because that is what each is: this turn replacing
    what a previous one told the human, or putting to them what it takes the
    thread to have settled, in the same breath as it says the new thing.
    """
    prose, updates, superseded, proposal = declared_updates(text)
    if not prose.strip():
        raise ReplyRefusedError(tier, "the completion was empty")
    spoken: dict[str, Any] = {
        "kind": "informational" if channel == MAP_CHANNEL else "thread-turn",
        "text": prose,
    }
    if superseded:
        spoken[SUPERSEDES_KEY] = superseded
    if proposal is not None:
        spoken[PROPOSED_ANSWER_KEY] = proposal
    # The kind is the envelope's when the turn stands alone and the sub-update's
    # when it rides inside a gesture, so it is stripped from the one and kept on
    # the other -- everything else the turn said travels either way.
    solo = {key: value for key, value in spoken.items() if key != "kind"}
    payload: dict[str, Any] = (
        {**solo, **attribution} if not updates else {"updates": [spoken, *updates], **attribution}
    )
    receipt = log.submit(
        [
            EventSubmission(
                kind=FOLD_KIND if updates else str(spoken["kind"]),
                actor="grill-master" if channel == MAP_CHANNEL else "thread-agent",
                channel=channel,
                idempotency_key=f"{tier}-{uuid4().hex}",
                payload=payload,
            )
        ],
        log.epoch,
    )[0]
    if receipt.status != "accepted":
        raise ReplyRefusedError(tier, _refusal(receipt))


def _refusal(receipt: Receipt) -> str:
    if isinstance(receipt, RejectedReceipt):
        return f"the appender refused it: {receipt.reason}"
    return f"the appender answered {receipt.status!r}"
