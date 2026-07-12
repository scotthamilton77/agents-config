"""Tests for the wired ``poll`` CLI verb (§1, §2, §3.2).

The verb resolves the store + gh adapter, parses the PR ref, then runs
``read → poll_pr → write`` under the lock wrapper and renders any
:class:`PrgroomError` via ``handle_cli_error``. The two outward seams —
``_build_gh`` (the gh adapter) and ``_build_store`` (the Store) — are
monkeypatched here so the verb runs against an InMemoryStore + a recorded-gh
fake (no real subprocess, no real disk). Poll is a **locked** verb, not the
``status`` carve-out.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from prgroom import cli
from prgroom.gh import GhCli
from prgroom.proc import CommandResult
from prgroom.prsession.enums import PRPhase
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.pr_ref import PRRef
from tests.fakes import RecordedRunner

runner = CliRunner()

_REF = PRRef(owner="octo", repo="demo", number=7)


def _ok(payload: object) -> CommandResult:
    return CommandResult(returncode=0, stdout=json.dumps(payload), stderr="")


def _gh_with_head(head: str, *, ci: str = "success") -> GhCli:
    return GhCli(
        RecordedRunner(
            [
                _ok({"headRefOid": head}),
                _ok({"state": "open", "merged_at": None}),
                _ok([]),
                _ok([]),
                _ok([]),
                _ok({"state": ci}),
            ]
        )
    )


def _gh_terminal() -> GhCli:
    # 401 on the head-oid read → RUNTIME_GH_TERMINAL (exit 77).
    return GhCli(
        RecordedRunner(
            [CommandResult(returncode=1, stdout="{}", stderr="gh: Bad credentials (HTTP 401)")]
        )
    )


def _gh_transient() -> GhCli:
    # 503 on the head-oid read → RUNTIME_GH_TRANSIENT (exit 75).
    return GhCli(
        RecordedRunner(
            [CommandResult(returncode=1, stdout="{}", stderr="gh: Service Unavailable (HTTP 503)")]
        )
    )


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> InMemoryStore:
    """Wire the verb to an InMemoryStore; the gh adapter is set per-test."""
    store = InMemoryStore()
    monkeypatch.setattr(cli, "_build_store", lambda _name: store)
    return store


def test_poll_bootstrap_writes_state_and_exits_zero(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh_with_head("abc"))
    result = runner.invoke(cli.app, ["poll", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    written = patched.read(_REF)
    assert written.pr_review_retries_used == 0  # the initial observed push is free
    assert written.last_poll_sha == "abc"
    assert written.phase is PRPhase.AWAITING_REVIEW


@pytest.mark.usefixtures("patched")
def test_poll_malformed_ref_exits_two_with_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh_with_head("abc"))
    result = runner.invoke(cli.app, ["poll", "not-a-ref"])
    assert result.exit_code == 2
    assert "error: PRECONDITION_BAD_PR_REF" in result.output
    assert "how:" in result.output


@pytest.mark.usefixtures("patched")
def test_poll_bare_number_is_bad_ref_pending_repo_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The poll verb parses without a default_repo (current-repo resolution is a
    # later bead), so a bare `<n>` is a bad ref, not a silent success.
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh_with_head("abc"))
    result = runner.invoke(cli.app, ["poll", "123"])
    assert result.exit_code == 2
    assert "PRECONDITION_BAD_PR_REF" in result.output


def test_poll_help_does_not_advertise_bare_number() -> None:
    # Finding: the help must match reality — a bare number is not yet resolvable.
    result = runner.invoke(cli.app, ["poll", "--help"])
    assert result.exit_code == 0
    assert "owner/repo#n" in result.output
    assert "PR number" not in result.output


@pytest.mark.usefixtures("patched")
def test_poll_transient_gh_error_exits_seventyfive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh_transient())
    result = runner.invoke(cli.app, ["poll", "octo/demo#7"])
    assert result.exit_code == 75
    assert "RUNTIME_GH_TRANSIENT" in result.output


@pytest.mark.usefixtures("patched")
def test_poll_terminal_gh_error_exits_seventyseven(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh_terminal())
    result = runner.invoke(cli.app, ["poll", "octo/demo#7"])
    assert result.exit_code == 77
    assert "RUNTIME_GH_TERMINAL" in result.output


def test_poll_acquires_lock_and_exits_seventyfive_on_contention(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh_with_head("abc"))
    # Pre-hold the lock so the verb's acquire fails non-blocking → exit 75.
    assert patched.try_acquire(_REF)
    try:
        result = runner.invoke(cli.app, ["poll", "octo/demo#7"])
    finally:
        patched.release(_REF)
    assert result.exit_code == 75
    assert "PRECONDITION_LOCK_HELD" in result.output
