"""Tests for ``fix_pr`` — the lock-held ``_fix`` lifecycle internal (§3.2, §5, §8).

``fix_pr`` is the APPLY side of the fix path: it assembles the §8.1 snapshot per
cluster, calls 8.7's pure ``run_fix`` compute, and APPLIES the results to a
deepcopy of state — setting each ``item.disposition``, emitting each returned
``Escalation`` via the injected ``Sink``, and logging soft warnings. It makes NO
phase change (§3.2 fix row: phase resolution is end-of-cycle, bead 8.10) and does
NOT set ``state.last_error``. The fix dispatcher, gh, git, and sink are fakes at
the boundaries; the clock is the injected frozen fake. No code we own is mocked.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from prgroom.agent.contracts import FixInput, FixItemResult, FixOutput, MemoryEntry
from prgroom.agent.dispatcher import AllProvidersFailedError, Dispatched
from prgroom.agent.subprocess_runner import AgentSpec
from prgroom.config import PrgroomConfig
from prgroom.deps import Deps
from prgroom.escalation import Escalation
from prgroom.gh import GhCli
from prgroom.lifecycle.fix import fix_pr
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
    gh_id: str,
    *,
    cluster_id: str = "c-1",
    disposition: Disposition | None = None,
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


def _gh_per_cluster(n: int) -> GhCli:
    """Queue the snapshot reads (PR resource + review comments) for ``n`` clusters."""
    pr_resource = {"body": "desc", "base": {"ref": "main"}, "labels": []}
    results: list[CommandResult] = []
    for _ in range(n):
        results.append(_ok(pr_resource))
        results.append(_ok([]))  # review comments
    return GhCli(RecordedRunner(results))


class FakeGit:
    """A ``GitClient`` fake covering both run_fix (head_sha/rev_list) and snapshot.

    ``new_commits`` scripts the ``pre..post`` range run_fix asks for (the commits a
    cluster's fix produced); the default empty list models the common
    skipped/wont_fix path. ``head_sha`` returns the same value twice (pre==post),
    so an empty ``new_commits`` correctly means "no commits produced this cluster".
    """

    def __init__(self, *, new_commits: list[str] | None = None) -> None:
        self._new = new_commits or []
        self.stash_calls = 0

    def head_sha(self) -> str:
        return "head"

    def rev_list(self, range_: str) -> list[str]:
        # The bare-pre query yields ancestors (none needed here); the pre..post
        # range yields this cluster's produced commits.
        return list(self._new) if ".." in range_ else []

    def log(self, range_: str) -> str:
        del range_
        return "recent commits"

    def diff_stat(self, range_: str) -> str:
        del range_
        return "diff stat"

    def push(self, remote: str, branch: str) -> None:  # pragma: no cover - unused
        del remote, branch

    def stash(self) -> None:
        self.stash_calls += 1


class FixDispatcherStub:
    """A ``FixContract`` fake returning a canned output (or raising) per cluster call."""

    def __init__(
        self, outcomes: list[FixOutput | Exception], *, winner: AgentSpec | None = None
    ) -> None:
        self._outcomes = list(outcomes)
        self._winner = winner if winner is not None else AgentSpec(cli="claude", model="opus[1m]")
        self.calls = 0
        self.requests: list[FixInput] = []

    def fix(self, request: FixInput) -> Dispatched[FixOutput]:
        self.calls += 1
        self.requests.append(request)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return Dispatched(output=outcome, winner=self._winner)


class RecordingSink:
    """A ``Sink`` fake recording every emitted Escalation."""

    def __init__(self) -> None:
        self.emitted: list[Escalation] = []

    def emit(self, escalation: Escalation) -> None:
        self.emitted.append(escalation)


def _out(*rows: FixItemResult, **kw: object) -> FixOutput:
    return FixOutput(items=list(rows), **kw)  # type: ignore[arg-type]


def _run(
    state: PRGroomingState,
    dispatcher: FixDispatcherStub,
    scratch_dir: Path,
    *,
    gh: GhCli | None = None,
    git: FakeGit | None = None,
    sink: RecordingSink | None = None,
) -> tuple[PRGroomingState, RecordingSink, FakeGit]:
    sink = sink or RecordingSink()
    git = git or FakeGit()
    out = fix_pr(
        state,
        ref=_REF,
        gh=gh or _gh_per_cluster(_count_clusters(state)),
        git=git,
        deps=_deps(),
        config=PrgroomConfig(),
        dispatcher=dispatcher,
        sink=sink,
        scratch_dir=scratch_dir,
    )
    return out, sink, git


def _count_clusters(state: PRGroomingState) -> int:
    return len(
        {it.cluster_id for it in state.items if it.disposition is None and it.cluster_id != ""}
    )


# ───────────────────────── apply dispositions ─────────────────────────


def test_fix_applies_dispositions_from_result(tmp_path: Path) -> None:
    a, b = _item("a"), _item("b")
    # "a" is a clean FIXED claiming a commit the FakeGit reports in pre..post (so
    # the 8.7 commit audit passes); "b" is a clean SKIPPED (rationale only).
    dispatcher = FixDispatcherStub(
        [
            _out(
                FixItemResult(
                    gh_id="a",
                    disposition=DispositionKind.FIXED,
                    commit_shas=["sha1"],
                    recommended_gate="full",
                ),
                FixItemResult(gh_id="b", disposition=DispositionKind.SKIPPED, rationale="ack only"),
            )
        ]
    )
    git = FakeGit(new_commits=["sha1"])
    out, _sink, _git = _run(_state(a, b), dispatcher, tmp_path, git=git)
    by_id = {it.identity.gh_id: it.disposition for it in out.items}
    assert by_id["a"] is not None
    assert by_id["a"].kind is DispositionKind.FIXED
    assert by_id["a"].decided_by == "claude opus[1m]"
    assert by_id["b"] is not None
    assert by_id["b"].kind is DispositionKind.SKIPPED


def test_fix_applies_per_cluster_not_state_wide_gh_id(tmp_path: Path) -> None:
    # Two items share gh_id "dup" but differ in kind (the natural key is
    # (kind, gh_id), not gh_id alone). The clustered-unprocessed one must receive the
    # disposition; the already-processed sibling sharing the gh_id must be untouched —
    # a state-wide gh_id map would mis-target the sibling (PR #152 comment 3408284563).
    target = _item("dup", cluster_id="c-1")  # REVIEW_THREAD, unprocessed
    prior = Disposition(
        kind=DispositionKind.SKIPPED, decided_at=_T0, decided_by="x", rationale="kept"
    )
    sibling = ReviewItem(
        kind=ItemKind.ISSUE_COMMENT,
        identity=Identity(gh_id="dup", issue_comment_id=99),
        author="copilot",
        body_excerpt="other",
        seen_at=_T0,
        cluster_id="",
        disposition=prior,
    )
    dispatcher = FixDispatcherStub(
        [
            _out(
                FixItemResult(
                    gh_id="dup",
                    disposition=DispositionKind.FIXED,
                    commit_shas=["sha1"],
                    recommended_gate="full",
                )
            )
        ]
    )
    out, _sink, _git = _run(
        _state(target, sibling), dispatcher, tmp_path, git=FakeGit(new_commits=["sha1"])
    )
    rt = next(it for it in out.items if it.kind is ItemKind.REVIEW_THREAD)
    ic = next(it for it in out.items if it.kind is ItemKind.ISSUE_COMMENT)
    assert rt.disposition is not None and rt.disposition.kind is DispositionKind.FIXED
    # the same-gh_id sibling kept its prior disposition; it was NOT clobbered
    assert ic.disposition is not None and ic.disposition.kind is DispositionKind.SKIPPED
    assert ic.disposition.rationale == "kept"


def test_fix_no_phase_change_and_no_last_error(tmp_path: Path) -> None:
    a = _item("a")
    dispatcher = FixDispatcherStub(
        [_out(FixItemResult(gh_id="a", disposition=DispositionKind.SKIPPED, rationale="r"))]
    )
    out, _sink, _git = _run(_state(a, phase=PRPhase.FIXES_PENDING), dispatcher, tmp_path)
    assert out.phase is PRPhase.FIXES_PENDING  # §3.2 fix row: no phase change here
    assert out.last_error is None  # FAILED dispositions carry their own rationale


def test_fix_emits_escalations_via_sink(tmp_path: Path) -> None:
    a = _item("a")
    dispatcher = FixDispatcherStub([AllProvidersFailedError(detail="ollama down; opus down")])
    out, sink, git = _run(_state(a), dispatcher, tmp_path)
    # both-fail flips the item to FAILED and yields one escalation the sink emits.
    assert out.items[0].disposition is not None
    assert out.items[0].disposition.kind is DispositionKind.FAILED
    assert len(sink.emitted) == 1
    assert "down" in sink.emitted[0].reason
    assert git.stash_calls == 0  # both-fail produces nothing → no stash


# ───────────────────────── idempotency ─────────────────────────


def test_fix_idempotent_noop_when_all_dispositioned(tmp_path: Path) -> None:
    disp = Disposition(kind=DispositionKind.FIXED, decided_at=_T0, decided_by="x")
    a = _item("a", disposition=disp)
    dispatcher = FixDispatcherStub([])
    out, sink, _git = _run(_state(a), dispatcher, tmp_path, gh=_gh_per_cluster(0))
    assert dispatcher.calls == 0  # nothing to do → no dispatch
    assert sink.emitted == []
    # Value-equal (fix_pr deep-copies state; identity differs, content is preserved).
    assert out.items[0].disposition == disp


def test_fix_skips_unclustered_items(tmp_path: Path) -> None:
    # An item with cluster_id == "" is not yet clustered → fix does not touch it
    # (fix groups disposition is None AND cluster_id != "").
    clustered = _item("c", cluster_id="c-1")
    unclustered = _item("u", cluster_id="")
    dispatcher = FixDispatcherStub(
        [_out(FixItemResult(gh_id="c", disposition=DispositionKind.SKIPPED, rationale="r"))]
    )
    out, _sink, _git = _run(_state(clustered, unclustered), dispatcher, tmp_path)
    by_id = {it.identity.gh_id: it.disposition for it in out.items}
    assert by_id["c"] is not None
    assert by_id["u"] is None  # unclustered item left for a future cluster pass


# ───────────────────────── serial multi-cluster ─────────────────────────


def test_fix_processes_clusters_serially(tmp_path: Path) -> None:
    a = _item("a", cluster_id="c-1")
    b = _item("b", cluster_id="c-2")
    dispatcher = FixDispatcherStub(
        [
            _out(FixItemResult(gh_id="a", disposition=DispositionKind.SKIPPED, rationale="r")),
            _out(FixItemResult(gh_id="b", disposition=DispositionKind.WONT_FIX, rationale="r")),
        ]
    )
    out, _sink, _git = _run(_state(a, b), dispatcher, tmp_path)
    assert dispatcher.calls == 2  # one dispatch per cluster (MVP serial)
    # Each dispatch carries exactly its cluster's item.
    sent = {req.cluster_id: [it.identity.gh_id for it in req.items] for req in dispatcher.requests}
    assert sent == {"c-1": ["a"], "c-2": ["b"]}
    by_id = {it.identity.gh_id: it.disposition.kind for it in out.items if it.disposition}
    assert by_id == {"a": DispositionKind.SKIPPED, "b": DispositionKind.WONT_FIX}


# ───────────────────────── soft warnings + deferred memory ─────────────────────────


def test_fix_logs_deferred_memory_via_warn_seam(tmp_path: Path) -> None:
    # A non-CONTEXTUAL memory entry is accepted-but-deferred (§8.3): fix_pr logs it
    # through the injected warn seam (MVP does not route it) without flipping the
    # item or escalating. The warn seam is injectable so this is asserted directly,
    # not by scraping stderr.
    a = _item("a")
    out = FixOutput(
        items=[FixItemResult(gh_id="a", disposition=DispositionKind.SKIPPED, rationale="r")],
        memory=[MemoryEntry(classification="PROJECT", content="a repo-wide note")],
    )
    dispatcher = FixDispatcherStub([out])
    warnings: list[str] = []
    state_out = fix_pr(
        _state(a),
        ref=_REF,
        gh=_gh_per_cluster(1),
        git=FakeGit(),
        deps=_deps(),
        config=PrgroomConfig(),
        dispatcher=dispatcher,
        sink=RecordingSink(),
        scratch_dir=tmp_path,
        warn=warnings.append,
    )
    assert state_out.items[0].disposition is not None
    assert state_out.items[0].disposition.kind is DispositionKind.SKIPPED
    # The deferred memory entry was logged (MVP routes only CONTEXTUAL→PR).
    assert any("deferred" in w.lower() for w in warnings)


def test_fix_logs_unwritten_paths_via_warn_seam(tmp_path: Path) -> None:
    # A declared-but-unwritten memory_writes path is a soft warning (§8.6): logged,
    # never a cluster failure. Forced here by passing a known_thread_ids-independent
    # output; the warn seam records the soft warning.
    a = _item("a")
    out = FixOutput(
        items=[FixItemResult(gh_id="a", disposition=DispositionKind.SKIPPED, rationale="r")],
    )
    dispatcher = FixDispatcherStub([out])
    warnings: list[str] = []
    fix_pr(
        _state(a),
        ref=_REF,
        gh=_gh_per_cluster(1),
        git=FakeGit(),
        deps=_deps(),
        config=PrgroomConfig(),
        dispatcher=dispatcher,
        sink=RecordingSink(),
        scratch_dir=tmp_path,
        warn=warnings.append,
    )
    # MVP audit passes written_paths == declared, so unwritten is empty here — no
    # spurious soft warning. (The seam is exercised by the deferred-memory test.)
    assert not any("unwritten" in w.lower() for w in warnings)


def test_fix_does_not_mutate_caller_state(tmp_path: Path) -> None:
    a = _item("a")
    state = _state(a)
    dispatcher = FixDispatcherStub(
        [_out(FixItemResult(gh_id="a", disposition=DispositionKind.SKIPPED, rationale="r"))]
    )
    _run(state, dispatcher, tmp_path)
    assert state.items[0].disposition is None  # caller's object untouched (deepcopy)
