"""Tests for the decided-by + soft-warning helpers (§5, §8, §8.15).

``cli._decided_by`` derives the disposition author string from a resolved provider
chain's primary; ``lifecycle.warn.default_warn`` is the shared default soft-warning
stderr sink the verb internals fall back to. Both are small pure-ish helpers; the
production dispatcher-build seams themselves are boundary wiring (monkeypatched in
the verb tests), so these pin the logic the seams delegate to.
"""

from __future__ import annotations

import pytest

from prgroom.agent.dispatcher import ProviderChain
from prgroom.agent.subprocess_runner import AgentSpec
from prgroom.cli import _decided_by
from prgroom.lifecycle.warn import default_warn


def test_decided_by_uses_primary_cli_and_model() -> None:
    chain = ProviderChain(
        providers=[
            AgentSpec(cli="claude", model="opus[1m]"),
            AgentSpec(cli="codex", model="gpt-5.6-terra"),
        ],
        time_budget_s=1.0,
    )
    # The primary (first) provider names the deciding agent: "<cli> <model>".
    assert _decided_by(chain) == "claude opus[1m]"


def test_decided_by_empty_chain_degrades_to_prgroom() -> None:
    # A misconfigured empty chain never yields a blank decided_by.
    assert _decided_by(ProviderChain(providers=[], time_budget_s=1.0)) == "prgroom"


def test_default_warn_writes_a_one_line_prgroom_notice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The shared default soft-warning sink prefixes "prgroom: " and a newline,
    # so an operator can grep soft warnings out of stderr.
    default_warn("a soft warning")
    assert capsys.readouterr().err == "prgroom: a soft warning\n"
