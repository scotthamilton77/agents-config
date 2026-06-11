"""Provider-chain dispatch + fallback ladder (§5 agent-CLI config & fallback).

The dispatcher resolves a per-contract provider chain (from TOML, with a
``--cluster-model`` / ``--fix-model`` override), tries the primary, and on a
fallback-triggering failure (binary absent, quota/auth/network exit, or timeout)
falls to the next link. If the whole chain fails it raises a single
caller-mappable error so the lifecycle can file a ``failed`` disposition +
escalate rather than crash.

Tests use a recorded-outcome fake agent runner (one queued outcome per chain
link), never a real subprocess — the runner's own timeout/cancel behavior is
proven in ``test_agent_subprocess_runner``; here we prove the LADDER logic.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from prgroom.agent.contracts import ClusterContract, ClusterInput, FixContract, FixInput
from prgroom.agent.dispatcher import (
    AllProvidersFailedError,
    ClusterDispatcher,
    FixDispatcher,
    ProviderChain,
    load_chain,
)
from prgroom.agent.subprocess_runner import (
    AgentCancelledError,
    AgentRunResult,
    AgentSpec,
    AgentTimeoutError,
)
from prgroom.errors import ErrorCode, PrgroomError, Tier, exit_code_for_tier
from prgroom.prsession.pr_ref import PRRef

# ── recorded-outcome runner fake (one outcome per chain link) ──


class _Outcome:
    """Base sentinel; subclasses encode the chain link's outcome."""


class Succeeds(_Outcome):
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


class ExitsWith(_Outcome):
    """A non-zero process exit (quota/auth/network) — a fallback trigger."""

    def __init__(self, returncode: int, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr


class TimesOut(_Outcome):
    """The runner raised AgentTimeoutError (budget overrun) — a fallback trigger."""


class Cancelled(_Outcome):
    """The runner raised AgentCancelledError (cancel-token) — aborts the whole chain."""


class BinaryMissing(_Outcome):
    """The agent binary was not on PATH (FileNotFoundError) — a fallback trigger."""


class FakeAgentRunner:
    """Replays one queued :class:`_Outcome` per ``run`` call, recording the specs tried."""

    def __init__(self, outcomes: Sequence[_Outcome]) -> None:
        self._outcomes = list(outcomes)
        self.specs_tried: list[AgentSpec] = []

    def run(self, spec: AgentSpec, **_kwargs: object) -> AgentRunResult:
        self.specs_tried.append(spec)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Succeeds):
            return AgentRunResult(returncode=0, stdout=outcome.stdout, stderr="", duration_ms=1)
        if isinstance(outcome, ExitsWith):
            return AgentRunResult(
                returncode=outcome.returncode, stdout="", stderr=outcome.stderr, duration_ms=1
            )
        if isinstance(outcome, TimesOut):
            raise AgentTimeoutError(
                tier=Tier.RUNTIME_TRANSIENT, code=ErrorCode.RUNTIME_AGENT_TIMEOUT
            )
        if isinstance(outcome, Cancelled):
            raise AgentCancelledError(
                tier=Tier.RUNTIME_CANCELLED, code=ErrorCode.RUNTIME_CANCELLED_SIGTERM, signum=15
            )
        raise FileNotFoundError(2, "No such file or directory", spec.cli)


PR = PRRef(owner="octo", repo="demo", number=7)
CLUSTER_OK = '{"clusters": []}'
FIX_OK = '{"contract_version": 1, "items": []}'


def _cluster_input() -> ClusterInput:
    return ClusterInput(pr=PR, items=[], pr_context_path="/ctx")


def _fix_input() -> FixInput:
    return FixInput(
        pr=PR,
        cluster_id="c-1",
        item_gh_ids=[],
        items=[],
        pr_detail_path="/detail",
        branch_state_path="/branch",
        memory_dir="/mem",
        response_outbox_dir="/out",
    )


def _chain(*specs: AgentSpec) -> ProviderChain:
    return ProviderChain(providers=list(specs), time_budget_s=5.0)


# ── chain loading: defaults, TOML, overrides ──


def test_default_cluster_chain_is_ollama_then_claude_haiku_then_codex() -> None:
    chain = load_chain("cluster", repo_config=None, model_override=None)
    assert [(p.cli, p.model) for p in chain.providers] == [
        ("ollama", "gemma4"),
        ("claude", "haiku"),
        ("codex", "gpt-5.4-mini"),
    ]
    assert chain.providers[1].extra.get("effort") == "high"


