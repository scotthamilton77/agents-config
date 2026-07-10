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

import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from prgroom.agent.contracts import ClusterContract, ClusterInput, FixContract, FixInput
from prgroom.agent.dispatcher import (
    AllProvidersFailedError,
    ClusterDispatcher,
    FixDispatcher,
    ProviderChain,
    load_chain,
)
from prgroom.agent.prompt_loader import PromptTemplate
from prgroom.agent.subprocess_runner import (
    AgentCancelledError,
    AgentRunResult,
    AgentSpec,
    AgentTimeoutError,
)
from prgroom.agent.usage import UsageRecord
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


class SpawnOSError(_Outcome):
    """Spawn failed with a non-FileNotFound OSError (present but not executable)."""


class FakeAgentRunner:
    """Replays one queued :class:`_Outcome` per ``run`` call, recording every call.

    The signature mirrors the ``AgentRunner`` Protocol EXACTLY — no ``**kwargs``
    swallowing — so a dispatcher that drops or misnames a forwarded argument fails
    loudly here instead of staying green. ``calls`` records each invocation's
    kwargs so tests pin the dispatcher→runner contract (per-link budget, prompt
    template, render data, cancel token), not just which specs were tried.
    """

    def __init__(self, outcomes: Sequence[_Outcome]) -> None:
        self._outcomes = list(outcomes)
        self.specs_tried: list[AgentSpec] = []
        self.calls: list[dict[str, Any]] = []

    def run(
        self,
        spec: AgentSpec,
        *,
        prompt_template: PromptTemplate,
        render_data: dict[str, str],
        contract_payload: dict[str, Any],
        time_budget_s: float,
        cancel: threading.Event | None = None,
    ) -> AgentRunResult:
        self.specs_tried.append(spec)
        self.calls.append(
            {
                "spec": spec,
                "prompt_template": prompt_template,
                "render_data": render_data,
                "contract_payload": contract_payload,
                "time_budget_s": time_budget_s,
                "cancel": cancel,
            }
        )
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
            # Cancellation is only reachable in production when the dispatcher
            # forwards a SET cancel token — enforce it so this fake cannot pin a
            # code path the real plumbing does not have.
            assert cancel is not None and cancel.is_set(), "cancel token not forwarded"
            raise AgentCancelledError(
                tier=Tier.RUNTIME_CANCELLED, code=ErrorCode.RUNTIME_CANCELLED_SIGTERM, signum=15
            )
        if isinstance(outcome, SpawnOSError):
            raise PermissionError(13, "Permission denied", spec.cli)
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
        ("codex", "gpt-5.6-luna"),
    ]
    assert chain.providers[1].extra.get("effort") == "high"


def test_default_fix_chain_makes_both_links_write_capable() -> None:
    # The fix role edits + commits, so BOTH default providers must be write-capable:
    # claude via `write=True` (-> headless dontAsk + scoped allow-list in the invoker;
    # without it a headless `claude -p` commits nothing) and codex via `write=True`
    # (-> --sandbox workspace-write). The cluster chain's claude link stays read-only.
    chain = load_chain("fix", repo_config=None, model_override=None)
    assert [(p.cli, p.model) for p in chain.providers] == [
        ("claude", "opus[1m]"),
        ("codex", "gpt-5.6-terra"),
    ]
    assert chain.providers[0].extra.get("effort") == "xhigh"
    assert chain.providers[0].extra.get("write") is True
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
    # per-provider errors — not the foundation subtable's bare-key message.
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
        ("codex", "gpt-5.6-luna"),
    ]


def test_provider_timeout_key_overrides_that_links_budget(tmp_path: Path) -> None:
    # The HLD names per-provider TOML config for model + timeout: a provider-level
    # `timeout` (seconds) overrides the contract default for THAT link only; links
    # without one keep the contract default. The key is structural, not `extra`.
    cfg = tmp_path / ".prgroom.toml"
    cfg.write_text(
        "\n".join(
            [
                "[agents.cluster]",
                'primary = { cli = "ollama", model = "gemma4", timeout = 300 }',
                'fallback = { cli = "claude", model = "haiku" }',
            ]
        ),
        encoding="utf-8",
    )
    chain = load_chain("cluster", repo_config=cfg, model_override=None)
    assert chain.providers[0].time_budget_s == 300.0
    assert "timeout" not in chain.providers[0].extra
    assert chain.providers[1].time_budget_s is None  # falls back to the contract budget


def test_dispatcher_honors_a_per_link_timeout_override() -> None:
    # The per-link override must actually reach the runner; the un-overridden link
    # still gets the chain's contract default.
    runner = FakeAgentRunner([TimesOut(), Succeeds(CLUSTER_OK)])
    dispatcher = ClusterDispatcher(
        runner=runner,
        chain=_chain(
            AgentSpec("ollama", "gemma4", time_budget_s=7.0), AgentSpec("claude", "haiku")
        ),
    )
    dispatcher.cluster(_cluster_input())
    assert runner.calls[0]["time_budget_s"] == 7.0  # the link's own override
    assert runner.calls[1]["time_budget_s"] == 5.0  # the chain default


