"""Tests for the wired ``push`` CLI verb (§1, §3.2).

The verb resolves the store + gh/git adapters, parses the ref, then runs
``read -> push_pr -> write`` under the lock wrapper. The outward seams
(``_build_store`` / ``_build_gh`` / ``_build_git``) are monkeypatched. Preconditions:
no state -> NO_STATE (exit 2); a terminal-for-CLI phase -> no-op exit 0.
"""

from __future__ import annotations

from datetime import UTC, datetime

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


class FakeGh:
    def head_ref_oid(self, ref: PRRef) -> str:
        del ref
        return "remotesha"

    def head_ref_name(self, ref: PRRef) -> str:
        del ref
        return "feature-x"


class FakeGit:
    def __init__(self, queued: list[str], *, branch: str = "feature-x") -> None:
        self._queued = queued
        self._branch = branch
        self.pushes: list[tuple[str, str]] = []

    def current_branch(self) -> str:
        return self._branch

    def head_sha(self) -> str:
        return "newhead"

    def rev_list(self, range_: str) -> list[str]:
        del range_
        return list(self._queued)

    def push(self, remote: str, branch: str) -> None:
        self.pushes.append((remote, branch))


def _state(*, phase: PRPhase = PRPhase.FIXES_PENDING, round_: int = 1) -> PRGroomingState:
    return PRGroomingState(
        pr=_REF,
        phase=phase,
        round=round_,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(),
    )


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> InMemoryStore:
    store = InMemoryStore()
    monkeypatch.setattr(cli, "_build_store", lambda _name: store)
    monkeypatch.setattr(cli, "_build_gh", lambda: FakeGh())
    return store


def test_push_uploads_and_persists_bumped_round(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    git = FakeGit(queued=["c1"])
    monkeypatch.setattr(cli, "_build_git", lambda: git)
    patched.write(_REF, _state(round_=1))
    result = runner.invoke(cli.app, ["push", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert git.pushes == [("origin", "HEAD:feature-x")]
    written = patched.read(_REF)
    assert written.round == 2
    assert written.last_pushed_head_sha == "newhead"


@pytest.mark.usefixtures("patched")
def test_push_no_state_exits_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_build_git", lambda: FakeGit(queued=[]))
    result = runner.invoke(cli.app, ["push", "octo/demo#7"])
    assert result.exit_code == 2
    assert "PRECONDITION_NO_STATE" in result.output


def test_push_terminal_phase_is_noop(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # push rests in every terminal-for-CLI phase (quiesced included) — no new
    # commits go up once the PR has stopped soliciting review.
    git = FakeGit(queued=["c1"])
    monkeypatch.setattr(cli, "_build_git", lambda: git)
    patched.write(_REF, _state(phase=PRPhase.QUIESCED, round_=2))
    result = runner.invoke(cli.app, ["push", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert git.pushes == []
    assert patched.read(_REF).round == 2


def test_push_malformed_ref_exits_two() -> None:
    result = runner.invoke(cli.app, ["push", "not-a-ref"])
    assert result.exit_code == 2
    assert "PRECONDITION_BAD_PR_REF" in result.output
