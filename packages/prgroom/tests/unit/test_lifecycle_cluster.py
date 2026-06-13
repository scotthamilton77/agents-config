"""Tests for ``cluster_pr`` — the lock-held ``_cluster`` lifecycle internal (§3.2, §5).

``cluster_pr`` mirrors ``poll_pr``: it works on a deepcopy of the in-memory
``PRGroomingState``, calls 8.7's pure ``run_cluster`` compute, and APPLIES the
returned assignments by setting each item's ``cluster_id``. It decides NO
disposition and makes NO phase change (the §3.2 cluster row). The dispatcher is a
small ``ClusterContract`` fake; gh/git are fakes at the boundary; the clock is the
injected frozen fake. No code we own is mocked (§7.6).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from prgroom.agent.contracts import ClusterInput, ClusterOutput, ClusterResult
from prgroom.config import PrgroomConfig
from prgroom.deps import Deps
from prgroom.gh import GhCli
from prgroom.lifecycle.cluster import cluster_pr
from prgroom.proc import CommandResult
from prgroom.prsession.enums import DispositionKind, ItemKind, PRPhase
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Disposition,
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewItem,
)
from tests.conftest import FixedRandomness, FrozenClock
from tests.fakes import RecordedRunner

_REF = PRRef(owner="octo", repo="demo", number=7)
_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _ok(payload: object) -> CommandResult:
    return CommandResult(returncode=0, stdout=json.dumps(payload), stderr="")


def _deps() -> Deps:
    return Deps(clock=FrozenClock(_T0), randomness=FixedRandomness())


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
        round=1,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(ci_state="success"),
        items=list(items),
    )


def _gh() -> GhCli:
    """The light PR-context read: just the PR resource (title/body/CI summary)."""
    return GhCli(RecordedRunner([_ok({"title": "My PR", "body": "desc", "base": {"ref": "main"}})]))


class FakeGit:
    """A minimal ``GitClient`` fake for the cluster PR-context file's recent commits."""

    def head_sha(self) -> str:  # pragma: no cover - unused
        return "head"

    def rev_list(self, range_: str) -> list[str]:  # pragma: no cover - unused
        del range_
        return []

    def log(self, range_: str) -> str:
        del range_
        return "abc recent commit"

    def diff_stat(self, range_: str) -> str:  # pragma: no cover - unused by cluster
        del range_
        return ""

    def push(self, remote: str, branch: str) -> None:  # pragma: no cover - unused
        del remote, branch

    def stash(self) -> None:  # pragma: no cover - unused
        return None


class ClusterDispatcherStub:
    """A ``ClusterContract`` fake returning a canned clustering of the input items."""

    def __init__(self, clusters: list[ClusterResult]) -> None:
        self._clusters = clusters
        self.calls = 0
        self.last_request: ClusterInput | None = None

    def cluster(self, request: ClusterInput) -> ClusterOutput:
        self.calls += 1
        self.last_request = request
        return ClusterOutput(clusters=self._clusters)


def _run(
    state: PRGroomingState,
    dispatcher: ClusterDispatcherStub,
    scratch_dir: Path,
    *,
    gh: GhCli | None = None,
) -> PRGroomingState:
    return cluster_pr(
        state,
        ref=_REF,
        gh=gh or _gh(),
        git=FakeGit(),
        deps=_deps(),
        config=PrgroomConfig(),
        dispatcher=dispatcher,
        decided_by="ollama gemma4",
        scratch_dir=scratch_dir,
    )


def test_cluster_applies_assignments_to_unclustered_items(tmp_path: Path) -> None:
    a, b = _item("a"), _item("b")
    dispatcher = ClusterDispatcherStub(
        [ClusterResult(cluster_id="c-x", item_gh_ids=["a", "b"], rationale="same area")]
    )
    out = _run(_state(a, b), dispatcher, tmp_path)
    assert {it.identity.gh_id: it.cluster_id for it in out.items} == {"a": "c-x", "b": "c-x"}
    assert dispatcher.calls == 1


def test_cluster_no_phase_change_and_no_disposition(tmp_path: Path) -> None:
    a = _item("a")
    dispatcher = ClusterDispatcherStub(
        [ClusterResult(cluster_id="c-x", item_gh_ids=["a"], rationale="solo")]
    )
    out = _run(_state(a, phase=PRPhase.FIXES_PENDING), dispatcher, tmp_path)
    assert out.phase is PRPhase.FIXES_PENDING
    assert out.items[0].disposition is None


def test_cluster_idempotent_noop_when_all_already_clustered(tmp_path: Path) -> None:
    a = _item("a", cluster_id="c-existing")
    dispatcher = ClusterDispatcherStub([])
    out = _run(_state(a), dispatcher, tmp_path)
    # Every item already clustered → no dispatch, cluster_id untouched.
    assert dispatcher.calls == 0
    assert out.items[0].cluster_id == "c-existing"


def test_cluster_only_clusters_unclustered_items(tmp_path: Path) -> None:
    done = _item("done", cluster_id="c-old")
    todo = _item("todo")
    dispatcher = ClusterDispatcherStub(
        [ClusterResult(cluster_id="c-new", item_gh_ids=["todo"], rationale="new")]
    )
    out = _run(_state(done, todo), dispatcher, tmp_path)
    by_id = {it.identity.gh_id: it.cluster_id for it in out.items}
    assert by_id == {"done": "c-old", "todo": "c-new"}
    # Only the unclustered item is sent to the dispatcher.
    assert dispatcher.last_request is not None
    assert [it.identity.gh_id for it in dispatcher.last_request.items] == ["todo"]


def test_cluster_skips_dispositioned_items_even_if_unclustered(tmp_path: Path) -> None:
    # A dispositioned-but-unclustered item is already processed; cluster works on
    # cluster_id == "" items, but an already-dispositioned item must not be re-sent.
    disp = Disposition(kind=DispositionKind.FIXED, decided_at=_T0, decided_by="x")
    processed = _item("p", disposition=disp)
    fresh = _item("f")
    dispatcher = ClusterDispatcherStub(
        [ClusterResult(cluster_id="c-1", item_gh_ids=["f"], rationale="r")]
    )
    out = _run(_state(processed, fresh), dispatcher, tmp_path)
    assert dispatcher.last_request is not None
    assert [it.identity.gh_id for it in dispatcher.last_request.items] == ["f"]
    by_id = {it.identity.gh_id: it.cluster_id for it in out.items}
    assert by_id["f"] == "c-1"
    assert by_id["p"] == ""  # processed item is left untouched


def test_cluster_does_not_mutate_caller_state(tmp_path: Path) -> None:
    a = _item("a")
    state = _state(a)
    dispatcher = ClusterDispatcherStub(
        [ClusterResult(cluster_id="c-x", item_gh_ids=["a"], rationale="r")]
    )
    _run(state, dispatcher, tmp_path)
    # cluster_pr works on a deepcopy; the caller's object is unchanged.
    assert state.items[0].cluster_id == ""


def test_cluster_writes_pr_context_file(tmp_path: Path) -> None:
    a = _item("a")
    dispatcher = ClusterDispatcherStub(
        [ClusterResult(cluster_id="c-x", item_gh_ids=["a"], rationale="r")]
    )
    _run(_state(a), dispatcher, tmp_path)
    assert dispatcher.last_request is not None
    ctx_path = Path(dispatcher.last_request.pr_context_path)
    assert ctx_path.is_file()
    ctx = ctx_path.read_text(encoding="utf-8")
    assert "My PR" in ctx  # title from the gh PR resource
    assert "abc recent commit" in ctx  # recent commits from git