def test_provider_timeout_must_be_a_positive_number(tmp_path: Path) -> None:
    # Invalid timeouts are rejected naming the full agents.<contract>.<key>.timeout
    # path — never silently swallowed into `extra` (the pre-fix behavior).
    for bad in ('"5m"', "-3", "0", "true"):
        cfg = tmp_path / ".prgroom.toml"
        cfg.write_text(
            f'[agents.cluster]\nprimary = {{ cli = "ollama", model = "g", timeout = {bad} }}\n',
            encoding="utf-8",
        )
        with pytest.raises(
            ValueError, match=r"agents\.cluster\.primary\.timeout must be a positive number"
        ):
            load_chain("cluster", repo_config=cfg, model_override=None)


def test_model_override_replaces_the_primary_model_only() -> None:
    # --cluster-model / --fix-model swaps the primary provider's model, keeping its
    # cli + the rest of the chain (operator wants "the same provider, this model").
    chain = load_chain("fix", repo_config=None, model_override="opus")
    assert chain.providers[0].cli == "claude"
    assert chain.providers[0].model == "opus"
    # the fallback link is untouched
    assert chain.providers[1].model == "gpt-5.6-terra"


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
    # aborting the whole dispatch, and the fallback is never touched. The token is
    # REAL plumbing: the dispatcher must forward its own Event to every runner call
    # (the fake refuses to cancel unless it received a set token).
    cancel = threading.Event()
    cancel.set()
    runner = FakeAgentRunner([Cancelled(), Succeeds(CLUSTER_OK)])
    dispatcher = ClusterDispatcher(
        runner=runner,
        chain=_chain(AgentSpec("ollama", "gemma4"), AgentSpec("claude", "haiku")),
        cancel=cancel,
    )
    with pytest.raises(AgentCancelledError) as excinfo:
        dispatcher.cluster(_cluster_input())
    assert excinfo.value.code is ErrorCode.RUNTIME_CANCELLED_SIGTERM
    assert runner.calls[0]["cancel"] is cancel  # the dispatcher's OWN event reached the runner
    assert [s.cli for s in runner.specs_tried] == ["ollama"]  # fallback never tried


def test_dispatcher_forwards_the_runner_contract_kwargs() -> None:
    # The dispatcher→runner seam pinned end to end: the per-link budget, the loaded
    # prompt template, the contract_version render datum, and the cancel token must
    # all reach the runner — a dropped kwarg is a silent regression otherwise.
    cancel = threading.Event()
    prompt = PromptTemplate(name="t", text="x")
    runner = FakeAgentRunner([Succeeds(CLUSTER_OK)])
    dispatcher = ClusterDispatcher(
        runner=runner, chain=_chain(AgentSpec("ollama", "gemma4")), prompt=prompt, cancel=cancel
    )
    dispatcher.cluster(_cluster_input())
    call = runner.calls[0]
    assert call["time_budget_s"] == 5.0  # the chain's per-link budget
    assert call["prompt_template"] is prompt
    assert call["render_data"] == {"contract_version": "1"}
    assert call["cancel"] is cancel


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


def test_spawn_oserror_falls_through_like_binary_missing() -> None:
    # A present-but-non-executable binary (PermissionError, exec-format error) is
    # morally the same provider-unavailable trigger as a missing one — it must fall
    # through to the next link, never crash the whole dispatch.
    runner = FakeAgentRunner([SpawnOSError(), Succeeds(CLUSTER_OK)])
    dispatcher = ClusterDispatcher(
        runner=runner, chain=_chain(AgentSpec("ollama", "gemma4"), AgentSpec("claude", "haiku"))
    )
    dispatcher.cluster(_cluster_input())
    assert [s.cli for s in runner.specs_tried] == ["ollama", "claude"]


def test_spawn_oserror_detail_names_the_failure() -> None:
    runner = FakeAgentRunner([SpawnOSError()])
    dispatcher = ClusterDispatcher(runner=runner, chain=_chain(AgentSpec("ollama", "gemma4")))
    with pytest.raises(AllProvidersFailedError) as excinfo:
        dispatcher.cluster(_cluster_input())
    assert "spawn failed" in excinfo.value.detail
    assert "Permission denied" in excinfo.value.detail


def test_long_failure_reason_keeps_the_informative_tail() -> None:
    # Tracebacks and CLI stderr put the real error LAST — head-only truncation kept
    # pure boilerplate and dropped the cause. The cap must keep head AND tail.
    long_stderr = (
        "Traceback (most recent call last):\n"
        + "\n".join(f'  File "/x/mod{i}.py", line {i}, in step{i}' for i in range(10))
        + "\nRuntimeError: the actual cause"
    )
    runner = FakeAgentRunner([ExitsWith(1, long_stderr)])
    dispatcher = ClusterDispatcher(runner=runner, chain=_chain(AgentSpec("ollama", "gemma4")))
    with pytest.raises(AllProvidersFailedError) as excinfo:
        dispatcher.cluster(_cluster_input())
    detail = excinfo.value.detail
    assert "Traceback" in detail  # the head survives
    assert "RuntimeError: the actual cause" in detail  # the tail survives the cap


