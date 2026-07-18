"""Tests for the wired ``reply`` + ``resolve-escalated`` CLI verbs (§1, §3.2).

``reply`` mirrors ``resolve``: ``read -> reply_pr -> write`` under the lock
wrapper, with the gh seam monkeypatched. ``resolve-escalated`` retypes ``--as``
to a 4-value choice (typer rejects an invalid value at parse, exit 2 before any
lifecycle call) and derives ``decided_by = "human:" + _git_user()`` through the
``_build_git`` seam.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from prgroom import cli
from prgroom.gh import GhCli
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
from tests.fakes import RecordedRunner, RecordingGh

runner = CliRunner()

_REF = PRRef(owner="octo", repo="demo", number=7)
_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


class _FakeGit:
    """Minimal ``GitClient`` stand-in: only ``config_user`` is exercised here."""

    def config_user(self) -> str:
        return "tester"


def _fixed_item() -> ReviewItem:
    return ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="555"),
        author="copilot",
        body_excerpt="tighten the bound",
        seen_at=_T0,
        disposition=Disposition(
            kind=DispositionKind.FIXED, decided_at=_T0, decided_by="agent", commits=["abc1234"]
        ),
    )


def _escalated_item() -> ReviewItem:
    return ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="100", thread_id="PRRT_abc"),
        author="copilot",
        body_excerpt="needs a human call",
        seen_at=_T0,
        disposition=Disposition(kind=DispositionKind.ESCALATED, decided_at=_T0, decided_by="agent"),
    )


def _state(*, phase: PRPhase = PRPhase.HUMAN_GATED) -> PRGroomingState:
    return PRGroomingState(
        pr=_REF,
        phase=phase,
        pr_review_retries_used=2,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(),
        items=[_escalated_item()],
    )


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> InMemoryStore:
    store = InMemoryStore()
    monkeypatch.setattr(cli, "_build_store", lambda _name: store)
    return store


def test_invalid_as_rejected_at_parse_exit_2() -> None:
    # typer renders ``--as`` as a choice over ResolveAsKind; an out-of-set value is
    # rejected at parse (exit 2) before any store/gh/lifecycle wiring runs.
    result = runner.invoke(cli.app, ["resolve-escalated", "octo/demo#7", "100", "--as", "bogus"])
    assert result.exit_code == 2


@pytest.mark.usefixtures("patched")
def test_reply_no_state_exits_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: GhCli(RecordedRunner([])))
    result = runner.invoke(cli.app, ["reply", "octo/demo#7"])
    assert result.exit_code == 2
    assert "PRECONDITION_NO_STATE" in result.output


def test_reply_posts_and_persists_replied(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Happy path: the lock wrapper reads state, runs the real reply_pr (which POSTs),
    # and writes the replied flag back. Proves the CLI wiring, not just the no-state gate.
    gh = RecordingGh()
    monkeypatch.setattr(cli, "_build_gh", lambda: gh)
    state = PRGroomingState(
        pr=_REF,
        phase=PRPhase.FIXES_PENDING,
        pr_review_retries_used=1,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(),
        items=[_fixed_item()],
    )
    patched.write(_REF, state)
    result = runner.invoke(cli.app, ["reply", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert gh.rest_calls == [
        # The pre-flight idempotency scan reads the review-comments surface first.
        ("GET", "repos/octo/demo/pulls/7/comments", {}),
        (
            "POST",
            "repos/octo/demo/pulls/7/comments/555/replies",
            {"body": "Fixed in abc1234.\n\n<!-- prgroom:reply:review_thread:555 -->"},
        ),
    ]
    assert patched.read(_REF).items[0].replied is True


def test_resolve_escalated_flips_disposition(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_build_git", lambda: _FakeGit())
    patched.write(_REF, _state())
    result = runner.invoke(
        cli.app,
        ["resolve-escalated", "octo/demo#7", "100", "--as", "skipped", "--rationale", "not needed"],
    )
    assert result.exit_code == 0, result.output
    disposition = patched.read(_REF).items[0].disposition
    assert disposition is not None
    assert disposition.kind is DispositionKind.SKIPPED
    assert disposition.decided_by == "human:tester"  # "human:" + _git_user() seam


def test_resolve_escalated_fixed_strips_commit_whitespace(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # --commits "abc, def" must yield ["abc", "def"], not ["abc", " def"] — the leading
    # space after the comma would otherwise ride into the SHA.
    monkeypatch.setattr(cli, "_build_git", lambda: _FakeGit())
    patched.write(_REF, _state())
    result = runner.invoke(
        cli.app,
        ["resolve-escalated", "octo/demo#7", "100", "--as", "fixed", "--commits", "abc123, def456"],
    )
    assert result.exit_code == 0, result.output
    disposition = patched.read(_REF).items[0].disposition
    assert disposition is not None
    assert disposition.commits == ["abc123", "def456"]
