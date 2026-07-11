"""Tests for the wired ``run`` CLI verb (§3.3).

Two layers: wiring tests monkeypatch ``run_lifecycle`` to assert the command maps
flags correctly (``--interactive/--autonomous`` → ``Mode``, ``--pr-review-retries`` → config)
and propagates the returned exit code; one integration test drives the real
``run_lifecycle`` + ``Verbs.system`` end-to-end against a fake gh on the simplest
real path (autonomous run where ``_poll`` observes the PR merged → terminal), proving
the cli → run_lifecycle → _run → real ``poll_pr`` → flush chain connects.
"""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from prgroom import cli
from prgroom.lifecycle.run import Mode
from prgroom.prsession.enums import PRPhase
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.pr_ref import PRRef

runner = CliRunner()

_REF = PRRef(owner="octo", repo="demo", number=7)


class _StubDispatcher:
    """Unused under a stubbed run_lifecycle; satisfies the build seam's return shape."""


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub every build seam + capture the kwargs the command hands ``run_lifecycle``."""
    monkeypatch.setattr(cli, "_build_store", lambda _name: InMemoryStore())
    monkeypatch.setattr(cli, "_build_gh", lambda: object())
    monkeypatch.setattr(cli, "_build_git", lambda: object())
    monkeypatch.setattr(cli, "_build_sink", lambda: object())
    monkeypatch.setattr(cli, "_build_cluster_dispatcher", lambda: (_StubDispatcher(), "claude"))
    monkeypatch.setattr(cli, "_build_fix_dispatcher", lambda: (_StubDispatcher(), "claude"))
    box: dict[str, Any] = {}

    def fake_run_lifecycle(**kwargs: Any) -> int:
        box.update(kwargs)
        return box.get("_return_code", 0)

    monkeypatch.setattr(cli, "run_lifecycle", fake_run_lifecycle)
    return box


def test_run_defaults_to_autonomous_mode(captured: dict[str, Any]) -> None:
    result = runner.invoke(cli.app, ["run", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert captured["mode"] is Mode.AUTONOMOUS
    assert captured["ref"] == _REF
    assert captured["config"].pr_review_retries == 5  # built-in default


def test_run_interactive_flag_sets_mode(captured: dict[str, Any]) -> None:
    result = runner.invoke(cli.app, ["run", "octo/demo#7", "--interactive"])
    assert result.exit_code == 0, result.output
    assert captured["mode"] is Mode.INTERACTIVE


def test_run_pr_review_retries_flag_flows_into_config(captured: dict[str, Any]) -> None:
    result = runner.invoke(cli.app, ["run", "octo/demo#7", "--pr-review-retries", "6"])
    assert result.exit_code == 0, result.output
    assert captured["config"].pr_review_retries == 6


def test_run_propagates_nonzero_exit_code(captured: dict[str, Any]) -> None:
    captured["_return_code"] = 77  # run_lifecycle's mapped tier code
    result = runner.invoke(cli.app, ["run", "octo/demo#7"])
    assert result.exit_code == 77


def test_run_bad_ref_exits_2(captured: dict[str, Any]) -> None:
    result = runner.invoke(cli.app, ["run", "not a ref"])
    assert result.exit_code == 2  # PRECONDITION_BAD_PR_REF, rendered before run_lifecycle
    assert "run_lifecycle" not in captured or "mode" not in captured


# ── real-seam integration: autonomous run on a merged PR ────────────────────


class _MergedGh:
    """A fake gh where the PR reads as merged and no items/CI exist (real poll_pr path)."""

    def head_ref_oid(self, ref: PRRef) -> str:
        del ref
        return "abc123"

    def rest(self, method: str, path: str, *, fields: dict[str, str] | None = None) -> Any:
        del method, fields
        if path == "repos/octo/demo/pulls/7":
            return {"merged_at": "2026-06-09T12:00:00Z"}  # merged close
        if path.endswith("/status"):
            return {"state": "success"}
        return []  # issue comments / reviews / review comments — none

    def add_label(self, ref: PRRef, label: str) -> None:  # pragma: no cover - not a gating run
        del ref, label


def test_run_integration_merged_pr_reaches_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryStore()
    monkeypatch.setattr(cli, "_build_store", lambda _name: store)
    monkeypatch.setattr(cli, "_build_gh", lambda: _MergedGh())
    monkeypatch.setattr(cli, "_build_git", lambda: object())  # unused: never reaches push
    monkeypatch.setattr(cli, "_build_cluster_dispatcher", lambda: (_StubDispatcher(), "claude"))
    monkeypatch.setattr(cli, "_build_fix_dispatcher", lambda: (_StubDispatcher(), "claude"))
    # Drives the REAL run_lifecycle -> _run -> poll_pr -> flush via Verbs.system.
    result = runner.invoke(cli.app, ["run", "octo/demo#7", "--autonomous"])
    assert result.exit_code == 0, result.output
    assert store.read(_REF).phase is PRPhase.MERGED  # poll observed the merge close
