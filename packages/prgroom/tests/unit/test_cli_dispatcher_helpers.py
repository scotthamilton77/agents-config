"""Tests for the CLI dispatcher-build seams + logging helpers (§4, §5).

The production dispatcher builders wire ``usage_hook=append_usage`` — the
bead-item-1 regression guard here drives a dispatch through the REAL
``_build_fix_dispatcher()`` construction line (fake runner, real hook, tmp XDG
state dir) and asserts rows land in ``usage.jsonl``. ``_resolve_log_level`` pins
the fail-lateral env-knob choice; ``lifecycle.warn.default_warn`` is the shared
default soft-warning stderr sink.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

import pytest

import prgroom.cli as cli
from prgroom.agent.prompt_loader import PromptTemplate
from prgroom.agent.subprocess_runner import AgentRunResult, AgentSpec
from prgroom.lifecycle.warn import default_warn


def test_default_warn_writes_a_one_line_prgroom_notice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The shared default soft-warning sink prefixes "prgroom: " and a newline,
    # so an operator can grep soft warnings out of stderr.
    default_warn("a soft warning")
    assert capsys.readouterr().err == "prgroom: a soft warning\n"


class _ScriptedRunner:
    """Stands in for ``SubprocessAgentRunner`` at the production build seam.

    Constructed with no args (mirroring the builder's call), it replays a
    fail-then-succeed script so the dispatch exercises the fallback ladder.
    """

    def __init__(self) -> None:
        self._outcomes = [
            AgentRunResult(returncode=1, stdout="", stderr="quota", duration_ms=1),
            AgentRunResult(
                returncode=0,
                stdout='{"contract_version": 1, "items": []}',
                stderr="",
                duration_ms=1,
            ),
        ]

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
        del spec, prompt_template, render_data, contract_payload, time_budget_s, cancel
        return self._outcomes.pop(0)


def test_production_fix_builder_appends_usage_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The bead-item-1 regression guard: this drives the EXACT construction line
    # that used to omit usage_hook. One row per chain-link attempt must land in
    # usage.jsonl — failures included.
    from prgroom.agent.contracts import FixInput
    from prgroom.prsession.pr_ref import PRRef

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(cli, "SubprocessAgentRunner", _ScriptedRunner)
    dispatcher = cli._build_fix_dispatcher()
    dispatched = dispatcher.fix(
        FixInput(
            pr=PRRef(owner="octo", repo="demo", number=7),
            cluster_id="c-1",
            item_gh_ids=[],
            items=[],
            pr_detail_path="/d",
            branch_state_path="/b",
            memory_dir="/m",
            response_outbox_dir="/o",
        )
    )
    assert dispatched.rung == 1  # the scripted fallback actually happened
    lines = (tmp_path / "prgroom" / "usage.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert [r["outcome"] for r in rows] == ["error", "success"]
    assert all(r["contract"] == "fix" for r in rows)


def test_resolve_log_level_default_and_named_levels() -> None:
    assert cli._resolve_log_level(None) == (logging.WARNING, None)
    assert cli._resolve_log_level("") == (logging.WARNING, None)
    assert cli._resolve_log_level("info") == (logging.INFO, None)
    assert cli._resolve_log_level("DEBUG") == (logging.DEBUG, None)


def test_resolve_log_level_garbage_degrades_loudly() -> None:
    # Fail-lateral by design: a typo'd env var must never take down an
    # autonomous overnight run — it degrades to WARNING with a notice.
    level, notice = cli._resolve_log_level("verbose")
    assert level == logging.WARNING
    assert notice is not None and "verbose" in notice
