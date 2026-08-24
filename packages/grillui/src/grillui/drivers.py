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
all.** The two roles answer in different shapes. A grill-master turn is the
reply document and nothing else -- notice, updates, withdrawals, rulings and
the stop judgement in one object, validated here, retried once on this seat
when it does not, and handed up rather than shown to the human as the bytes it
arrived in. A thread agent's turn is prose, optionally carrying the one offer
it may make. Either way the turn is submitted as a single gesture, so what the
human is told and what the turn declared arrive together or not at all, on the
channel the turn ran on, through the same appender the page writes through --
which is what makes the sole-author rule structural: a thread agent's updates
are refused there, and no driver holds a second way to the board.

Declaring is not applying. What an agent's update does on arrival -- land, or
wait in the human's queue for their gesture -- is decided against the board by
the fold, not here. No driver may pre-empt that: one that decided for itself
which of its updates were safe would be the agent applying its own turn again,
by a longer route.

**Every turn records what it was given, and a tier nearing its model's window
says so out loud.** The reply entry carries the request's bytes always and the
provider's own prompt count where the provider returned one; where it did not,
the bytes stand in at a stated ratio and are reported as the estimate they are.
Measured against the tier's context limit, a turn past three quarters of the
window raises a notice on the board and a line on the launch's stdout, naming
the tier, the model, what was measured and what the ceiling is. This is the
instrument the deferred elision machinery waits on: without it, a session that
outgrew its window would degrade with nothing to point at, and the decision to
build elision would rest on nobody's measurement.

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
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeVar
from uuid import uuid4

import httpx
from pydantic import ValidationError

from grillui.dispatch import GRILL_MASTER
from grillui.escalation import in_expert_mode, recommend, transfer_source, turns_of
from grillui.lane import AgentUnreachableError, DocumentRefusedError
from grillui.projector import fold
from grillui.schemas import (
    CONTEXT_BYTES_KEY,
    CONTEXT_LIMIT_KEY,
    EFFORT_KEY,
    FAST_TIER,
    FOLD_KIND,
    FOLLOWED_TRANSFER_KEY,
    HEAVY_TIER,
    MAP_CHANNEL,
    MODEL_KEY,
    PROMPT_TOKENS_KEY,
    PROPOSED_ANSWER_KEY,
    RECOMMENDATION_KEY,
    RULING_STANDS,
    RULINGS_KEY,
    STATUS_PHASE_TRANSFERRED,
    STOP_KEY,
    SUPERSEDES_KEY,
    TIER_KEY,
    TRANSFER_SOURCE_KEY,
    DispatchContext,
    EventSubmission,
    GrillMasterDocument,
    RejectedReceipt,
    Ruling,
    Stop,
    fault_summary,
)
from grillui.tiers import (
    API_KEY_ENV,
    BYTES_PER_TOKEN,
    CLAUDE_CLI,
    CLAUDE_TRANSPORT,
    CODEX_CLI,
    CODEX_TRANSPORT,
    CONTEXT_WARN_FRACTION,
    DEFAULT_API_BASE,
    RETRY_RULE,
    Seat,
    TierConfig,
    compose,
    system_prompt,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from typing import TextIO

    from grillui.escalation import Recommendation
    from grillui.lane import TurnDriver
    from grillui.log import SessionLog
    from grillui.schemas import LogEntry, Receipt

RESUME_FILE = "heavy-resume.json"
# The Codex chain's identities keep their own file rather than a second key in
# the heavy one: a channel may have both chains open at once -- the map's Codex
# seat and the expert turn the human transfers it to -- and one file keyed by
# channel could hold only one of them.
CODEX_RESUME_FILE = "codex-resume.json"
# One chain file per rung. A channel may have this transport on both rungs at
# once -- a session that seats the first rung on `claude`, with the expert seat
# behind it -- and one file keyed by channel could hold only one of the two
# conversations, so the expert would resume the first rung's and back again.
FIRST_RUNG_RESUME_FILE = "fast-resume.json"


def resume_file(tier: str) -> str:
    """Which chain file this rung's conversations are kept in."""
    return RESUME_FILE if tier == HEAVY_TIER else FIRST_RUNG_RESUME_FILE


REQUEST_TIMEOUT = 60.0

# What the map's seat may do, and it is nothing but answer. The CLI hands its
# agent a shell and a sandbox in whatever directory the backend was launched
# from, and a turn composing a ruling has no business in the human's working
# tree: left with the tool, it reads whatever repository the session happened to
# start in -- context nobody put in the dispatch, and latency nobody asked for.
# Both execution features are named because either alone leaves the other's tool
# on the turn. The sandbox and the approval policy ride behind them rather than
# instead of them: a tool that does not exist cannot be approved, and a
# configuration that stops naming one of these must still not be able to write.
CODEX_NO_TOOLS = [
    "-c",
    "features.shell_tool=false",
    "-c",
    "features.unified_exec=false",
    "-c",
    'sandbox_mode="read-only"',
    "-c",
    'approval_policy="never"',
]

# What the human is told when an offer arrives in a shape nothing can read.
# The offer's own bytes are deliberately not quoted back at them: an
# unreadable object is not made readable by printing it.
REFUSED_SHAPE = (
    "The agent offered an answer in a shape the board cannot read, so nothing was taken from it."
)

# A hosted model asked for an object commonly sends it inside a markdown fence,
# because that is how it was trained to present JSON to a reader. The fence is
# presentation, not content: a turn whose updates were dropped over three
# backticks is a turn the human watched arrive as prose with the board unmoved.
#
# The opening line carries an info string and then, as often as not, the start
# of the object itself -- a model writing the whole reply on one line is writing
# the same object as one that broke after the backticks. So the info string is
# matched for what it is, a bare language token, and everything after it is the
# body whichever side of a newline it fell on.
FENCED = re.compile(r"\A```[A-Za-z0-9_+.-]*[ \t]*(?P<body>.*?)\s*```\Z", re.DOTALL)


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
    """One completion from a hosted model, and what it counted the prompt at.

    The count comes back beside the text rather than being asked for
    afterwards, because it is a property of the response: a transport that
    stashed it would have to be asked which call it was answering about, and a
    second concurrent turn would get the wrong answer. `None` is the honest
    reply from a provider that reported no usage.
    """

    def __call__(
        self, *, model: str, system: str, prompt: str, shaped: bool = False
    ) -> tuple[str, int | None]: ...


class ClaudeCli(Protocol):
    """One CLI invocation, returning what it printed."""

    def __call__(self, argv: Sequence[str], /) -> str: ...


class CodexCli(Protocol):
    """One `codex exec` invocation, returning the JSONL stream it printed.

    The directory is the one the process runs in, and it is part of the call
    rather than the caller's ambient state: the CLI reads its working directory
    into the turn, and `resume` takes no flag for it.
    """

    def __call__(self, argv: Sequence[str], directory: Path, /) -> str: ...


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

    def __call__(
        self, *, model: str, system: str, prompt: str, shaped: bool = False
    ) -> tuple[str, int | None]:
        source = os.environ if self.environ is None else self.environ
        key = self.api_key or source.get(API_KEY_ENV)
        if not key:
            raise AgentUnreachableError(FAST_TIER)
        body = request_body(model, system, prompt, shaped)
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


def request_body(model: str, system: str, prompt: str, shaped: bool = False) -> dict[str, Any]:
    """The completion request. The standing brief is a system message rather
    than a preamble on the prompt, so it cannot be read as something the human
    said.

    A grill-master turn asks the provider for the reply document by schema.
    Asking is not trusting: the driver validates what comes back whatever the
    request said, because a provider that ignores the field, downgrades it, or
    honours it approximately fails silently and looks exactly like one that did
    not.
    """
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    if shaped:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "grill_master_turn",
                "schema": GrillMasterDocument.model_json_schema(),
            },
        }
    return body


