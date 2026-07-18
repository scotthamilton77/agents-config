"""Tests for the wired ``cluster`` CLI verb (§1, §2, §3.2).

The verb resolves the store + gh/git adapters + a ClusterDispatcher, parses the
PR ref, then runs ``read → cluster_pr → write`` under the lock wrapper. The
outward seams — ``_build_store``, ``_build_gh``, ``_build_git``, and
``_build_cluster_dispatcher`` — are monkeypatched so the verb runs against an
InMemoryStore + fakes (no real subprocess, no real disk). Preconditions for
direct invocation: no state → NO_STATE; no items → NO_ITEMS; already-clustered or
terminal → no-op exit 0.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from prgroom import cli
from prgroom.agent.contracts import ClusterInput, ClusterOutput, ClusterResult
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
    def head_sha(self) -> str:  # pragma: no cover - unused
        return "head"

    def rev_list(self, range_: str) -> list[str]:  # pragma: no cover - unused
        del range_
        return []

    def log(self, range_: str) -> str:
        del range_
        return "recent commits"

    def diff_stat(self, range_: str) -> str:  # pragma: no cover - unused
        del range_
        return ""

    def push(self, remote: str, branch: str) -> None:  # pragma: no cover - unused
        del remote, branch

    def stash(self) -> None:  # pragma: no cover - unused
        return None


class ClusterDispatcherStub:
    def __init__(self, clusters: list[ClusterResult]) -> None:
        self._clusters = clusters
        self.calls = 0

    def cluster(self, request: ClusterInput) -> Dispatched[ClusterOutput]:
        del request
        self.calls += 1
        return Dispatched(
            output=ClusterOutput(clusters=self._clusters),
            winner=AgentSpec(cli="ollama", model="gemma4"),
        )


def _item(
    gh_id: str, *, cluster_id: str = "", disposition: Disposition | None = None
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

    return GhCli(RecordedRunner([_ok({"title": "My PR", "body": "desc", "base": {"ref": "main"}})]))


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> InMemoryStore:
    store = InMemoryStore()
    monkeypatch.setattr(cli, "_build_store", lambda _name: store)
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh())
    monkeypatch.setattr(cli, "_build_git", lambda: FakeGit())
    return store


def _wire_dispatcher(monkeypatch: pytest.MonkeyPatch, dispatcher: ClusterDispatcherStub) -> None:
    monkeypatch.setattr(cli, "_build_cluster_dispatcher", lambda: dispatcher)


def test_cluster_applies_and_persists(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    patched.write(_REF, _state(_item("a"), _item("b")))
    dispatcher = ClusterDispatcherStub(
        [ClusterResult(cluster_id="c-x", item_gh_ids=["a", "b"], rationale="same area")]
    )
    _wire_dispatcher(monkeypatch, dispatcher)
    result = runner.invoke(cli.app, ["cluster", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    written = patched.read(_REF)
    assert {it.identity.gh_id: it.cluster_id for it in written.items} == {"a": "c-x", "b": "c-x"}


@pytest.mark.usefixtures("patched")
def test_cluster_no_state_exits_two(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_dispatcher(monkeypatch, ClusterDispatcherStub([]))
    result = runner.invoke(cli.app, ["cluster", "octo/demo#7"])
    assert result.exit_code == 2
    assert "PRECONDITION_NO_STATE" in result.output


def test_cluster_no_items_exits_zero_no_work(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    patched.write(_REF, _state())  # state exists but has no items at all
    _wire_dispatcher(monkeypatch, ClusterDispatcherStub([]))
    result = runner.invoke(cli.app, ["cluster", "octo/demo#7"])
    assert result.exit_code == 0
    assert "PRECONDITION_NO_ITEMS" in result.output


def test_cluster_already_clustered_is_idempotent_noop(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    patched.write(_REF, _state(_item("a", cluster_id="c-old")))
    dispatcher = ClusterDispatcherStub([])
    _wire_dispatcher(monkeypatch, dispatcher)
    result = runner.invoke(cli.app, ["cluster", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert dispatcher.calls == 0  # nothing to cluster → no dispatch
    assert patched.read(_REF).items[0].cluster_id == "c-old"


def test_cluster_terminal_phase_is_noop(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A merged PR is terminal: cluster is a no-op exit 0 even with unclustered items.
    patched.write(_REF, _state(_item("a"), phase=PRPhase.MERGED))
    dispatcher = ClusterDispatcherStub([])
    _wire_dispatcher(monkeypatch, dispatcher)
    result = runner.invoke(cli.app, ["cluster", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert dispatcher.calls == 0
    assert patched.read(_REF).items[0].cluster_id == ""


def test_cluster_all_items_dispositioned_is_no_items(
    patched: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Items exist but all are processed (dispositioned) → nothing needs clustering.
    disp = Disposition(kind=DispositionKind.FIXED, decided_at=_T0, decided_by="x")
    patched.write(_REF, _state(_item("a", cluster_id="c1", disposition=disp)))
    dispatcher = ClusterDispatcherStub([])
    _wire_dispatcher(monkeypatch, dispatcher)
    result = runner.invoke(cli.app, ["cluster", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert dispatcher.calls == 0


def test_cluster_malformed_ref_exits_two() -> None:
    result = runner.invoke(cli.app, ["cluster", "not-a-ref"])
    assert result.exit_code == 2
    assert "PRECONDITION_BAD_PR_REF" in result.output
