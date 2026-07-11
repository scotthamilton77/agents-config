"""Tests for the wired ``rereview`` CLI verb (§1, §3.2).

``read -> rereview_pr -> write`` under the lock wrapper. The gh seam is
monkeypatched. Unlike ``push``, ``rereview`` only rests at the graph-terminal
``merged`` phase; in ``quiesced`` / ``human-gated`` it still re-asks stale required
reviewers idempotently.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from prgroom import cli
from prgroom.gh import GhCli
from prgroom.proc import CommandResult
from prgroom.prsession.enums import PRPhase, ReviewerKind, ReviewerStatus
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import PRGroomingState, QuiescenceState, ReviewerState
from tests.fakes import RecordedRunner

runner = CliRunner()

_REF = PRRef(owner="octo", repo="demo", number=7)
_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _ok() -> CommandResult:
    return CommandResult(returncode=0, stdout="{}", stderr="")


def _stale_reviewer() -> dict[str, ReviewerState]:
    return {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.NOT_REQUESTED,
            required=True,
            last_request_at=_T0,
        )
    }


def _state(*, phase: PRPhase = PRPhase.FIXES_PENDING) -> PRGroomingState:
    return PRGroomingState(
        pr=_REF,
        phase=phase,
        pr_review_retries_used=2,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(),
        reviewers=_stale_reviewer(),
    )


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> InMemoryStore:
    store = InMemoryStore()
    monkeypatch.setattr(cli, "_build_store", lambda _name: store)
    return store


def test_rereview_re_requests_and_persists(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: GhCli(RecordedRunner([_ok(), _ok()])))
    patched.write(_REF, _state())
    result = runner.invoke(cli.app, ["rereview", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert patched.read(_REF).reviewers["copilot"].status is ReviewerStatus.REQUESTED


@pytest.mark.usefixtures("patched")
def test_rereview_no_state_exits_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: GhCli(RecordedRunner([])))
    result = runner.invoke(cli.app, ["rereview", "octo/demo#7"])
    assert result.exit_code == 2
    assert "PRECONDITION_NO_STATE" in result.output


def test_rereview_acts_in_quiesced(patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch) -> None:
    # quiesced is terminal-for-CLI but NOT graph-terminal: rereview still repairs
    # a stale required reviewer there (§3.2 rereview/quiesced).
    monkeypatch.setattr(cli, "_build_gh", lambda: GhCli(RecordedRunner([_ok(), _ok()])))
    patched.write(_REF, _state(phase=PRPhase.QUIESCED))
    result = runner.invoke(cli.app, ["rereview", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert patched.read(_REF).reviewers["copilot"].status is ReviewerStatus.REQUESTED


def test_rereview_merged_is_noop(patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: GhCli(RecordedRunner([])))
    patched.write(_REF, _state(phase=PRPhase.MERGED))
    result = runner.invoke(cli.app, ["rereview", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert patched.read(_REF).reviewers["copilot"].status is ReviewerStatus.NOT_REQUESTED
