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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
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
    AgentRunner,
    AgentSpec,
    AgentTimeoutError,
)
from prgroom.config import _read_toml, _subtable
from prgroom.errors import ErrorCode, PrgroomError, Tier

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
_STRUCTURAL_KEYS = frozenset({"cli", "model"})


@dataclass(frozen=True, slots=True)
class ProviderChain:
    """An ordered provider chain plus the shared per-contract time budget."""

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


def _spec_from_toml(raw: Mapping[str, Any]) -> AgentSpec:
    """Build an :class:`AgentSpec` from one TOML provider table.

    ``cli`` + ``model`` are required structural fields; every other key (``effort``,
    ``write``, …) flows into ``extra`` so the per-invoker shapes can read them
    without this loader knowing each CLI's options.
    """
    cli = raw.get("cli")
    model = raw.get("model")
    if not isinstance(cli, str) or not isinstance(model, str):
        msg = f"agent provider needs string cli + model, got {raw!r}"
        raise ValueError(msg)  # noqa: TRY004  # config-domain validation; ValueError is the loader's uniform type
    extra = {k: v for k, v in raw.items() if k not in _STRUCTURAL_KEYS}
    return AgentSpec(cli=cli, model=model, extra=extra)


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
        if not isinstance(raw, dict):
            msg = f"agents.{key} must be a table, got {raw!r}"
            raise ValueError(msg)  # noqa: TRY004  # config-domain validation; ValueError is the loader's uniform type
        specs.append(_spec_from_toml(raw))
    return specs


def load_chain(
    contract: ContractName,
    *,
    repo_config: Path | None,
    model_override: str | None,
) -> ProviderChain:
    """Resolve the provider chain for ``contract`` (TOML section, else default).

    Reads ``[agents.<contract>]`` from the per-repo ``.prgroom.toml`` via the
    foundation loader; an absent section (or file) yields the shipped default
    chain. ``model_override`` (``--cluster-model`` / ``--fix-model``) swaps the
    **primary** provider's model only, leaving its cli and the rest of the chain
    intact — "same provider, this model".
    """
    table = _read_toml(repo_config)
    agents = _subtable(table, "agents")
    section = _subtable(agents, contract)
    specs = _chain_from_toml(contract, section) if section else list(_DEFAULT_CHAINS[contract])
    if model_override is not None and specs:
        head = specs[0]
        specs[0] = AgentSpec(cli=head.cli, model=model_override, extra=dict(head.extra))
    return ProviderChain(providers=specs, time_budget_s=_DEFAULT_BUDGETS[contract])


@dataclass(frozen=True, slots=True)
class _LinkFailure:
    """One chain link's failure, recorded for the both-fail escalation detail."""

    spec: AgentSpec
    reason: str


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
    ) -> None:
        self._runner = runner
        self._chain = chain
        # The prompt template is loaded once (§5 "loaded once at startup"); a caller
        # may inject one to avoid disk I/O in a tight test.
        self._prompt = prompt if prompt is not None else load_prompt(self._contract)

    def _run_chain(self, payload: dict[str, Any], parse: Callable[[str], T]) -> T:
        """Try each provider; return the first parseable output, else raise both-fail.

        Per-link failures — binary absent, non-zero exit (quota/auth/network),
        budget timeout, or 0-exit-but-unparseable output — fall through to the next
        link. An exhausted chain raises :class:`AllProvidersFailedError` naming every
        link's rejection (§5 both-fail → failed disposition + escalation).
        """
        failures: list[_LinkFailure] = []
        for spec in self._chain.providers:
            outcome = self._try_one(spec, payload)
            if isinstance(outcome, _LinkFailure):
                failures.append(outcome)
                continue
            try:
                return parse(outcome)
            except (KeyError, TypeError, ValueError) as exc:
                # ValueError subsumes json.JSONDecodeError AND an out-of-enum
                # DispositionKind (StrEnum raises ValueError): a model emitting bogus
                # JSON or a bogus disposition is THIS provider's malformed output —
                # fall through to the next link, never crash the whole dispatch.
                failures.append(_LinkFailure(spec, f"malformed output: {exc}"))
        raise AllProvidersFailedError(detail=_render_failures(self._contract, failures))

    def _try_one(self, spec: AgentSpec, payload: dict[str, Any]) -> str | _LinkFailure:
        """Run one provider; return its stdout on a 0-exit, else a :class:`_LinkFailure`."""
        try:
            result = self._runner.run(
                spec,
                prompt_template=self._prompt,
                render_data={"contract_version": str(payload.get("contract_version", 1))},
                contract_payload=payload,
                time_budget_s=self._chain.time_budget_s,
            )
        except AgentTimeoutError as exc:
            return _LinkFailure(spec, f"timeout: {exc.detail or exc.code.value}")
        except FileNotFoundError:
            return _LinkFailure(spec, "binary not on PATH")
        if result.returncode != 0:
            reason = f"exit {result.returncode}: {result.stderr.strip()[:120]}"
            return _LinkFailure(spec, reason)
        return result.stdout


class ClusterDispatcher(_Dispatcher):
    """Concrete ``ClusterContract``: dispatch the cluster chain, parse the output."""

    _contract: ContractName = "cluster"

    def cluster(self, request: ClusterInput) -> ClusterOutput:
        return self._run_chain(request.to_dict(), lambda s: ClusterOutput.from_dict(json.loads(s)))


class FixDispatcher(_Dispatcher):
    """Concrete ``FixContract``: dispatch the fix chain, parse the output."""

    _contract: ContractName = "fix"

    def fix(self, request: FixInput) -> FixOutput:
        return self._run_chain(request.to_dict(), lambda s: FixOutput.from_dict(json.loads(s)))


def _render_failures(contract: ContractName, failures: list[_LinkFailure]) -> str:
    """A one-line summary of every link's rejection for the escalation detail."""
    parts = [f"{f.spec.cli}:{f.spec.model} ({f.reason})" for f in failures]
    return f"{contract} chain exhausted: " + "; ".join(parts)
