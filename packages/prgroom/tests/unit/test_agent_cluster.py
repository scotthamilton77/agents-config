"""Tests for ``run_cluster`` orchestration (§5: retry-once → degenerate fallback).

``run_cluster`` dispatches, audits, and on failure retries once; a second
failure (or a both-fail) falls back to per-item degenerate clusters that are
coverage-complete by construction. It is pure of state — it returns a
:class:`ClusterRunResult`, never mutating ``PRGroomingState``. The fakes mirror
the ``ClusterContract`` Protocol exactly.
"""

from __future__ import annotations

from datetime import UTC, datetime

from prgroom.agent.cluster import run_cluster
from prgroom.agent.contracts import ClusterInput, ClusterOutput, ClusterResult
from prgroom.agent.dispatcher import AllProvidersFailedError, Dispatched
from prgroom.agent.subprocess_runner import AgentSpec
from prgroom.prsession.enums import ItemKind
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import Identity, ReviewItem

_NOW = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
_REF = PRRef("octo", "demo", 7)


def _item(gh_id: str) -> ReviewItem:
    return ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id=gh_id, thread_id=f"PRT_{gh_id}"),
        author="copilot",
        body_excerpt="x",
        seen_at=_NOW,
    )


def _req(*gh_ids: str) -> ClusterInput:
    return ClusterInput(
        pr=_REF, items=[_item(g) for g in gh_ids], pr_context_path="/ctx", memory_path=None
    )


class ScriptedClusterDispatcher:
    """A ``ClusterContract`` fake driven by a queue of per-call outcomes.

    Each queued outcome is either a :class:`ClusterOutput` to return or an
    exception instance to raise, so a test scripts the exact dispatch sequence.
    """

    def __init__(self, outcomes: list[ClusterOutput | Exception]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def cluster(self, request: ClusterInput) -> Dispatched[ClusterOutput]:
        del request  # scripted by call order; mirrors the ClusterContract Protocol
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return Dispatched(output=outcome, winner=AgentSpec(cli="ollama", model="gemma4"))


def _one_cluster(req: ClusterInput, *, rationale: str = "all of them") -> ClusterOutput:
    return ClusterOutput(
        clusters=[
            ClusterResult(
                cluster_id="c-1",
                item_gh_ids=[i.identity.gh_id for i in req.items],
                rationale=rationale,
            )
        ]
    )


def test_clean_first_attempt_passes_through() -> None:
    req = _req("C_1", "C_2")
    disp = ScriptedClusterDispatcher([_one_cluster(req)])
    result = run_cluster(req, disp)
    assert disp.calls == 1
    assert result.attempts == 1
    assert result.degenerate is False
    assert result.assignments == {"C_1": "c-1", "C_2": "c-1"}


def test_retry_once_succeeds_on_second_attempt() -> None:
    req = _req("C_1")
    # First attempt fails audit (empty rationale); second is clean.
    bad = ClusterOutput(
        clusters=[ClusterResult(cluster_id="c-1", item_gh_ids=["C_1"], rationale="")]
    )
    disp = ScriptedClusterDispatcher([bad, _one_cluster(req)])
    result = run_cluster(req, disp)
    assert disp.calls == 2
    assert result.attempts == 2
    assert result.degenerate is False
    assert result.assignments == {"C_1": "c-1"}


def test_two_audit_failures_fall_back_to_degenerate() -> None:
    req = _req("C_1", "C_2")
    bad = ClusterOutput(clusters=[])  # coverage-empty — fails audit twice
    disp = ScriptedClusterDispatcher([bad, bad])
    result = run_cluster(req, disp)
    assert disp.calls == 2
    assert result.degenerate is True
    # One cluster per item, coverage-complete by construction.
    assert set(result.assignments) == {"C_1", "C_2"}
    assert len({result.assignments[g] for g in ("C_1", "C_2")}) == 2


def test_both_fail_twice_falls_back_to_degenerate_without_agent() -> None:
    req = _req("C_1")
    err = AllProvidersFailedError(detail="ollama down; haiku down")
    disp = ScriptedClusterDispatcher([err, err])
    result = run_cluster(req, disp)
    assert disp.calls == 2
    assert result.degenerate is True
    assert set(result.assignments) == {"C_1"}


def test_degenerate_cluster_id_derives_from_gh_id_not_clock() -> None:
    req = _req("C_1")
    err = AllProvidersFailedError(detail="down")
    disp = ScriptedClusterDispatcher([err, err])
    result = run_cluster(req, disp)
    # Deterministic: the id is a pure function of the gh_id (no counter+clock).
    assert result.assignments["C_1"] == "degen-C_1"


def test_degenerate_clusters_each_carry_a_rationale() -> None:
    # Degenerate output must itself pass the cluster audit (non-empty rationale).
    req = _req("C_1", "C_2")
    err = AllProvidersFailedError(detail="down")
    disp = ScriptedClusterDispatcher([err, err])
    result = run_cluster(req, disp)
    assert all(c.rationale.strip() for c in result.clusters)
    assert {c.cluster_id for c in result.clusters} == {"degen-C_1", "degen-C_2"}


def test_first_attempt_both_fail_then_clean_retry_succeeds() -> None:
    # A transient both-fail on attempt 1 followed by a clean attempt 2 must NOT
    # go degenerate — retry-once covers the transient case.
    req = _req("C_1")
    disp = ScriptedClusterDispatcher([AllProvidersFailedError(detail="blip"), _one_cluster(req)])
    result = run_cluster(req, disp)
    assert disp.calls == 2
    assert result.degenerate is False
    assert result.assignments == {"C_1": "c-1"}
