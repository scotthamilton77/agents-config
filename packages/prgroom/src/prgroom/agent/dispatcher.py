"""Provider-chain dispatch + fallback ladder (§5 agent-CLI config & fallback).

A :class:`ClusterDispatcher` / :class:`FixDispatcher` is the concrete
implementation of the foundation's ``ClusterContract`` / ``FixContract`` Protocol.
It resolves a per-contract **provider chain** (§5) — a primary plus ordered
fallbacks — tries the primary, and on a fallback-triggering failure falls to the
next link:

* the agent binary is not on ``PATH`` (``FileNotFoundError`` from the spawn);
* the agent exits non-zero (quota / auth / network — the runner reports the code);
* the agent exceeds its per-contract time budget (``AgentTimeoutError``);
* the agent exits 0 but emits JSON that fails to parse into the contract output.

If **every** link fails, the dispatcher raises :class:`AllProvidersFailedError` —
a ``RUNTIME_AGENT_UNAVAILABLE`` :class:`~prgroom.errors.PrgroomError` the lifecycle
maps to a ``failed`` disposition + ``EscalationSink`` event (§5), never a crash.

The chain is resolved by :func:`load_chain` from the per-repo ``.prgroom.toml``
``[agents.cluster]`` / ``[agents.fix]`` sections — read through the foundation TOML
loader (:func:`prgroom.config._read_toml`) so the agent config shares the one
``.prgroom.toml`` parse path — falling back to the shipped default chains. A
``--cluster-model`` / ``--fix-model`` override swaps the primary provider's model.

Audits (cluster coverage, fix commit/disposition checks) are deliberately NOT
here — they are the agent-audits bead's job. This layer owns only get-valid-JSON-
or-fall-through; it parses the output shape but does not validate its invariants.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeVar

from prgroom.agent.contracts import (
    ClusterInput,
    ClusterOutput,
    FixInput,
    FixOutput,
)
from prgroom.agent.prompt_loader import PromptTemplate, load_prompt
from prgroom.agent.subprocess_runner import (
    AgentCancelledError,
    AgentRunner,
    AgentSpec,
    AgentTimeoutError,
)
from prgroom.agent.usage import UsageRecord
from prgroom.config import _read_toml, _subtable
from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.prsession.pr_ref import PRRef

ContractName = Literal["cluster", "fix"]

# The contract output type the fallback ladder parses (ClusterOutput / FixOutput).
T = TypeVar("T")

# Default per-contract wall-clock budget for one agent invocation (one cluster /
# the whole cluster set). Conservative; a later config knob may make it per-chain.
DEFAULT_CLUSTER_BUDGET_S = 120.0
DEFAULT_FIX_BUDGET_S = 1800.0

# The shipped default provider chains (§5). Each entry is (cli, model, extra).
_DEFAULT_CHAINS: dict[ContractName, list[AgentSpec]] = {
    "cluster": [
        AgentSpec(cli="ollama", model="gemma4"),
        AgentSpec(cli="claude", model="haiku", extra={"effort": "high"}),
        AgentSpec(cli="codex", model="gpt-5.4-mini"),
    ],
    "fix": [
        AgentSpec(cli="claude", model="opus[1m]", extra={"effort": "xhigh"}),
        AgentSpec(cli="codex", model="gpt-5.5", extra={"write": True}),
    ],
}

_DEFAULT_BUDGETS: dict[ContractName, float] = {
    "cluster": DEFAULT_CLUSTER_BUDGET_S,
    "fix": DEFAULT_FIX_BUDGET_S,
}

# The ordered TOML keys that form a chain in `[agents.<contract>]`. `primary` is
# required when the section is present; the fallbacks are optional and consumed in
# this fixed order so chain ordering is deterministic, not dict-iteration order.
_CHAIN_KEYS = ("primary", "fallback", "fallback2", "fallback3")

# TOML provider keys that are NOT part of `extra` — they are the structural fields.
_STRUCTURAL_KEYS = frozenset({"cli", "model", "timeout"})

# Cap on a single link's failure reason in the escalation detail (post-collapse),
# so a verbose agent stderr cannot bloat the one-line summary. Capping keeps the
# head AND the tail (tracebacks and CLI stderr put the actual error LAST).
_REASON_MAX_CHARS = 120
_REASON_HEAD_CHARS = 40
_REASON_ELLIPSIS = " ... "


@dataclass(frozen=True, slots=True)
class ProviderChain:
    """An ordered provider chain plus the shared per-contract time budget.

    ``time_budget_s`` applies **per chain link**, not per dispatch: each provider
    gets the full budget (unless its own ``timeout`` TOML key overrides it), so the
    worst-case wall-clock for one dispatch is budget x chain length — all while the
    per-PR lock is held.
    """

    providers: list[AgentSpec]
    time_budget_s: float


class AllProvidersFailedError(PrgroomError):
    """Every provider in the chain failed (§5 both-fail).

    A ``RUNTIME_AGENT_UNAVAILABLE`` error the lifecycle maps to a ``failed``
    disposition + escalation. ``detail`` chains each link's failure so the
    escalation names what was tried and why each was rejected.
    """

    def __init__(self, *, detail: str) -> None:
        # §3.7 pins RUNTIME_AGENT_UNAVAILABLE to RUNTIME_TRANSIENT (exit 75): the
        # scheduler retries on the next cadence, preserving §3.6 restart-safety for
        # the un-dispositioned items. A terminal tier would human-gate and break it.
        super().__init__(
            tier=Tier.RUNTIME_TRANSIENT,
            code=ErrorCode.RUNTIME_AGENT_UNAVAILABLE,
            detail=detail,
        )


def _spec_from_toml(raw: Mapping[str, Any], *, path: str) -> AgentSpec:
    """Build an :class:`AgentSpec` from one TOML provider table at ``path``.

    ``cli`` + ``model`` are required structural fields; an optional ``timeout``
    (positive seconds) overrides the contract's per-link budget for this provider.
    Every other key (``effort``, ``write``, …) flows into ``extra`` so the
    per-invoker shapes can read them without this loader knowing each CLI's
    options. ``path`` is the provider's full ``agents.<contract>.<key>`` path,
    named in the error so a user sees which entry is malformed.
    """
    cli = raw.get("cli")
    model = raw.get("model")
    if not isinstance(cli, str) or not isinstance(model, str):
        msg = f"{path} needs string cli + model, got {raw!r}"
        raise ValueError(msg)  # noqa: TRY004  # config-domain validation; ValueError is the loader's uniform type
    budget: float | None = None
    raw_timeout = raw.get("timeout")
    if raw_timeout is not None:
        # bool is an int subclass — `timeout = true` must not become a 1s budget.
        if (
            isinstance(raw_timeout, bool)
            or not isinstance(raw_timeout, int | float)
            or raw_timeout <= 0
        ):
            msg = f"{path}.timeout must be a positive number (seconds), got {raw_timeout!r}"
            raise ValueError(msg)
        budget = float(raw_timeout)
    extra = {k: v for k, v in raw.items() if k not in _STRUCTURAL_KEYS}
    return AgentSpec(cli=cli, model=model, extra=extra, time_budget_s=budget)


def _chain_from_toml(contract: ContractName, section: Mapping[str, Any]) -> list[AgentSpec]:
    """Read ``primary`` … ``fallback3`` from a present ``[agents.<contract>]`` section.

    A present section MUST define ``primary``: a fallback-only section would build a
    chain with fallback-as-head, and a key-less one an empty chain that later raises
    a contentless both-fail. Both are baffling misconfigs, so reject them with the
    loader's uniform ``ValueError`` rather than silently honoring them.
    """
    if "primary" not in section:
        msg = f"agents.{contract} needs a 'primary' provider"
        raise ValueError(msg)
    specs: list[AgentSpec] = []
    for key in _CHAIN_KEYS:
        raw = section.get(key)
        if raw is None:
            continue
        # Name the full .prgroom.toml path (agents.<contract>.<key>) so a user
        # debugging their config sees the real key, not a bare agents.<key>.
        path = f"agents.{contract}.{key}"
        if not isinstance(raw, dict):
            msg = f"{path} must be a table, got {raw!r}"
            raise ValueError(msg)  # noqa: TRY004  # config-domain validation; ValueError is the loader's uniform type
        specs.append(_spec_from_toml(raw, path=path))
    return specs


def load_chain(
    contract: ContractName,
    *,
    repo_config: Path | None,
    model_override: str | None,
) -> ProviderChain:
    """Resolve the provider chain for ``contract`` (TOML section, else default).

    Reads ``[agents.<contract>]`` from the per-repo ``.prgroom.toml`` via the
    foundation loader; a truly **absent** section (or file) yields the shipped
    default chain, while a **present** section — even an empty one — must define
    ``primary`` (else it is rejected). ``model_override`` (``--cluster-model`` /
    ``--fix-model``) swaps the **primary** provider's model only, leaving its cli
    and the rest of the chain intact — "same provider, this model".
    """
    table = _read_toml(repo_config)
    agents = _subtable(table, "agents")
    # Distinguish key-PRESENT from value-EMPTY by membership, not truthiness: an
    # empty-but-present [agents.<contract>] table is still a present section, so it
    # must route through _chain_from_toml (where the missing-primary check fires).
    # Only a truly ABSENT key falls through to the shipped default chain.
    if contract in agents:
        section = agents[contract]
        if not isinstance(section, dict):
            # Name the full agents.<contract> path (not _subtable's bare key) so the
            # error matches the per-provider agents.<contract>.<key> errors below.
            msg = f"agents.{contract} must be a table, got {section!r}"
            raise ValueError(msg)
        specs = _chain_from_toml(contract, section)
    else:
        specs = list(_DEFAULT_CHAINS[contract])
    if model_override is not None and specs:
        head = specs[0]
        specs[0] = AgentSpec(cli=head.cli, model=model_override, extra=dict(head.extra))
    return ProviderChain(providers=specs, time_budget_s=_DEFAULT_BUDGETS[contract])


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class _LinkFailure:
    """One chain link's failure, recorded for the both-fail escalation detail.

    ``reason`` is normalized to a single line at construction: every source (an
    agent stderr, a timeout ``detail``, a parse exception message) may contain
    interior newlines, but the escalation ``detail`` is documented as a one-line
    summary — so collapse all whitespace once, centrally, here. ``kind`` is the
    usage-telemetry outcome tag for the failed attempt (``timeout`` /
    ``unavailable`` / ``error`` / ``malformed``).
    """

    spec: AgentSpec
    reason: str
    kind: str

    def __post_init__(self) -> None:
        # Collapse all whitespace (one-line guarantee), then cap so a huge agent
        # stderr cannot bloat the escalation detail. The cap keeps head AND tail:
        # the informative line of a traceback is the LAST one, so head-only
        # truncation would keep boilerplate and drop the cause.
        collapsed = " ".join(self.reason.split())
        if len(collapsed) > _REASON_MAX_CHARS:
            tail_chars = _REASON_MAX_CHARS - _REASON_HEAD_CHARS - len(_REASON_ELLIPSIS)
            collapsed = collapsed[:_REASON_HEAD_CHARS] + _REASON_ELLIPSIS + collapsed[-tail_chars:]
        object.__setattr__(self, "reason", collapsed)


class _Dispatcher:
    """Shared fallback-ladder engine. Subclasses bind the contract name + output parser.

    The ladder is generic over the contract output type ``T``: :meth:`_run_chain`
    runs each provider in order, parses the first 0-exit-and-well-formed stdout via
    the subclass ``parse`` callable, and falls through every other outcome. The only
    per-contract difference is the parser, so the loop lives here once.
    """

    _contract: ContractName

    def __init__(
        self,
        *,
        runner: AgentRunner,
        chain: ProviderChain,
        prompt: PromptTemplate | None = None,
        cancel: threading.Event | None = None,
        usage_hook: Callable[[UsageRecord], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], str] = _utc_now_iso,
    ) -> None:
        self._runner = runner
        self._chain = chain
        # The prompt template is loaded once (§5 "loaded once at startup"); a caller
        # may inject one to avoid disk I/O in a tight test.
        self._prompt = prompt if prompt is not None else load_prompt(self._contract)
        # The cancel token is forwarded to EVERY runner invocation, so the lifecycle
        # (or the run verb's SIGTERM handler) can abort an in-flight dispatch — the
        # contract surfaces (cluster()/fix()) carry no parameter for it.
        self._cancel = cancel
        # §5 usage logging: one UsageRecord per ATTEMPT (failed links included) is
        # pushed through this hook — the lifecycle wires it to usage.append_usage.
        # Token counts stay None until a usage-line parser exists. `clock` (monotonic,
        # durations) and `now` (wall, the ts field) are injectable so tests never sleep.
        self._usage_hook = usage_hook
        self._clock = clock
        self._now = now

    def _run_chain(self, payload: dict[str, Any], parse: Callable[[str], T]) -> T:
        """Try each provider; return the first parseable output, else raise both-fail.

        Per-link failures — binary absent, non-zero exit (quota/auth/network),
        budget timeout, or 0-exit-but-unparseable output — fall through to the next
        link. An exhausted chain raises :class:`AllProvidersFailedError` naming every
        link's rejection (§5 both-fail → failed disposition + escalation).
        """
        failures: list[_LinkFailure] = []
        for spec in self._chain.providers:
            started = self._clock()
            try:
                outcome = self._try_one(spec, payload)
            except AgentCancelledError:
                # The abort-everything path still leaves a telemetry trace of the
                # attempt before propagating past the ladder.
                self._emit_usage(spec, payload, started=started, outcome="cancelled")
                raise
            if isinstance(outcome, _LinkFailure):
                self._emit_usage(spec, payload, started=started, outcome=outcome.kind)
                failures.append(outcome)
                continue
            try:
                parsed = parse(outcome)
            except (KeyError, TypeError, ValueError) as exc:
                # ValueError subsumes json.JSONDecodeError AND an out-of-enum
                # DispositionKind (StrEnum raises ValueError): a model emitting bogus
                # JSON or a bogus disposition is THIS provider's malformed output —
                # fall through to the next link, never crash the whole dispatch.
                self._emit_usage(spec, payload, started=started, outcome="malformed")
                failures.append(_LinkFailure(spec, f"malformed output: {exc}", kind="malformed"))
                continue
            self._emit_usage(spec, payload, started=started, outcome="success")
            return parsed
        raise AllProvidersFailedError(detail=_render_failures(self._contract, failures))

    def _emit_usage(
        self, spec: AgentSpec, payload: dict[str, Any], *, started: float, outcome: str
    ) -> None:
        """Push one per-attempt :class:`UsageRecord` through the hook, if wired."""
        if self._usage_hook is None:
            return
        self._usage_hook(
            UsageRecord(
                ts=self._now(),
                pr=PRRef.from_dict(payload["pr"]),
                contract=self._contract,
                provider=spec.cli,
                model=spec.model,
                input_tokens=None,
                output_tokens=None,
                duration_ms=int((self._clock() - started) * 1000),
                outcome=outcome,
            )
        )

    def _try_one(self, spec: AgentSpec, payload: dict[str, Any]) -> str | _LinkFailure:
        """Run one provider; return its stdout on a 0-exit, else a :class:`_LinkFailure`."""
        try:
            result = self._runner.run(
                spec,
                prompt_template=self._prompt,
                render_data={"contract_version": str(payload.get("contract_version", 1))},
                contract_payload=payload,
                # Per-link: the provider's own `timeout` override, else the
                # contract default (see ProviderChain — budget x chain length
                # is the worst-case dispatch wall-clock).
                time_budget_s=(
                    spec.time_budget_s
                    if spec.time_budget_s is not None
                    else self._chain.time_budget_s
                ),
                cancel=self._cancel,
            )
        except AgentTimeoutError as exc:
            return _LinkFailure(spec, f"timeout: {exc.detail or exc.code.value}", kind="timeout")
        except FileNotFoundError:
            return _LinkFailure(spec, "binary not on PATH", kind="unavailable")
        except OSError as exc:
            # Present-but-unspawnable (non-executable binary, exec-format error) is
            # the same provider-unavailable trigger as a missing one — fall through.
            return _LinkFailure(spec, f"spawn failed: {exc}", kind="unavailable")
        if result.returncode != 0:
            # _LinkFailure normalizes whitespace + caps length centrally.
            return _LinkFailure(spec, f"exit {result.returncode}: {result.stderr}", kind="error")
        return result.stdout


def _loads_lenient(stdout: str) -> Any:
    """Parse agent stdout as JSON, tolerating banner noise around the object.

    Strict parse first (the §5 contract: pure JSON on stdout). On failure, scan the
    text for complete top-level JSON objects and return the LAST one — real CLIs
    decorate stdout with progress lines and timing banners, and exhausting a whole
    chain over decoration is worse than reading the object out of it. No parseable
    object at all raises :class:`ValueError`, so the attempt becomes this link's
    malformed-output failure and falls through.
    """
    try:
        return json.loads(stdout)
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    found = False
    last: Any = None
    idx = stdout.find("{")
    while idx != -1:
        try:
            obj, end = decoder.raw_decode(stdout, idx)
        except ValueError:
            idx = stdout.find("{", idx + 1)
            continue
        found = True
        last = obj
        idx = stdout.find("{", end)
    if not found:
        msg = "no JSON object in agent stdout"
        raise ValueError(msg)
    return last


class ClusterDispatcher(_Dispatcher):
    """Concrete ``ClusterContract``: dispatch the cluster chain, parse the output."""

    _contract: ContractName = "cluster"

    def cluster(self, request: ClusterInput) -> ClusterOutput:
        return self._run_chain(
            request.to_dict(), lambda s: ClusterOutput.from_dict(_loads_lenient(s))
        )


class FixDispatcher(_Dispatcher):
    """Concrete ``FixContract``: dispatch the fix chain, parse the output."""

    _contract: ContractName = "fix"

    def fix(self, request: FixInput) -> FixOutput:
        return self._run_chain(request.to_dict(), lambda s: FixOutput.from_dict(_loads_lenient(s)))


def _render_failures(contract: ContractName, failures: list[_LinkFailure]) -> str:
    """A one-line summary of every link's rejection for the escalation detail."""
    parts = [f"{f.spec.cli}:{f.spec.model} ({f.reason})" for f in failures]
    return f"{contract} chain exhausted: " + "; ".join(parts)