# ── lenient stdout parsing: banner noise must not exhaust the chain ──


def test_banner_wrapped_json_still_parses() -> None:
    # Real CLIs decorate stdout (progress lines, timing banners). The contract
    # object inside the noise must parse rather than exhausting the whole chain.
    noisy = "Loading model gemma4...\n" + CLUSTER_OK + "\nDone in 3.2s"
    runner = FakeAgentRunner([Succeeds(noisy)])
    dispatcher = ClusterDispatcher(runner=runner, chain=_chain(AgentSpec("ollama", "gemma4")))
    out = dispatcher.cluster(_cluster_input())
    assert out.clusters == []


def test_stray_brace_in_banner_noise_is_skipped() -> None:
    # A "{" that does not start a valid JSON object (shell prompt art, progress
    # format strings) must be skipped over, not abort the scan.
    noisy = "progress {percent} done " + CLUSTER_OK
    runner = FakeAgentRunner([Succeeds(noisy)])
    dispatcher = ClusterDispatcher(runner=runner, chain=_chain(AgentSpec("ollama", "gemma4")))
    out = dispatcher.cluster(_cluster_input())
    assert out.clusters == []


def test_last_json_object_wins_when_stdout_carries_several() -> None:
    noisy = '{"progress": "warming up"} chatter ' + CLUSTER_OK
    runner = FakeAgentRunner([Succeeds(noisy)])
    dispatcher = ClusterDispatcher(runner=runner, chain=_chain(AgentSpec("ollama", "gemma4")))
    out = dispatcher.cluster(_cluster_input())
    assert out.clusters == []  # the LAST object is the contract output


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
        runner=runner,
        chain=_chain(AgentSpec("claude", "opus[1m]"), AgentSpec("codex", "gpt-5.6-terra")),
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


# ── usage telemetry: one record per attempt escapes the dispatcher ──


def test_usage_hook_emits_one_record_per_attempt_across_the_ladder() -> None:
    # Per-invocation telemetry must escape the dispatcher — one record per attempt,
    # failed links included — or the fallback ladder is invisible to the lifecycle
    # and the §5 usage log can never be correct.
    records: list[UsageRecord] = []
    ticks = iter(range(100))
    runner = FakeAgentRunner([TimesOut(), Succeeds(CLUSTER_OK)])
    dispatcher = ClusterDispatcher(
        runner=runner,
        chain=_chain(AgentSpec("ollama", "gemma4"), AgentSpec("claude", "haiku")),
        usage_hook=records.append,
        clock=lambda: float(next(ticks)),  # 1s per clock pair -> 1000ms durations
        now=lambda: "2026-06-12T00:00:00+00:00",
    )
    dispatcher.cluster(_cluster_input())
    assert [(r.provider, r.outcome) for r in records] == [
        ("ollama", "timeout"),
        ("claude", "success"),
    ]
    first = records[0]
    assert first.contract == "cluster"
    assert first.model == "gemma4"
    assert first.pr == PR  # rebuilt from the contract payload
    assert first.ts == "2026-06-12T00:00:00+00:00"  # injected wall clock
    assert first.duration_ms == 1000  # injected monotonic clock
    assert first.input_tokens is None and first.output_tokens is None  # no parser yet


def test_usage_hook_tags_unavailable_error_and_malformed_attempts() -> None:
    records: list[UsageRecord] = []
    runner = FakeAgentRunner(
        [BinaryMissing(), ExitsWith(1, "quota"), Succeeds("not json"), Succeeds(CLUSTER_OK)]
    )
    dispatcher = ClusterDispatcher(
        runner=runner,
        chain=_chain(
            AgentSpec("ollama", "g"),
            AgentSpec("claude", "h"),
            AgentSpec("codex", "m"),
            AgentSpec("opencode", "o"),
        ),
        usage_hook=records.append,
    )
    dispatcher.cluster(_cluster_input())
    assert [r.outcome for r in records] == ["unavailable", "error", "malformed", "success"]


def test_usage_hook_records_a_cancelled_attempt_before_the_abort() -> None:
    # Even the abort-everything path leaves a telemetry trace of the attempt.
    records: list[UsageRecord] = []
    cancel = threading.Event()
    cancel.set()
    runner = FakeAgentRunner([Cancelled()])
    dispatcher = ClusterDispatcher(
        runner=runner,
        chain=_chain(AgentSpec("ollama", "gemma4")),
        cancel=cancel,
        usage_hook=records.append,
    )
    with pytest.raises(AgentCancelledError):
        dispatcher.cluster(_cluster_input())
    assert [r.outcome for r in records] == ["cancelled"]


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
