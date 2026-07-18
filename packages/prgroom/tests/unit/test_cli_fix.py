"""Tests for the wired ``fix`` CLI verb (§1, §2, §3.2).

The verb resolves the store + gh/git adapters + a FixDispatcher + a StderrSink,
parses the PR ref, then runs ``read → fix_pr → write`` under the lock wrapper.
The outward seams — ``_build_store``, ``_build_gh``, ``_build_git``, and
``_build_fix_dispatcher`` — are monkeypatched. Direct-invocation preconditions:
no state → NO_STATE; no clusters → NO_CLUSTERS; all dispositioned or terminal →
no-op exit 0.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from prgroom import cli
from prgroom.agent.contracts import FixInput, FixItemResult, FixOutput
from prgroom.agent.dispatcher import Dispatched
from prgroom.agent.subprocess_runner import AgentSpec
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

runner = CliRunner()

_REF = PRRef(owner="octo", repo="demo", number=7)
_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _ok(payload: object) -> CommandResult:
    return CommandResult(returncode=0, stdout=json.dumps(payload), stderr="")


class FakeGit:
    def head_sha(self) -> str:
        return "head"

    def rev_list(self, range_: str) -> list[str]:
        del range_
        return []

    def log(self, range_: str) -> str:
        del range_
        return "recent commits"

    def diff_stat(self, range_: str) -> str:
        del range_
        return "diff stat"

    def push(self, remote: str, branch: str) -> None:  # pragma: no cover - unused
        del remote, branch

    def stash(self) -> None:  # pragma: no cover - unused
        return None


class FixDispatcherStub:
    def __init__(self, output: FixOutput) -> None:
        self._output = output
        self.calls = 0

    def fix(self, request: FixInput) -> Dispatched[FixOutput]:
        del request
        self.calls += 1
        return Dispatched(output=self._output, winner=AgentSpec(cli="claude", model="opus[1m]"))


def _item(
    gh_id: str, *, cluster_id: str = "c-1", disposition: Disposition | None = None
) -> ReviewItem:
    return ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id=gh_id, thread_id=f"PRT_{gh_id}"),
        author="copilot",
        body_excerpt="fix this",
        seen_at=_T0,
        cluster_id=cluster_id,
        disposition=disposition,
    )


def _state(*items: ReviewItem, phase: PRPhase = PRPhase.FIXES_PENDING) -> PRGroomingState:
    return PRGroomingState(
        pr=_REF,
        phase=phase,
        pr_review_retries_used=1,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(ci_state="success"),
        items=list(items),
    )


def _gh() -> GhCli:
    from tests.fakes import RecordedRunner

    pr_resource = {"body": "desc", "base": {"ref": "main"}, "labels": []}
    return GhCli(RecordedRunner([_ok(pr_resource), _ok([])]))


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> InMemoryStore:
    store = InMemoryStore()
    monkeypatch.setattr(cli, "_build_store", lambda _name: store)
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh())
    monkeypatch.setattr(cli, "_build_git", lambda: FakeGit())
    return store


def _wire_dispatcher(monkeypatch: pytest.MonkeyPatch, dispatcher: FixDispatcherStub) -> None:
    monkeypatch.setattr(cli, "_build_fix_dispatcher", lambda: dispatcher)


def test_fix_applies_and_persists(patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch) -> None:
    patched.write(_REF, _state(_item("a")))
    dispatcher = FixDispatcherStub(
        FixOutput(
            items=[FixItemResult(gh_id="a", disposition=DispositionKind.SKIPPED, rationale="ack")]
        )
    )
    _wire_dispatcher(monkeypatch, dispatcher)
    result = runner.invoke(cli.app, ["fix", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    written = patched.read(_REF)
    assert written.items[0].disposition is not None
    assert written.items[0].disposition.kind is DispositionKind.SKIPPED
    assert written.items[0].disposition.decided_by == "claude opus[1m]"


@pytest.mark.usefixtures("patched")
def test_fix_no_state_exits_two(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_dispatcher(monkeypatch, FixDispatcherStub(FixOutput(items=[])))
    result = runner.invoke(cli.app, ["fix", "octo/demo#7"])
    assert result.exit_code == 2
    assert "PRECONDITION_NO_STATE" in result.output


def test_fix_no_clusters_exits_zero_no_work(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Items exist but none are clustered (cluster_id == "") → nothing to fix.
    patched.write(_REF, _state(_item("a", cluster_id="")))
    _wire_dispatcher(monkeypatch, FixDispatcherStub(FixOutput(items=[])))
    result = runner.invoke(cli.app, ["fix", "octo/demo#7"])
    assert result.exit_code == 0
    assert "PRECONDITION_NO_CLUSTERS" in result.output


def test_fix_all_dispositioned_is_idempotent_noop(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    disp = Disposition(kind=DispositionKind.FIXED, decided_at=_T0, decided_by="x")
    patched.write(_REF, _state(_item("a", disposition=disp)))
    dispatcher = FixDispatcherStub(FixOutput(items=[]))
    _wire_dispatcher(monkeypatch, dispatcher)
    result = runner.invoke(cli.app, ["fix", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert dispatcher.calls == 0  # nothing to fix → no dispatch
    # All-dispositioned is the idempotent "already done" no-op — NOT the misleading
    # NO_CLUSTERS "run cluster first" precondition (which also exits 0).
    assert "PRECONDITION_NO_CLUSTERS" not in result.output


def test_fix_terminal_phase_is_noop(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    patched.write(_REF, _state(_item("a"), phase=PRPhase.MERGED))
    dispatcher = FixDispatcherStub(FixOutput(items=[]))
    _wire_dispatcher(monkeypatch, dispatcher)
    result = runner.invoke(cli.app, ["fix", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert dispatcher.calls == 0
    assert patched.read(_REF).items[0].disposition is None


def test_fix_malformed_ref_exits_two() -> None:
    result = runner.invoke(cli.app, ["fix", "not-a-ref"])
    assert result.exit_code == 2
    assert "PRECONDITION_BAD_PR_REF" in result.output
