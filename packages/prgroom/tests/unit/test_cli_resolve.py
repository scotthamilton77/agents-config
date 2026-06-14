"""Tests for the wired ``resolve`` CLI verb (§1, §3.2).

``read -> resolve_pr -> write`` under the lock wrapper. The gh seam is
monkeypatched. Like ``rereview``, ``resolve`` only rests at the graph-terminal
``merged`` phase; in ``quiesced`` / ``human-gated`` it still resolves any
fixed/already_addressed thread idempotently.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from prgroom import cli
from prgroom.gh import GhCli
from prgroom.proc import CommandResult
from prgroom.prsession.enums import DispositionKind, ItemKind, PRPhase
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Disposition,
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewItem,
)
from tests.fakes import RecordedRunner

runner = CliRunner()

_REF = PRRef(owner="octo", repo="demo", number=7)
_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _resolved_ok() -> CommandResult:
    payload = {"data": {"resolveReviewThread": {"thread": {"id": "PRRT_x", "isResolved": True}}}}
    return CommandResult(returncode=0, stdout=json.dumps(payload), stderr="")


def _fixed_item() -> ReviewItem:
    return ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="1", thread_id="PRRT_abc"),
        author="copilot",
        body_excerpt="fix this",
        seen_at=_T0,
        disposition=Disposition(kind=DispositionKind.FIXED, decided_at=_T0, decided_by="x"),
    )


def _state(*, phase: PRPhase = PRPhase.FIXES_PENDING) -> PRGroomingState:
    return PRGroomingState(
        pr=_REF,
        phase=phase,
        round=2,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(),
        items=[_fixed_item()],
    )


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> InMemoryStore:
    store = InMemoryStore()
    monkeypatch.setattr(cli, "_build_store", lambda _name: store)
    return store


def test_resolve_resolves_and_persists(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: GhCli(RecordedRunner([_resolved_ok()])))
    patched.write(_REF, _state())
    result = runner.invoke(cli.app, ["resolve", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert patched.read(_REF).items[0].resolved is True


@pytest.mark.usefixtures("patched")
def test_resolve_no_state_exits_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: GhCli(RecordedRunner([])))
    result = runner.invoke(cli.app, ["resolve", "octo/demo#7"])
    assert result.exit_code == 2
    assert "PRECONDITION_NO_STATE" in result.output


def test_resolve_acts_in_quiesced(patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: GhCli(RecordedRunner([_resolved_ok()])))
    patched.write(_REF, _state(phase=PRPhase.QUIESCED))
    result = runner.invoke(cli.app, ["resolve", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert patched.read(_REF).items[0].resolved is True


def test_resolve_merged_is_noop(patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: GhCli(RecordedRunner([])))
    patched.write(_REF, _state(phase=PRPhase.MERGED))
    result = runner.invoke(cli.app, ["resolve", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert patched.read(_REF).items[0].resolved is False