def read_completion(document: Any) -> tuple[str, int | None]:
    """The reply text out of a completion response, and its prompt token count.

    The text is required and the count is not: a missing or oddly-typed `usage`
    costs the turn its measurement and nothing else, because a response that
    answered the human is not a failure just because it declined to say what it
    cost. What must not happen is a zero standing in for an absent count -- the
    warning would then read every unmeasured turn as roomy.
    """
    content = document["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise MalformedCompletionError
    usage = document.get("usage") if isinstance(document, dict) else None
    counted = usage.get("prompt_tokens") if isinstance(usage, dict) else None
    return content, counted if isinstance(counted, int) else None


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
        raise AgentUnreachableError(HEAVY_TIER, _process_fault(error)) from error
    return finished.stdout


CLI_INPUT_TOKEN_KEYS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def cli_input_tokens(usage: Any) -> int | None:
    """What the CLI turn was given, in tokens, out of its usage block.

    All three input-side counts, summed. `input_tokens` alone is what the model
    read that was not already cached, which on a resumed chain is the last
    exchange and nothing else -- a few hundred tokens against a conversation of
    two hundred thousand. Reporting that as the context would be reporting the
    delta as the total, and the tier would read as empty right up to the turn
    the chain overflowed.

    Nothing is the answer when there is no usage to read, and a count this
    cannot parse contributes nothing rather than a zero.
    """
    if not isinstance(usage, dict):
        return None
    counts = [usage.get(key) for key in CLI_INPUT_TOKEN_KEYS]
    found = [one for one in counts if isinstance(one, int)]
    return sum(found) if found else None


def read_cli_reply(printed: str) -> tuple[str, str | None, int | None]:
    """The reply, the chain's identity, and what the turn's prompt counted at,
    out of what the CLI printed."""
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
    return (
        text,
        session_id if isinstance(session_id, str) else None,
        cli_input_tokens(document.get("usage")),
    )


def codex_argv(seat: Seat, system: str, prompt: str, resume: str | None) -> list[str]:
    """One `codex exec` turn's arguments, cold or resumed.

    The brief rides on every invocation, not just the cold one: a resumed thread
    inherits none of it, so a driver that supplied it once would resume into a
    conversation briefed for a role it no longer knows it has.

    Values are handed to `-c` as TOML, so each is quoted as one: an unquoted
    string is taken literally only where it fails to parse, which makes what a
    brief means depend on whether it happens to look like TOML.

    Nothing here asks the transport to shape the reply. `--output-schema` is the
    provider's strict structured-output mode, which requires every object in the
    schema to be closed -- and a map update is deliberately untyped, since each
    entry is judged as its own kind by the appender. The schema that satisfies
    the provider makes the model emit an empty object for every update: a turn
    that proposes nothing, silently, which is worse than the refusal it would
    replace. The shape is asked for in the standing brief and checked here.
    """
    argv = [CODEX_CLI, "exec"]
    if resume is not None:
        argv += ["resume", resume]
    # The session directory is not a repository and the process is not launched
    # from one it owns. Without this the CLI refuses the turn outright, on a
    # trust check about the working directory that has nothing to say about a
    # turn which runs no commands.
    argv += ["--json", "--skip-git-repo-check", "--model", seat.model]
    argv += ["-c", f"developer_instructions={json.dumps(system)}"]
    # Nothing is watching a desktop notification for a turn the board is already
    # showing a waiting clock for.
    argv += ["-c", "notify=[]"]
    argv += CODEX_NO_TOOLS
    if seat.effort is not None:
        argv += ["-c", f"model_reasoning_effort={json.dumps(seat.effort)}"]
    return [*argv, prompt]


def run_codex_cli(argv: Sequence[str], directory: Path, /) -> str:
    """The Codex seat's transport: one process, run to completion, stdin closed,
    in the session's own directory.

    Closed rather than inherited: `codex exec` reads its prompt from standard
    input when one is piped, so a process with an open stream nobody is writing
    waits on it for as long as the session lasts. The prompt is an argument
    here, and the closed stream is what says so.

    The directory is the session's rather than the one the backend was launched
    in, because the CLI reads its working directory into the turn -- the
    instructions it finds there and what it says about the tree. A grilling is
    about the plan in the dispatch and not about whichever repository the human
    happened to start the session from. It is set on the process rather than
    passed as a flag: `exec` takes one and `resume` does not, and the two turns
    have to run in the same place.
    """
    try:
        finished = subprocess.run(  # noqa: S603 -- argv is built here, never a shell string
            list(argv),
            capture_output=True,
            text=True,
            check=True,
            timeout=REQUEST_TIMEOUT,
            stdin=subprocess.DEVNULL,
            cwd=directory,
        )
    except (OSError, subprocess.SubprocessError) as error:
        # A non-zero exit, a timeout and a binary that is not there are three
        # different mornings, and the process said which on its standard error.
        # Carried through bounded rather than dropped: the lane's error phase is
        # the only place anybody looks, and "could not be reached" on its own
        # sends them to reproduce it by hand.
        raise AgentUnreachableError(FAST_TIER, _process_fault(error)) from error
    return finished.stdout


def _process_fault(error: BaseException) -> str:
    """What the transport said about its own failure, as far as it said anything."""
    said = getattr(error, "stderr", None)
    return said if isinstance(said, str) and said.strip() else f"{type(error).__name__}: {error}"


def codex_input_tokens(usage: Any) -> int | None:
    """What the turn was given, in tokens, out of a `turn.completed` usage block.

    `input_tokens` is the whole input side and `cached_input_tokens` is the part
    of it the provider served from cache, so the two are not added: summing them
    would count the cached prefix twice and report a window filling up at
    roughly double the rate it is.

    Nothing is the answer where there is no usage to read, and a count this
    cannot parse contributes nothing rather than a zero -- an unmeasured turn
    must not read as an empty one.
    """
    if not isinstance(usage, dict):
        return None
    counted = usage.get("input_tokens")
    return counted if isinstance(counted, int) else None


def read_codex_reply(printed: str, tier: str) -> tuple[str, str | None, int | None]:
    """The reply, the thread's identity, and what the turn counted at, out of
    the JSONL stream `codex exec --json` printed.

    The reply is the last `agent_message` item rather than the last item: the
    stream also carries the CLI's own diagnostics as completed items, and a
    reader taking whatever finished last would put a hook warning into the log
    as the agent's turn.

    A line that will not parse is skipped rather than fatal. What must not be
    skipped is the absence of any agent message at all -- that is a turn nobody
    took, and it surfaces as an unreachable seat rather than as an empty reply.
    """
    thread_id: str | None = None
    said: str | None = None
    counted: int | None = None
    faults: list[str] = []
    for line in printed.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "thread.started":
            found = event.get("thread_id")
            thread_id = found if isinstance(found, str) else thread_id
        elif kind == "item.completed":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                said = text if isinstance(text, str) else said
            elif isinstance(item, dict) and item.get("type") == "error":
                message = item.get("message")
                faults.append(message if isinstance(message, str) else "an unreadable error item")
        elif kind == "turn.completed":
            counted = codex_input_tokens(event.get("usage"))
    if said is None:
        # The stream's own error items are what it carried instead of a turn,
        # and they are the only account of why there is nothing to record.
        raise AgentUnreachableError(tier, "; ".join(faults) or "the stream carried no turn")
    return said, thread_id, counted


def sent_bytes(system: str, prompt: str) -> int:
    """How big this turn's request was, in bytes.

    The standing brief counts: it crosses on every turn and is a real part of
    what the model has to hold. Measured on the encoded bytes rather than on
    the string's length, because a character is not a byte and the estimate
    downstream is a bytes-per-token one.
    """
    return len(system.encode("utf-8")) + len(prompt.encode("utf-8"))


@dataclass(frozen=True)
class Measurement:
    """What one turn's context came to, and what that is against its tier's model.

    Kept as one value rather than as loose numbers because the three travel
    together: what was measured, whether anybody counted it or it was estimated,
    and the window it is being read against. Splitting them is how a report
    ends up stating an estimate as a count.
    """

    tier: str
    context_bytes: int
    prompt_tokens: int | None
    limit: int | None

    @classmethod
    def of(
        cls,
        config: TierConfig,
        tier: str,
        context_bytes: int,
        prompt_tokens: int | None,
        model: str | None = None,
    ) -> Measurement:
        """This turn's size, against the window of the model that took it.

        The model is the seat's rather than the rung's: two seats share the
        first rung, and measuring one against the other's ceiling is the
        made-up number this whole measurement exists to avoid.
        """
        return cls(tier, context_bytes, prompt_tokens, config.limit_for(tier, model))

    @property
    def counted(self) -> bool:
        """Whether the provider counted this, as against it being estimated."""
        return self.prompt_tokens is not None

    @property
    def tokens(self) -> int:
        """The count where there is one, and the bytes estimate where there is not."""
        if self.prompt_tokens is not None:
            return self.prompt_tokens
        return self.context_bytes // BYTES_PER_TOKEN

    @property
    def recorded(self) -> dict[str, Any]:
        """What the reply entry carries about its own size.

        The limit rides even when it is nothing, because "no warning was owed"
        and "nobody knows this model's window" are different states and only one
        of them is evidence that the session had room.
        """
        payload: dict[str, Any] = {
            CONTEXT_BYTES_KEY: self.context_bytes,
            CONTEXT_LIMIT_KEY: self.limit,
        }
        if self.prompt_tokens is not None:
            payload[PROMPT_TOKENS_KEY] = self.prompt_tokens
        return payload

    @property
    def pressed(self) -> bool:
        """Whether this turn has taken the tier near the model's ceiling."""
        return self.limit is not None and self.tokens >= self.limit * CONTEXT_WARN_FRACTION

    def warn(self, log: SessionLog, model: str, out: TextIO | None = None) -> None:
        """Say, in both places a human might be looking, that a tier is filling up.

        Two surfaces because there are two humans: the one watching the board,
        who gets a notice on the lane the board keeps for things it has nowhere
        else to put, and the one who launched the session in a terminal and is
        reading its stdout. Neither is a status entry -- the lane's mechanics
        are hidden from the board on purpose, and a warning nobody sees is the
        silent degradation this exists to prevent.

        It is said on every turn that measures over the threshold rather than
        once. A session that is three quarters of the way through its window is
        not in a state one notice covers, and a lane the human has scrolled past
        is one they have to be told again.
        """
        if not self.pressed:
            return
        said = (
            f"The {self.tier!r} tier's context is at {self.tokens:,} tokens against "
            f"{model}'s {self.limit:,}, over {int(CONTEXT_WARN_FRACTION * 100)}% of the window. "
            + (
                "The provider counted that."
                if self.counted
                else f"Nothing counted it; that is {self.context_bytes:,} bytes of prompt "
                f"estimated at {BYTES_PER_TOKEN} bytes to the token."
            )
        )
        log.record("informational", {"text": said})
        print(f"grillui: {said}", file=sys.stdout if out is None else out, flush=True)


def attribution_of(tier: str, seat: Seat) -> dict[str, Any]:
    """Who took this turn: the rung it ran on, and the seat that sat on it.

    The effort rides only where the seat has one, because the key's presence is
    itself the claim that the request carried it. A seat on a transport that
    takes no effort would otherwise be recorded as having been asked to think as
    hard as the last one that was.
    """
    said: dict[str, Any] = {TIER_KEY: tier, MODEL_KEY: seat.model}
    if seat.effort is not None:
        said[EFFORT_KEY] = seat.effort
    return said


# What a channel the policy moved is told, on the entry that moves it.
POLICY_MOVED = "the escalation policy moved this channel to the expert tier: "


def advise(
    log: SessionLog, entries: Sequence[LogEntry], channel: str, attribution: dict[str, Any]
) -> Recommendation | None:
    """The escalation condition this turn met, put on its attribution.

    A property of the rung rather than of the transport, which is why it is
    here: both seats on the first rung owe the same recommendation, and one that
    only the OpenRouter seat made would go silent the moment a channel was
    seated elsewhere.
    """
    advice = recommend(fold(log.epoch, entries), turns_of(entries, channel), channel)
    if advice is not None:
        attribution[RECOMMENDATION_KEY] = advice.as_payload()
    return advice


@dataclass
class FastDriver:
    """The first rung over OpenRouter: facilitate, do not decide, and say when
    to hand up.

    `seat` is which model this instance is, and it defaults to the threads'.
    The same driver seats the map where a session configures it there, and then
    the model it names is the map seat's -- one class, two seats, because what
    differs between them is configuration and not transport.
    """

    config: TierConfig = field(default_factory=TierConfig)
    transport: FastTransport = field(default_factory=OpenRouterTransport)
    tier: str = FAST_TIER
    seat: Seat | None = None

    def run(self, log: SessionLog, dispatch: Path, /) -> None:
        recorded = dispatch.read_text(encoding="utf-8")
        context = DispatchContext.model_validate_json(recorded)
        channel = context.channel
        entries = log.entries()
        seat = self.seat if self.seat is not None else self.config.thread_seat
        model = seat.model
        system = system_prompt(FAST_TIER, context.agent)
        prompt = compose(recorded, context, entries)
        ruling_turn = context.agent == GRILL_MASTER

        def ask(text: str) -> tuple[str, int | None]:
            return self.transport(model=model, system=system, prompt=text, shaped=ruling_turn)

        reply, prompt_tokens = (
            take_document(self.tier, prompt, ask, _first) if ruling_turn else ask(prompt)
        )
        measured = Measurement.of(
            self.config, self.tier, sent_bytes(system, prompt), prompt_tokens, model
        )
        attribution: dict[str, Any] = {**attribution_of(self.tier, seat), **measured.recorded}
        advice = advise(log, entries, channel, attribution)
        # The reply and everything it produces land under one hold of the
        # append lock -- the same discipline the lane uses to keep a turn and
        # the word about it adjacent. Two separate appends leave a window: a
        # human turn accepted inside it is scheduled against a log where this
        # channel is still fast, so the turn the policy just bought is composed
        # by the tier it moved off -- and a warning that measured this reply
        # would be filed against whatever landed in between.
        #
        # The transfer it triggers and the warning it measured are emitted
        # after it, and only if the reply landed: a turn nobody could record is
        # not a turn whose recommendation is worth spending the heavy tier on,
        # nor one whose size is worth telling the human about. Under the lock
        # that costs nothing -- a refusal raises out of the block before either
        # is written, and nothing else could have read the log in between.
        with log.appending():
            record_reply(log, self.tier, channel, reply, attribution)
            if advice is not None and self.config.autonomous:
                log.emit_status(STATUS_PHASE_TRANSFERRED, POLICY_MOVED + advice.condition, channel)
            measured.warn(log, model)


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
    seat: Seat | None = None
    _turn: threading.Lock = field(default_factory=threading.Lock, repr=False, init=False)

    def run(self, log: SessionLog, dispatch: Path, /) -> None:
        recorded = dispatch.read_text(encoding="utf-8")
        context = DispatchContext.model_validate_json(recorded)
        channel = context.channel
        entries = log.entries()
        seat = self.seat if self.seat is not None else self.config.expert_seat
        model = seat.model
        effort = seat.effort or self.config.heavy_effort
        # A thread reopened across a board that moved opens a cold chain rather
        # than resuming one formed against the older board. The catch-up and the
        # thread's turns both cross in this dispatch, so nothing is lost; what is
        # dropped is a chain carrying a dozen older snapshots, which has no
        # reason to read the newest as a correction rather than as more of the
        # same. The old record is discarded as the turn opens rather than kept
        # for a null session id to fall back on.
        cold = bool(context.catch_up)
        # The rung's brief, not the expert's: a session may seat this transport
        # on a channel's first rung, and a turn briefed as the expert while the
        # lane, the attribution and the hand-up all call it `fast` is a seat
        # answering as a rung it is not on.
        system = system_prompt(self.tier, context.agent)
        chains = resume_file(self.tier)
        prompt = compose(recorded, context, entries)

        def ask(text: str) -> tuple[str, str | None, int | None]:
            # The chain is read fresh and written back on every attempt, so the
            # retry a refused document buys resumes the turn that was refused
            # rather than opening a second conversation about it.
            printed = self.cli(
                claude_argv(
                    model, effort, system, text, read_resume(log.directory, channel, chains)
                )
            )
            outcome = read_cli_reply(printed)
            if outcome[1] is not None:
                write_resume(log.directory, channel, outcome[1], chains)
            return outcome

        with self._turn:
            if cold:
                forget_resume(log.directory, channel, chains)
            reply, _chain, prompt_tokens = (
                take_document(self.tier, prompt, ask, _first)
                if context.agent == GRILL_MASTER
                else ask(prompt)
            )
        # The bytes are this turn's alone and the count is the whole resumed
        # chain's, which is why the count is the one that matters here: what
        # fills a heavy tier's window is the conversation it is resuming, and
        # this turn's prompt is the smallest part of it.
        measured = Measurement.of(
            self.config, self.tier, sent_bytes(system, prompt), prompt_tokens, model
        )
        attribution: dict[str, Any] = {
            TIER_KEY: self.tier,
            MODEL_KEY: model,
            EFFORT_KEY: effort,
            **measured.recorded,
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
        # One hold of the append lock, for the same reason the fast tier takes
        # one: a warning is about the reply immediately above it, and a turn on
        # another channel landing between the two would leave the human reading
        # this measurement against somebody else's turn. The warning is second
        # and conditional on the reply -- a refusal raises out of the block
        # before anything is said about a turn that never happened.
        with log.appending():
            record_reply(log, self.tier, channel, reply, attribution)
            measured.warn(log, model)


@dataclass
class CodexDriver:
    """A first-rung seat on the Codex transport: one resumed thread, one turn at
    a time.

    The same shape as the expert seat's chain and for the same reasons. The
    thread's identity is written into the session directory rather than held in
    memory, so a backend restarted over that directory picks the conversation
    back up instead of paying for a cold one; the lock is the one-process rule
    made structural, since two turns resuming one thread is not a slow session
    but a wrong one.

    It sits on the first rung, not a third one: a channel seated here still
    names the `fast` tier, still offers *Transfer to expert*, and hands a turn
    it could not take up to the same expert every other channel has.
    """

    config: TierConfig = field(default_factory=TierConfig)
    cli: CodexCli = run_codex_cli
    tier: str = FAST_TIER
    seat: Seat | None = None
    _turn: threading.Lock = field(default_factory=threading.Lock, repr=False, init=False)
    _counted: dict[str, int] = field(default_factory=dict, repr=False, init=False)

    def run(self, log: SessionLog, dispatch: Path, /) -> None:
        recorded = dispatch.read_text(encoding="utf-8")
        context = DispatchContext.model_validate_json(recorded)
        channel = context.channel
        entries = log.entries()
        seat = self.seat if self.seat is not None else self.config.map_seat
        # The same cold-open rule the expert chain has: a thread reopened across
        # a board that moved starts a new conversation rather than resuming one
        # formed against the older board.
        cold = bool(context.catch_up)
        ruling_turn = context.agent == GRILL_MASTER
        system = system_prompt(self.tier, context.agent)
        prompt = compose(recorded, context, entries)

        def ask(text: str) -> tuple[str, str | None, int | None]:
            # The thread is read fresh and written back on every attempt, so the
            # retry a refused document buys resumes the turn that was refused
            # rather than opening a second conversation about it.
            printed = self.cli(
                codex_argv(
                    seat, system, text, read_resume(log.directory, channel, CODEX_RESUME_FILE)
                ),
                log.directory,
            )
            said, thread, total = read_codex_reply(printed, self.tier)
            if thread is not None:
                write_resume(log.directory, channel, thread, CODEX_RESUME_FILE)
            # Read against the baseline here rather than on the accepted reply,
            # because a refused attempt still ran: the provider's total counts
            # it, and a baseline that only moved on the attempt that landed
            # would bill the accepted turn for every rejected one before it.
            return said, thread, self._read_since(channel, total)

        with self._turn:
            if cold:
                forget_resume(log.directory, channel, CODEX_RESUME_FILE)
                self._counted.pop(channel, None)
            reply, _thread, prompt_tokens = (
                take_document(self.tier, prompt, ask, _first) if ruling_turn else ask(prompt)
            )
        # The count is what this turn was given, out of a total the thread keeps,
        # and the bytes are this turn's alone -- which is why the count is the
        # one that matters: what fills the window is the conversation being
        # resumed, and this turn's own prompt is the smallest part of it.
        measured = Measurement.of(
            self.config, self.tier, sent_bytes(system, prompt), prompt_tokens, seat.model
        )
        attribution: dict[str, Any] = {**attribution_of(self.tier, seat), **measured.recorded}
        advice = advise(log, entries, channel, attribution)
        # One hold of the append lock, for the reason every other seat takes
        # one: the transfer a policy buys and the warning this turn measured are
        # about the reply immediately above them.
        with log.appending():
            record_reply(log, self.tier, channel, reply, attribution)
            if advice is not None and self.config.autonomous:
                log.emit_status(STATUS_PHASE_TRANSFERRED, POLICY_MOVED + advice.condition, channel)
            measured.warn(log, seat.model)

    def _read_since(self, channel: str, total: int | None) -> int | None:
        """What this turn was given, out of the running total the thread reports.

        The count on `turn.completed` is the thread's input so far and not this
        turn's: it accumulates across turns and across the processes that took
        them, so a conversation holding thirty thousand tokens reports a hundred
        thousand by its third turn. Recorded raw it would be a window warning
        that fires on arithmetic rather than on a full window, which is the
        made-up ceiling this measurement exists to avoid.

        Held in memory rather than on disk. A backend restarted mid-session then
        over-reports exactly one turn -- it has no earlier total to subtract --
        against a limit that is unknown for this seat's model anyway, which is a
        cheaper wrong number than a second file to keep consistent.

        A total that did not grow is not a number to state: something other than
        this driver moved the thread, and an unmeasured turn falls back to the
        estimate rather than to a count nobody can stand behind.
        """
        if total is None:
            return None
        read = total - self._counted.get(channel, 0)
        self._counted[channel] = total
        return read if read > 0 else None


def seat_driver(config: TierConfig, seat: Seat, tier: str = FAST_TIER) -> TurnDriver:
    """The driver that takes a seat's turns.

    The one place a transport becomes a driver. A seat is configuration and a
    driver is code, and mapping one to the other anywhere else is how a session
    ends up attributed to a model a different transport answered.
    """
    if seat.transport == CODEX_TRANSPORT:
        return CodexDriver(config, tier=tier, seat=seat)
    if seat.transport == CLAUDE_TRANSPORT:
        return HeavyDriver(config, tier=tier, seat=seat)
    return FastDriver(config, tier=tier, seat=seat)


def read_resume(directory: Path, channel: str, file: str = RESUME_FILE) -> str | None:
    """The chain this channel is already having, if there is one.

    Read from the directory on every turn rather than remembered, so the
    successor of a killed process resumes what its predecessor started.

    The file is named because a channel may be having two chains at once, one
    per transport, and each seat resumes its own.
    """
    found = _chains(directory / file).get(channel)
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


def write_resume(directory: Path, channel: str, session_id: str, file: str = RESUME_FILE) -> None:
    """Remember the chain, per channel: the map's and each thread's are separate
    conversations and must not resume into each other."""
    path = directory / file
    with _REWRITE:
        _write_json(path, {**_chains(path), channel: session_id})


def forget_resume(directory: Path, channel: str, file: str = RESUME_FILE) -> None:
    """Drop this channel's chain, leaving every other channel's alone.

    What a cold turn does on the way in. Dropping it now rather than letting the
    turn's own session id overwrite it is the difference that matters when the
    turn returns none: the channel then holds no chain, instead of falling back
    to the one the cold turn was opened to get away from.
    """
    path = directory / file
    with _REWRITE:
        chains = _chains(path)
        if chains.pop(channel, None) is not None:
            _write_json(path, chains)


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


def _write_json(path: Path, payload: Any) -> None:
    # Written whole and renamed into place: a crash mid-write must cost the
    # documented cold start, never leave half a file racing the reader -- and
    # the reader here is sometimes another process entirely, which would take
    # half a schema as a schema.
    scratch = path.with_suffix(".tmp")
    scratch.write_text(json.dumps(payload), encoding="utf-8")
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
    document = _document(reply)
    if document is None:
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


def _document(reply: str) -> dict[str, Any] | None:
    """The object a reply carries, fence and all read through, or None where the
    reply is prose."""
    fenced = FENCED.match(reply.strip())
    try:
        document = json.loads(fenced.group("body") if fenced else reply)
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


def document_problem(reply: str) -> str | None:
    """Why this reply is not a grill-master turn, or None where it is one.

    Every fault names the key it is about, because that is what makes the one
    retry worth taking: a seat told only that it was wrong guesses at a second
    shape, while one told that `rulings` was missing supplies it.
    """
    carried = _document(reply)
    if carried is None:
        return "the reply was prose, not the reply document"
    try:
        document = GrillMasterDocument.model_validate(carried)
    except ValidationError as error:
        return fault_summary(error, "document")
    # A withdrawal rides on the turn's entry, so a turn that withdraws while
    # giving nothing to record has no entry to put it on and the gesture is
    # lost. Judged here rather than at the append, because here is where the
    # seat is told what was wrong and gets its one retry -- and adding a line
    # of `text` is exactly the fix a seat can make.
    if document.supersedes and not sub_updates(document):
        return "supersedes: a withdrawal needs `text`, an update or a ruling to ride on"
    return None


def read_document(reply: str) -> GrillMasterDocument:
    """The turn this reply is. Only ever called on one already validated."""
    return GrillMasterDocument.model_validate(_document(reply) or {})


_Outcome = TypeVar("_Outcome")


def take_document(
    tier: str,
    prompt: str,
    attempt: Callable[[str], _Outcome],
    said: Callable[[_Outcome], str],
) -> _Outcome:
    """One grill-master turn, retried once on the same seat when what came back
    is not the document.

    One retry and no more. A model that lost the shape usually finds it again
    when told which key was wrong, and paying an expert turn for a formatting
    slip spends the human's waiting clock on nothing; a seat that missed twice
    with the fault quoted is not going to find it on a third ask, and the rung
    above is where the turn goes instead.
    """
    outcome = attempt(prompt)
    problem = document_problem(said(outcome))
    if problem is None:
        return outcome
    outcome = attempt(f"{prompt}\n\n## Your last reply was refused\n{RETRY_RULE} {problem}")
    problem = document_problem(said(outcome))
    if problem is not None:
        raise DocumentRefusedError(tier, problem)
    return outcome


def _first(outcome: tuple[str, Any] | tuple[str, Any, Any]) -> str:
    """What the seat said, out of whatever else its transport returned with it."""
    return outcome[0]


def _proposal_refusal(
    log: SessionLog, channel: str, reply: str, taken: dict[str, Any] | None
) -> str | None:
    """Why the answer this reply offered cannot be taken, in a line addressed to
    the human, or None where there is nothing to refuse.

    A reply that names `proposed_answer` at all has recognisably offered one, so
    it is never left to arrive as its own raw bytes: the human reading a thread
    is owed the sentence saying what the agent tried and why the board would not
    take it. The anchor is asked first, because an offer aimed at a decision
    this thread is not about is refused for that whatever else is wrong with it
    -- and the map channel and the session-scoped thread anchor nothing, so an
    offer arriving on either is answered by the same question.
    """
    document = _document(reply)
    if document is None or PROPOSED_ANSWER_KEY not in document:
        return None
    offered = document[PROPOSED_ANSWER_KEY]
    if not isinstance(offered, dict):
        return REFUSED_SHAPE
    anchor = log.anchor_of(channel)
    named = offered.get("decision")
    if named != anchor:
        return (
            f"The agent offered an answer to {named!r}, and this conversation "
            f"{'anchors no decision' if anchor is None else f'is about {anchor!r}'}, "
            f"so the board did not take it."
        )
    return None if taken is not None else REFUSED_SHAPE


def sub_updates(document: GrillMasterDocument) -> list[dict[str, Any]]:
    """Everything one turn puts on the board, in the order the human meets it.

    The notice it spoke, the changes it proposed, the why behind each decision
    it ruled standing, and its judgement that the grilling is over. Built in one
    place because two readers ask the same question of it: the validator, which
    refuses a withdrawal with nothing to ride on, and the recorder, which needs
    at least one of these to have an entry at all.
    """
    notice = [{"kind": "informational", "text": document.text}] if document.text.strip() else []
    minted = [stands_notice(one) for one in document.rulings if one.ruling == RULING_STANDS]
    return [*notice, *document.updates, *minted, *stop_notice(document.stop)]


def stands_notice(one: Ruling) -> dict[str, Any]:
    """What a `stands` ruling puts in front of the human.

    A ruling of `stands` has no update behind it -- the decision goes on being
    offered, which is the point -- so its `why` would otherwise be a judgement
    nothing recorded. Targeted at the decision it rules on, it renders there
    rather than on the notification lane, and a Discuss opened from it anchors
    to the same decision.
    """
    return {
        "kind": "informational",
        "target": one.decision,
        "text": f"{one.decision} stands: {one.why}",
    }


def stop_notice(stop: Stop) -> list[dict[str, Any]]:
    """The turn saying the grilling is over, where it says so.

    A notice and not a gesture: ending the session is the human's, and this is
    what they act on. It rides the lane the board already keeps for what the
    board itself does not show, so nothing on the page has to learn a new shape
    to carry it.
    """
    if not stop.met:
        return []
    said = "The stop condition is met."
    return [{"kind": "informational", "text": f"{said} {stop.why}" if stop.why else said}]


def record_document(
    log: SessionLog, tier: str, document: GrillMasterDocument, attribution: dict[str, Any]
) -> None:
    """Put a grill-master turn into the log, whole.

    The turn is one gesture: the notice, the updates it proposes, and the
    informational each `stands` ruling mints, all under one entry, because a
    turn whose ruling landed and whose update did not is a board the human
    cannot make sense of.

    `rulings` and `stop` ride as payload keys on the entry itself, the way a
    thread turn carries its offered answer -- the kind vocabulary is closed, and
    a ruling is something a turn does while it says its piece rather than an
    event of its own. They ride on every turn, empty or not: the obligation
    check reads coverage off them, and a key that is sometimes absent is a check
    that sometimes reads a turn that ruled as a turn that could not.
    """
    updates = sub_updates(document)
    if not updates:
        # Every key validated and the turn still carries nothing: no notice, no
        # proposal, no ruling. Nothing is appended, because every entry shape
        # here holds content and inventing some would put words in the agent's
        # mouth. This is not a failed turn and must not be raised as one -- the
        # turn is on the record in its own dispatch file and in the lane's
        # pair, and a turn that ruled on nothing is exactly what the coverage
        # check upstream exists to decide about. Raising here would skip the
        # ladder that owes this case a hand-up and then a notice.
        #
        # A withdrawal is the exception: `supersedes` rides on an entry, so a
        # turn that withdrew something and gave nothing to record it on has
        # lost the gesture. That is a failed turn rather than a silent drop.
        if document.supersedes:
            raise ReplyRefusedError(tier, "it withdrew items with nothing to record them on")
        return
    if document.supersedes:
        updates[0] = {**updates[0], SUPERSEDES_KEY: document.supersedes}
    judgement = {
        RULINGS_KEY: [one.model_dump() for one in document.rulings],
        STOP_KEY: document.stop.model_dump(),
    }
    # The turn spoke and did nothing else: with one sub-update and a notice in
    # it, the notice is what that one is, since everything else contributed
    # none. It rides as the entry itself rather than inside a fold.
    solo = len(updates) == 1 and bool(document.text.strip())
    payload: dict[str, Any] = (
        {**{key: value for key, value in updates[0].items() if key != "kind"}, **attribution}
        if solo
        else {"updates": updates, **attribution}
    )
    kind = "informational" if solo else FOLD_KIND
    _submit(log, tier, MAP_CHANNEL, kind, {**payload, **judgement})


def record_reply(
    log: SessionLog, tier: str, channel: str, text: str, attribution: dict[str, Any]
) -> None:
    """Put the turn into the log, attributed.

    An agent is a client of the same appender the page writes through, so a
    reply is judged like any other write and a refusal is not swallowed: the
    human asked something, and a reply nobody can read is not an answer.

    A map turn is a document and nothing else, and it is recorded by the
    function above. What is left here is a thread agent's turn, which is prose
    and may carry the one offer it is allowed to make.

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
    if channel == MAP_CHANNEL:
        record_document(log, tier, read_document(text), attribution)
        return
    prose, updates, superseded, proposal = declared_updates(text)
    refusal = _proposal_refusal(log, channel, text, proposal)
    if refusal is not None:
        # The agent's own words survive where the reply had any; where the
        # object was the whole reply, the refusal is what there is to say, and
        # it stands in for bytes no human should have been shown.
        prose = f"{prose}\n\n{refusal}" if proposal is not None else refusal
        proposal = None
    if not prose.strip():
        raise ReplyRefusedError(tier, "the completion was empty")
    spoken: dict[str, Any] = {"kind": "thread-turn", "text": prose}
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
    _submit(log, tier, channel, FOLD_KIND if updates else "thread-turn", payload)


def _submit(log: SessionLog, tier: str, channel: str, kind: str, payload: dict[str, Any]) -> None:
    """The one way a turn reaches the log: through the appender the page writes
    through, so a driver holds no second path to the board."""
    receipt = log.submit(
        [
            EventSubmission(
                kind=kind,
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