def test_default_fix_chain_is_opus_then_codex_write() -> None:
    chain = load_chain("fix", repo_config=None, model_override=None)
    assert [(p.cli, p.model) for p in chain.providers] == [
        ("claude", "opus[1m]"),
        ("codex", "gpt-5.5"),
    ]
    assert chain.providers[0].extra.get("effort") == "xhigh"
    assert chain.providers[1].extra.get("write") is True


def test_toml_overrides_the_default_chain(tmp_path: Path) -> None:
    cfg = tmp_path / ".prgroom.toml"
    cfg.write_text(
        "\n".join(
            [
                "[agents.cluster]",
                'primary = { cli = "claude", model = "haiku", effort = "low" }',
                'fallback = { cli = "ollama", model = "tinyllama" }',
            ]
        ),
        encoding="utf-8",
    )
    chain = load_chain("cluster", repo_config=cfg, model_override=None)
    assert [(p.cli, p.model) for p in chain.providers] == [
        ("claude", "haiku"),
        ("ollama", "tinyllama"),
    ]


def test_provider_missing_cli_or_model_names_the_full_path(tmp_path: Path) -> None:
    cfg = tmp_path / ".prgroom.toml"
    cfg.write_text(
        '[agents.cluster]\nprimary = { model = "haiku" }\n',  # no cli
        encoding="utf-8",
    )
    # Names the full agents.<contract>.<key> path so the user sees which entry.
    with pytest.raises(ValueError, match=r"agents\.cluster\.primary needs string cli \+ model"):
        load_chain("cluster", repo_config=cfg, model_override=None)


