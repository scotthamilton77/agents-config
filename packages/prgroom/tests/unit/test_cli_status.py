"""Tests for the wired ``status`` CLI verb (§3.3 carve-out, §4.6 envelope).

``status`` is the lock-free carve-out: the default path runs a single ``store.read``
without acquiring the lock, then enriches with a live gh fetch (labels + reviews) and
renders the §4.6 envelope. ``--locked`` wraps the read in ``with_lock`` and exits 75
under contention. The two seams (``_build_store`` / ``_build_gh``) are monkeypatched
to an InMemoryStore + a recorded-gh fake, mirroring ``test_cli_poll``.
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
from prgroom.prsession.state import PRGroomingState, QuiescenceState, bootstrap_state
from tests.conftest import FIXED_NOW
from tests.fakes import RecordedRunner

runner = CliRunner()
_REF = PRRef(owner="octo", repo="demo", number=7)


def _ok(payload: object) -> CommandResult:
    return CommandResult(returncode=0, stdout=json.dumps(payload), stderr="")


def _gh(labels: object = None, reviews: object = None) -> GhCli:
    # status' gh enrichment is exactly two REST GETs: labels then reviews.
    return GhCli(RecordedRunner([_ok(labels or []), _ok(reviews or [])]))


def _quiesced_state() -> PRGroomingState:
    state = bootstrap_state(_REF, now=FIXED_NOW)
    state.phase = PRPhase.QUIESCED
    state.quiescence = QuiescenceState(ci_state="success", quiesced_at=FIXED_NOW)
    return state


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> InMemoryStore:
    store = InMemoryStore()
    monkeypatch.setattr(cli, "_build_store", lambda _name: store)
    return store


def test_status_json_all_green_eligible(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    patched.write(_REF, _quiesced_state())
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh())
    result = runner.invoke(cli.app, ["status", "octo/demo#7", "--json"])
    assert result.exit_code == 0, result.output
    env = json.loads(result.output)
    assert env["pr"] == 7
    assert env["phase"] == "quiesced"
    assert env["auto_merge_eligible"] is True


def test_status_default_render(patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch) -> None:
    patched.write(_REF, _quiesced_state())
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh())
    result = runner.invoke(cli.app, ["status", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert "auto_merge_eligible" in result.output
    assert "PR #7" in result.output


@pytest.mark.usefixtures("patched")
def test_status_missing_state_is_precondition(monkeypatch: pytest.MonkeyPatch) -> None:
    # The missing-state path must fast-fail with PRECONDITION_NO_STATE with ZERO gh
    # dependency: the gh adapter is built lazily AFTER the state read, so on this path
    # _build_gh is never even called (let alone any gh call).
    build_calls = 0

    def _spy_build_gh() -> GhCli:
        nonlocal build_calls
        build_calls += 1
        return GhCli(RecordedRunner([_ok([]), _ok([])]))

    monkeypatch.setattr(cli, "_build_gh", _spy_build_gh)
    result = runner.invoke(cli.app, ["status", "octo/demo#7"])
    assert result.exit_code == 2
    assert "PRECONDITION_NO_STATE" in result.output
    assert "run `poll`" in result.output
    assert "how:" in result.output
    assert build_calls == 0  # gh adapter never constructed on the fast-fail path


@pytest.mark.usefixtures("patched")
def test_status_malformed_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh())
    result = runner.invoke(cli.app, ["status", "not-a-ref"])
    assert result.exit_code == 2
    assert "PRECONDITION_BAD_PR_REF" in result.output


def test_status_locked_success_reads_under_lock(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The uncontended --locked path: acquire the lock, read, release, render. Proves
    # the strictly-consistent read succeeds (the contention test only proves the raise).
    patched.write(_REF, _quiesced_state())
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh())
    result = runner.invoke(cli.app, ["status", "octo/demo#7", "--locked", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["pr"] == 7
    # The lock was released on the way out, so a subsequent acquire succeeds.
    assert patched.try_acquire(_REF)
    patched.release(_REF)


def test_status_locked_contention_exits_75(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    patched.write(_REF, _quiesced_state())
    # The lock is acquired before the state read, so --locked contention is the other
    # gh-independent fast-fail path: the adapter is never constructed.
    build_calls = 0

    def _spy_build_gh() -> GhCli:
        nonlocal build_calls
        build_calls += 1
        return _gh()

    monkeypatch.setattr(cli, "_build_gh", _spy_build_gh)
    # Pre-hold the lock so --locked's acquire fails non-blocking → exit 75.
    assert patched.try_acquire(_REF)
    try:
        result = runner.invoke(cli.app, ["status", "octo/demo#7", "--locked"])
    finally:
        patched.release(_REF)
    assert result.exit_code == 75
    assert "PRECONDITION_LOCK_HELD" in result.output
    assert build_calls == 0  # contention fails before constructing gh


def test_status_lockfree_reads_under_held_lock(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The §3.3 carve-out: the default status does NOT acquire the lock, so it reads
    # cleanly even while another holder owns it — the whole point of the carve-out.
    patched.write(_REF, _quiesced_state())
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh())
    assert patched.try_acquire(_REF)
    try:
        result = runner.invoke(cli.app, ["status", "octo/demo#7", "--json"])
    finally:
        patched.release(_REF)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["auto_merge_eligible"] is True


def test_status_bot_approval_does_not_satisfy(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    patched.write(_REF, _quiesced_state())
    monkeypatch.setattr(
        cli,
        "_build_gh",
        lambda: _gh(
            labels=[{"name": "human-review-required"}],
            reviews=[
                {"state": "APPROVED", "user": {"login": "github-copilot[bot]", "type": "Bot"}}
            ],
        ),
    )
    result = runner.invoke(cli.app, ["status", "octo/demo#7", "--json"])
    assert result.exit_code == 0, result.output
    env = json.loads(result.output)
    assert env["human_review"]["required"] is True
    assert env["merge_gates"]["human_review_satisfied"] is False
    assert env["auto_merge_eligible"] is False
    assert env["human_review"]["candidates_seen"][0]["reason"] == "bot"


def test_status_human_approval_satisfies(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    patched.write(_REF, _quiesced_state())
    monkeypatch.setattr(
        cli,
        "_build_gh",
        lambda: _gh(
            labels=[{"name": "human-review-required"}],
            reviews=[{"state": "APPROVED", "user": {"login": "alice", "type": "User"}}],
        ),
    )
    result = runner.invoke(cli.app, ["status", "octo/demo#7", "--json"])
    assert result.exit_code == 0, result.output
    env = json.loads(result.output)
    assert env["human_review"]["satisfied_by"] == "approval:alice"
    assert env["auto_merge_eligible"] is True


def test_status_gh_failure_propagates(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A gh terminal error during the human-review enrichment renders the tier code.
    patched.write(_REF, _quiesced_state())
    monkeypatch.setattr(
        cli,
        "_build_gh",
        lambda: GhCli(
            RecordedRunner(
                [CommandResult(returncode=1, stdout="{}", stderr="gh: Bad credentials (HTTP 401)")]
            )
        ),
    )
    result = runner.invoke(cli.app, ["status", "octo/demo#7", "--json"])
    assert result.exit_code == 77
    assert "RUNTIME_GH_TERMINAL" in result.output


def test_status_gh_404_enrichment_maps_to_terminal(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A 404 during the live human-review enrichment (PR closed/deleted, or repo
    # access lost between the lock-free state read and the enrichment) must map to a
    # terminal PrgroomError (exit 77), NOT escape as a raw GhNotFoundError traceback —
    # the same convention poll.py's _vanished_pr_terminal pins.
    patched.write(_REF, _quiesced_state())
    monkeypatch.setattr(
        cli,
        "_build_gh",
        lambda: GhCli(
            RecordedRunner(
                [CommandResult(returncode=1, stdout="{}", stderr="gh: Not Found (HTTP 404)")]
            )
        ),
    )
    result = runner.invoke(cli.app, ["status", "octo/demo#7", "--json"])
    assert result.exit_code == 77
    assert "RUNTIME_GH_TERMINAL" in result.output
