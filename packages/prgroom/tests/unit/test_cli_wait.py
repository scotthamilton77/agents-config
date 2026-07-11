"""Tests for the wired ``wait`` CLI verb (§4.2).

Wiring tests monkeypatch ``wait_lifecycle`` to assert the command parses the ref and
propagates the exit code. Integration tests drive the real ``wait_lifecycle`` →
``_wait_verb`` for the non-blocking precondition paths (§3.2): ``fixes-pending`` →
``PRECONDITION_WAIT_NOT_APPLICABLE``, a never-polled PR → ``PRECONDITION_NO_STATE``,
``merged`` → no-op. These return before any blocking poll, so no clock is consumed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from typer.testing import CliRunner

from prgroom import cli
from prgroom.prsession.enums import PRPhase
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import PRGroomingState, QuiescenceState

runner = CliRunner()

_REF = PRRef(owner="octo", repo="demo", number=7)
_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _state(phase: PRPhase) -> PRGroomingState:
    return PRGroomingState(
        pr=_REF,
        phase=phase,
        pr_review_retries_used=1,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(),
    )


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(cli, "_build_store", lambda _name: InMemoryStore())
    monkeypatch.setattr(cli, "_build_gh", lambda: object())
    box: dict[str, Any] = {}

    def fake_wait_lifecycle(**kwargs: Any) -> int:
        box.update(kwargs)
        return box.get("_return_code", 0)

    monkeypatch.setattr(cli, "wait_lifecycle", fake_wait_lifecycle)
    return box


def test_wait_parses_ref_and_returns_zero(captured: dict[str, Any]) -> None:
    result = runner.invoke(cli.app, ["wait", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert captured["ref"] == _REF


def test_wait_propagates_nonzero_exit_code(captured: dict[str, Any]) -> None:
    captured["_return_code"] = 2  # e.g. PRECONDITION_WAIT_NOT_APPLICABLE
    result = runner.invoke(cli.app, ["wait", "octo/demo#7"])
    assert result.exit_code == 2


def test_wait_bad_ref_exits_2(captured: dict[str, Any]) -> None:
    result = runner.invoke(cli.app, ["wait", "not a ref"])
    assert result.exit_code == 2
    assert "ref" not in captured  # failed at parse, before wait_lifecycle


# ── real-seam integration: non-blocking precondition paths ──────────────────


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> InMemoryStore:
    store = InMemoryStore()
    monkeypatch.setattr(cli, "_build_store", lambda _name: store)
    monkeypatch.setattr(cli, "_build_gh", lambda: object())  # unused on these paths
    return store


def test_wait_fixes_pending_is_not_applicable(patched: InMemoryStore) -> None:
    patched.write(_REF, _state(PRPhase.FIXES_PENDING))
    result = runner.invoke(cli.app, ["wait", "octo/demo#7"])
    assert result.exit_code == 2  # PRECONDITION_WAIT_NOT_APPLICABLE (EX_USAGE)
    assert "PRECONDITION_WAIT_NOT_APPLICABLE" in result.output


def test_wait_no_state_is_precondition_error(patched: InMemoryStore) -> None:
    assert patched.list_refs() == []  # never polled — no state on disk
    result = runner.invoke(cli.app, ["wait", "octo/demo#7"])
    assert result.exit_code == 2
    assert "PRECONDITION_NO_STATE" in result.output


def test_wait_merged_is_noop(patched: InMemoryStore) -> None:
    patched.write(_REF, _state(PRPhase.MERGED))
    result = runner.invoke(cli.app, ["wait", "octo/demo#7"])
    assert result.exit_code == 0, result.output  # merged is absorbing — nothing to wait on
