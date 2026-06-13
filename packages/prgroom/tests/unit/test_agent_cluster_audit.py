"""Tests for the pure cluster-output validator (§5 audit guards).

``audit_cluster`` is pure (no I/O) and returns one
:class:`~prgroom.agent.errors.AuditViolation` per breach, ``[]`` when clean. §5
pins four invariants: total coverage (every input item in exactly one cluster),
unique cluster ids, no cluster naming an unknown item, and a non-empty rationale
per cluster.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prgroom.agent.cluster_audit import audit_cluster
from prgroom.agent.contracts import ClusterInput, ClusterOutput, ClusterResult
from prgroom.errors import ErrorCode
from prgroom.prsession.enums import ItemKind
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import Identity, ReviewItem

_T = datetime(2026, 6, 13, tzinfo=UTC)
_REF = PRRef("octo", "demo", 7)


def _item(gh_id: str) -> ReviewItem:
    return ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id=gh_id, thread_id=f"PRT_{gh_id}"),
        author="copilot",
        body_excerpt="x",
        seen_at=_T,
    )


def _req(*gh_ids: str) -> ClusterInput:
    return ClusterInput(
        pr=_REF, items=[_item(g) for g in gh_ids], pr_context_path="/ctx", memory_path=None
    )


def _out(*clusters: ClusterResult) -> ClusterOutput:
    return ClusterOutput(clusters=list(clusters))


def test_clean_output_returns_no_violations() -> None:
    req = _req("C_1", "C_2")
    out = _out(
        ClusterResult(cluster_id="c-1", item_gh_ids=["C_1"], rationale="file a"),
        ClusterResult(cluster_id="c-2", item_gh_ids=["C_2"], rationale="file b"),
    )
    assert audit_cluster(req, out) == []


def test_missing_item_is_a_coverage_violation() -> None:
    req = _req("C_1", "C_2")
    out = _out(ClusterResult(cluster_id="c-1", item_gh_ids=["C_1"], rationale="r"))
    codes = [v.code for v in audit_cluster(req, out)]
    assert ErrorCode.CONTRACT_CLUSTER_COVERAGE in codes


def test_item_in_two_clusters_is_a_coverage_violation() -> None:
    # Appearing twice is a coverage/exclusivity break; pinned to COVERAGE (the
    # spec's chosen code for the exclusivity break, not MALFORMED).
    req = _req("C_1")
    out = _out(
        ClusterResult(cluster_id="c-1", item_gh_ids=["C_1"], rationale="r1"),
        ClusterResult(cluster_id="c-2", item_gh_ids=["C_1"], rationale="r2"),
    )
    codes = [v.code for v in audit_cluster(req, out)]
    assert ErrorCode.CONTRACT_CLUSTER_COVERAGE in codes


def test_duplicate_cluster_id_is_malformed() -> None:
    req = _req("C_1", "C_2")
    out = _out(
        ClusterResult(cluster_id="dup", item_gh_ids=["C_1"], rationale="r1"),
        ClusterResult(cluster_id="dup", item_gh_ids=["C_2"], rationale="r2"),
    )
    codes = [v.code for v in audit_cluster(req, out)]
    assert ErrorCode.CONTRACT_CLUSTER_MALFORMED in codes


def test_cluster_naming_unknown_gh_id_is_malformed() -> None:
    req = _req("C_1")
    out = _out(ClusterResult(cluster_id="c-1", item_gh_ids=["C_1", "GHOST"], rationale="r"))
    codes = [v.code for v in audit_cluster(req, out)]
    assert ErrorCode.CONTRACT_CLUSTER_MALFORMED in codes


@pytest.mark.parametrize("rationale", ["", "   ", "\t\n"])
def test_empty_or_whitespace_rationale_is_malformed(rationale: str) -> None:
    req = _req("C_1")
    out = _out(ClusterResult(cluster_id="c-1", item_gh_ids=["C_1"], rationale=rationale))
    codes = [v.code for v in audit_cluster(req, out)]
    assert ErrorCode.CONTRACT_CLUSTER_MALFORMED in codes


def test_violation_detail_is_present_for_each_breach() -> None:
    # Each violation must carry a public-safe detail (becomes rationale/reason).
    req = _req("C_1", "C_2")
    out = _out(ClusterResult(cluster_id="c-1", item_gh_ids=["C_1"], rationale="r"))
    violations = audit_cluster(req, out)
    assert violations
    assert all(v.detail for v in violations)