def test_non_table_provider_names_the_full_contract_key_path(tmp_path: Path) -> None:
    # The error must name the real .prgroom.toml path (agents.<contract>.<key>), not
    # a bare agents.<key>, so a user debugging their config sees the right key.
    cfg = tmp_path / ".prgroom.toml"
    cfg.write_text(
        '[agents.cluster]\nprimary = { cli = "ollama", model = "g" }\nfallback = "claude"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"agents\.cluster\.fallback must be a table"):
        load_chain("cluster", repo_config=cfg, model_override=None)


def test_non_table_section_names_the_full_agents_contract_path(tmp_path: Path) -> None:
    # A present [agents.<contract>] that is not a table at all (e.g. agents.cluster =
    # "...") must name the full agents.<contract> path — consistent with the
    # per-provider errors — not the foundation _subtable's bare-key message.
    cfg = tmp_path / ".prgroom.toml"
    cfg.write_text('[agents]\ncluster = "ollama"\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"agents\.cluster must be a table"):
        load_chain("cluster", repo_config=cfg, model_override=None)


def test_present_section_without_primary_is_a_config_error(tmp_path: Path) -> None:
    # A present [agents.cluster] that omits `primary` must be rejected, not silently
    # accepted with fallback-as-head (or an empty chain that later raises a
    # contentless both-fail). An absent section still falls through to the default.
    cfg = tmp_path / ".prgroom.toml"
    cfg.write_text(
        '[agents.cluster]\nfallback = { cli = "ollama", model = "tinyllama" }\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="needs a 'primary' provider"):
        load_chain("cluster", repo_config=cfg, model_override=None)


def test_present_but_empty_section_is_a_config_error(tmp_path: Path) -> None:
    # A present-but-empty [agents.cluster] is key-present, so it must route through
    # the missing-primary check — NOT fall through to the shipped default. (Truthiness
    # of the returned subtable can't tell empty-present from absent; key membership can.)
    cfg = tmp_path / ".prgroom.toml"
    cfg.write_text("[agents.cluster]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="needs a 'primary' provider"):
        load_chain("cluster", repo_config=cfg, model_override=None)


def test_absent_section_still_falls_through_to_the_default(tmp_path: Path) -> None:
    # A config file with NO [agents.cluster] key (only an unrelated section) must
    # still yield the shipped default chain — only a truly absent section, not an
    # empty one, gets the default.
    cfg = tmp_path / ".prgroom.toml"
    cfg.write_text('[agents.fix]\nprimary = { cli = "claude", model = "opus" }\n', encoding="utf-8")
    chain = load_chain("cluster", repo_config=cfg, model_override=None)
    assert [(p.cli, p.model) for p in chain.providers] == [
        ("ollama", "gemma4"),
        ("claude", "haiku"),
        ("codex", "gpt-5.4-mini"),
    ]


def test_model_override_replaces_the_primary_model_only() -> None:
    # --cluster-model / --fix-model swaps the primary provider's model, keeping its
    # cli + the rest of the chain (operator wants "the same provider, this model").
    chain = load_chain("fix", repo_config=None, model_override="opus")
    assert chain.providers[0].cli == "claude"
    assert chain.providers[0].model == "opus"
    # the fallback link is untouched
    assert chain.providers[1].model == "gpt-5.5"


# ── ladder behavior (table-driven over the acceptance scenarios) ──


def test_primary_success_uses_first_provider_only() -> None:
    runner = FakeAgentRunner([Succeeds(CLUSTER_OK)])
    dispatcher = ClusterDispatcher(
        runner=runner, chain=_chain(AgentSpec("ollama", "gemma4"), AgentSpec("claude", "haiku"))
    )
    out = dispatcher.cluster(_cluster_input())
    assert out.clusters == []
    assert [s.cli for s in runner.specs_tried] == ["ollama"]  # fallback never touched


def test_primary_binary_absent_falls_to_fallback() -> None:
    runner = FakeAgentRunner([BinaryMissing(), Succeeds(CLUSTER_OK)])
    dispatcher = ClusterDispatcher(
        runner=runner, chain=_chain(AgentSpec("ollama", "gemma4"), AgentSpec("claude", "haiku"))
    )
    dispatcher.cluster(_cluster_input())
    assert [s.cli for s in runner.specs_tried] == ["ollama", "claude"]


def test_primary_timeout_falls_to_fallback() -> None:
    runner = FakeAgentRunner([TimesOut(), Succeeds(CLUSTER_OK)])
    dispatcher = ClusterDispatcher(
        runner=runner, chain=_chain(AgentSpec("ollama", "gemma4"), AgentSpec("claude", "haiku"))
    )
    dispatcher.cluster(_cluster_input())
    assert [s.cli for s in runner.specs_tried] == ["ollama", "claude"]


def test_primary_quota_exit_falls_to_fallback() -> None:
    runner = FakeAgentRunner([ExitsWith(1, "quota exceeded"), Succeeds(CLUSTER_OK)])
    dispatcher = ClusterDispatcher(
        runner=runner, chain=_chain(AgentSpec("ollama", "gemma4"), AgentSpec("claude", "haiku"))
    )
    dispatcher.cluster(_cluster_input())
    assert [s.cli for s in runner.specs_tried] == ["ollama", "claude"]


def test_cancel_token_aborts_the_chain_without_trying_the_fallback() -> None:
    # A cancel-token kill is operator/scheduler shutdown — it must NOT be treated as
    # a per-provider failure and fall through to the next link. It propagates out,
    # aborting the whole dispatch, and the fallback is never touched.
    runner = FakeAgentRunner([Cancelled(), Succeeds(CLUSTER_OK)])
    dispatcher = ClusterDispatcher(
        runner=runner, chain=_chain(AgentSpec("ollama", "gemma4"), AgentSpec("claude", "haiku"))
    )
    with pytest.raises(AgentCancelledError) as excinfo:
        dispatcher.cluster(_cluster_input())
    assert excinfo.value.code is ErrorCode.RUNTIME_CANCELLED_SIGTERM
    assert [s.cli for s in runner.specs_tried] == ["ollama"]  # fallback never tried


def test_all_providers_fail_raises_caller_mappable_error() -> None:
    runner = FakeAgentRunner([BinaryMissing(), TimesOut()])
    dispatcher = ClusterDispatcher(
        runner=runner, chain=_chain(AgentSpec("ollama", "gemma4"), AgentSpec("claude", "haiku"))
    )
    with pytest.raises(AllProvidersFailedError) as excinfo:
        dispatcher.cluster(_cluster_input())
    # caller-mappable: an AGENT_UNAVAILABLE PrgroomError the lifecycle turns into a
    # failed disposition + escalation (not a crash, not a bare exception).
    assert isinstance(excinfo.value, PrgroomError)
    assert excinfo.value.code is ErrorCode.RUNTIME_AGENT_UNAVAILABLE


def test_all_providers_fail_is_transient_exit_75() -> None:
    # §3.7 registry pins RUNTIME_AGENT_UNAVAILABLE to RUNTIME_TRANSIENT (exit 75):
    # the scheduler retries on the next cadence, preserving restart-safety for the
    # un-dispositioned items. A terminal tier (77) would human-gate and break that.
    runner = FakeAgentRunner([BinaryMissing(), TimesOut()])
    dispatcher = ClusterDispatcher(
        runner=runner, chain=_chain(AgentSpec("ollama", "gemma4"), AgentSpec("claude", "haiku"))
    )
    with pytest.raises(AllProvidersFailedError) as excinfo:
        dispatcher.cluster(_cluster_input())
    assert excinfo.value.tier is Tier.RUNTIME_TRANSIENT
    assert exit_code_for_tier(excinfo.value) == 75


def test_all_providers_fail_detail_names_each_link_and_its_reason() -> None:
    # _render_failures + the _LinkFailure reasons exist to build the operator-facing
    # escalation payload — so the detail must name BOTH providers AND both reasons.
    runner = FakeAgentRunner([BinaryMissing(), ExitsWith(7, "quota exceeded")])
    dispatcher = ClusterDispatcher(
        runner=runner, chain=_chain(AgentSpec("ollama", "gemma4"), AgentSpec("claude", "haiku"))
    )
    with pytest.raises(AllProvidersFailedError) as excinfo:
        dispatcher.cluster(_cluster_input())
    detail = excinfo.value.detail
    assert "ollama" in detail and "gemma4" in detail
    assert "claude" in detail and "haiku" in detail
    assert "binary not on PATH" in detail
    assert "exit 7" in detail and "quota exceeded" in detail


def test_multiline_stderr_collapses_to_a_single_line_detail() -> None:
    # The detail is documented as a one-line summary; a multi-line agent stderr
    # (traceback, multi-line quota notice) must not smuggle interior newlines into
    # it. .strip() alone would leave them — the reason must collapse all whitespace.
    multiline = "Traceback (most recent call last):\n  File x\nRuntimeError: boom"
    runner = FakeAgentRunner([ExitsWith(1, multiline)])
    dispatcher = ClusterDispatcher(runner=runner, chain=_chain(AgentSpec("ollama", "gemma4")))
    with pytest.raises(AllProvidersFailedError) as excinfo:
        dispatcher.cluster(_cluster_input())
    detail = excinfo.value.detail
    assert "\n" not in detail
    assert "Traceback" in detail and "RuntimeError: boom" in detail  # content preserved


def test_fix_dispatcher_parses_fix_output() -> None:
    runner = FakeAgentRunner([Succeeds(FIX_OK)])
    dispatcher = FixDispatcher(runner=runner, chain=_chain(AgentSpec("claude", "opus[1m]")))
    out = dispatcher.fix(_fix_input())
    assert out.items == []


def test_fix_out_of_enum_disposition_falls_through_not_crashes() -> None:
    # A 0-exit provider emitting valid JSON whose `disposition` is out-of-enum makes
    # FixOutput.from_dict -> DispositionKind(...) raise ValueError. That must be a
    # per-link failure (fall through to the next provider), not an escaped crash.
    bad = '{"contract_version": 1, "items": [{"gh_id": "a", "disposition": "garbage"}]}'
    runner = FakeAgentRunner([Succeeds(bad), Succeeds(FIX_OK)])
    dispatcher = FixDispatcher(
        runner=runner, chain=_chain(AgentSpec("claude", "opus[1m]"), AgentSpec("codex", "gpt-5.5"))
    )
    out = dispatcher.fix(_fix_input())
    assert out.items == []  # the second provider's good output was parsed
    assert [s.cli for s in runner.specs_tried] == ["claude", "codex"]  # fell through


def test_malformed_agent_json_falls_through_to_the_next_provider() -> None:
    # A provider that exits 0 but emits unparseable JSON is a failure of THAT
    # provider — fall through, do not abort the whole dispatch.
    runner = FakeAgentRunner([Succeeds("not json at all"), Succeeds(CLUSTER_OK)])
    dispatcher = ClusterDispatcher(
        runner=runner, chain=_chain(AgentSpec("ollama", "gemma4"), AgentSpec("claude", "haiku"))
    )
    dispatcher.cluster(_cluster_input())
    assert [s.cli for s in runner.specs_tried] == ["ollama", "claude"]


# ── structural fit: the concrete dispatchers satisfy the foundation Protocols ──


def test_cluster_dispatcher_satisfies_cluster_contract() -> None:
    runner = FakeAgentRunner([Succeeds(CLUSTER_OK)])
    dispatcher: ClusterContract = ClusterDispatcher(
        runner=runner, chain=_chain(AgentSpec("ollama", "gemma4"))
    )
    assert isinstance(dispatcher, ClusterContract)


def test_fix_dispatcher_satisfies_fix_contract() -> None:
    runner = FakeAgentRunner([Succeeds(FIX_OK)])
    chain = _chain(AgentSpec("claude", "opus[1m]"))
    dispatcher: FixContract = FixDispatcher(runner=runner, chain=chain)
    assert isinstance(dispatcher, FixContract)
