"""Tests for the pure fix-output validator (§5 fix audit guards).

The caller supplies the git-derived sets (``ancestors_of_pre``,
``new_in_cluster``) so these functions are unit-testable without a repo. Each
per-disposition branch and the orphan check is pinned by one focused test.

Reachability is set membership only:
* ``ancestors_of_pre`` — commits reachable from the pre-cluster baseline.
* ``new_in_cluster`` — commits introduced between pre-cluster SHA and post HEAD.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prgroom.agent.contracts import FixInput, FixItemResult, FixOutput
from prgroom.agent.fix_audit import audit_fix_items, audit_orphans
from prgroom.errors import ErrorCode
from prgroom.escalation import Severity
from prgroom.prsession.enums import DispositionKind, ItemKind
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


def _req(*gh_ids: str) -> FixInput:
    return FixInput(
        pr=_REF,
        cluster_id="c-1",
        item_gh_ids=list(gh_ids),
        items=[_item(g) for g in gh_ids],
        pr_detail_path="/d",
        branch_state_path="/b",
        memory_dir="/m",
        response_outbox_dir="/o",
    )


def _row(gh_id: str, kind: DispositionKind, **kw: object) -> FixItemResult:
    return FixItemResult(gh_id=gh_id, disposition=kind, **kw)  # type: ignore[arg-type]


# ───────────────────────── fixed ─────────────────────────


def test_fixed_with_new_commit_is_clean() -> None:
    req = _req("C_1")
    out = FixOutput(
        items=[_row("C_1", DispositionKind.FIXED, commit_shas=["new1"], recommended_gate="full")]
    )
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster={"new1"})
    assert "C_1" not in v


def test_fixed_with_no_commits_is_audit_failed() -> None:
    req = _req("C_1")
    out = FixOutput(items=[_row("C_1", DispositionKind.FIXED, commit_shas=[])])
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster=set())
    assert v["C_1"].code is ErrorCode.CONTRACT_FIX_AUDIT_FAILED


def test_fixed_with_unknown_sha_is_unreachable() -> None:
    req = _req("C_1")
    out = FixOutput(items=[_row("C_1", DispositionKind.FIXED, commit_shas=["ghost"])])
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster={"new1"})
    assert v["C_1"].code is ErrorCode.CONTRACT_FIX_UNREACHABLE_SHA


def test_fixed_claiming_pre_baseline_sha_is_audit_failed() -> None:
    # A `fixed` must be a NEW commit; claiming a pre-baseline ancestor is wrong.
    req = _req("C_1")
    out = FixOutput(items=[_row("C_1", DispositionKind.FIXED, commit_shas=["base"])])
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster={"new1"})
    assert v["C_1"].code is ErrorCode.CONTRACT_FIX_AUDIT_FAILED


def test_fixed_with_empty_gate_is_audit_failed() -> None:
    # §6.1: recommended_gate is load-bearing — a FIXED item must carry a valid tier.
    req = _req("C_1")
    out = FixOutput(items=[_row("C_1", DispositionKind.FIXED, commit_shas=["new1"])])
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster={"new1"})
    assert v["C_1"].code is ErrorCode.CONTRACT_FIX_AUDIT_FAILED
    assert "recommended_gate" in v["C_1"].detail


def test_fixed_with_invalid_gate_is_audit_failed() -> None:
    req = _req("C_1")
    out = FixOutput(
        items=[_row("C_1", DispositionKind.FIXED, commit_shas=["new1"], recommended_gate="banana")]
    )
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster={"new1"})
    assert v["C_1"].code is ErrorCode.CONTRACT_FIX_AUDIT_FAILED


def test_fixed_gate_check_runs_after_sha_checks() -> None:
    # An unreachable sha must keep its richer UNREACHABLE_SHA code even when the
    # gate is also missing — first offending rule wins, shas first.
    req = _req("C_1")
    out = FixOutput(items=[_row("C_1", DispositionKind.FIXED, commit_shas=["ghost"])])
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster={"new1"})
    assert v["C_1"].code is ErrorCode.CONTRACT_FIX_UNREACHABLE_SHA


def test_non_fixed_dispositions_need_no_gate() -> None:
    req = _req("C_1")
    out = FixOutput(items=[_row("C_1", DispositionKind.ALREADY_ADDRESSED, commit_shas=["base"])])
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster=set())
    assert "C_1" not in v


# ───────────────────────── already_addressed ─────────────────────────


def test_already_addressed_with_pre_baseline_sha_is_clean() -> None:
    req = _req("C_1")
    out = FixOutput(items=[_row("C_1", DispositionKind.ALREADY_ADDRESSED, commit_shas=["base"])])
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster=set())
    assert "C_1" not in v


def test_already_addressed_with_unknown_sha_is_unreachable() -> None:
    req = _req("C_1")
    out = FixOutput(items=[_row("C_1", DispositionKind.ALREADY_ADDRESSED, commit_shas=["ghost"])])
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster={"new1"})
    assert v["C_1"].code is ErrorCode.CONTRACT_FIX_UNREACHABLE_SHA


def test_already_addressed_claiming_brand_new_sha_is_audit_failed() -> None:
    req = _req("C_1")
    out = FixOutput(items=[_row("C_1", DispositionKind.ALREADY_ADDRESSED, commit_shas=["new1"])])
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster={"new1"})
    assert v["C_1"].code is ErrorCode.CONTRACT_FIX_AUDIT_FAILED


def test_already_addressed_with_no_commits_is_audit_failed() -> None:
    # §5: commit_shas is REQUIRED for already_addressed (same as fixed). An empty
    # list claims "a prior commit handles it" while naming no commit — malformed.
    req = _req("C_1")
    out = FixOutput(items=[_row("C_1", DispositionKind.ALREADY_ADDRESSED, commit_shas=[])])
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster=set())
    assert v["C_1"].code is ErrorCode.CONTRACT_FIX_AUDIT_FAILED


# ───────────────────────── rationale-only dispositions ─────────────────────────


@pytest.mark.parametrize(
    "kind",
    [
        DispositionKind.SKIPPED,
        DispositionKind.DEFERRED,
        DispositionKind.WONT_FIX,
        DispositionKind.ESCALATED,
        DispositionKind.FAILED,
    ],
)
def test_rationale_disposition_with_text_is_clean(kind: DispositionKind) -> None:
    req = _req("C_1")
    out = FixOutput(items=[_row("C_1", kind, rationale="a reason")])
    v = audit_fix_items(req, out, ancestors_of_pre=set(), new_in_cluster=set())
    assert "C_1" not in v


@pytest.mark.parametrize(
    "kind",
    [
        DispositionKind.SKIPPED,
        DispositionKind.DEFERRED,
        DispositionKind.WONT_FIX,
        DispositionKind.ESCALATED,
        DispositionKind.FAILED,
    ],
)
def test_rationale_disposition_without_text_is_audit_failed(kind: DispositionKind) -> None:
    req = _req("C_1")
    out = FixOutput(items=[_row("C_1", kind, rationale="   ")])
    v = audit_fix_items(req, out, ancestors_of_pre=set(), new_in_cluster=set())
    assert v["C_1"].code is ErrorCode.CONTRACT_FIX_AUDIT_FAILED


def test_violations_are_keyed_by_gh_id_and_carry_that_gh_id() -> None:
    req = _req("C_1", "C_2")
    out = FixOutput(
        items=[
            _row("C_1", DispositionKind.FIXED, commit_shas=[]),
            _row("C_2", DispositionKind.SKIPPED, rationale="ok"),
        ]
    )
    v = audit_fix_items(req, out, ancestors_of_pre=set(), new_in_cluster=set())
    assert set(v) == {"C_1"}
    assert v["C_1"].gh_id == "C_1"


# ───────────────────────── orphans ─────────────────────────


def test_no_orphan_when_every_new_commit_is_claimed() -> None:
    out = FixOutput(
        items=[
            FixItemResult(gh_id="C_1", disposition=DispositionKind.FIXED, commit_shas=["n1"]),
            FixItemResult(gh_id="C_2", disposition=DispositionKind.FIXED, commit_shas=["n2"]),
        ]
    )
    assert audit_orphans(out, new_in_cluster={"n1", "n2"}, requested_gh_ids={"C_1", "C_2"}) is None


def test_unclaimed_new_commit_is_an_orphan_violation() -> None:
    out = FixOutput(
        items=[FixItemResult(gh_id="C_1", disposition=DispositionKind.FIXED, commit_shas=["n1"])]
    )
    v = audit_orphans(out, new_in_cluster={"n1", "n2"}, requested_gh_ids={"C_1"})
    assert v is not None
    assert v.code is ErrorCode.CONTRACT_FIX_ORPHAN_COMMIT
    assert v.gh_id is None  # structural, cluster-level
    assert "n2" in v.detail


def test_no_new_commits_means_no_orphan() -> None:
    out = FixOutput(
        items=[FixItemResult(gh_id="C_1", disposition=DispositionKind.SKIPPED, rationale="x")]
    )
    assert audit_orphans(out, new_in_cluster=set(), requested_gh_ids={"C_1"}) is None


def test_orphan_ignores_commits_claimed_only_by_unrequested_rows() -> None:
    # Security: a GHOST row (gh_id never requested) must not be able to "claim" a
    # new commit and thereby suppress orphan detection (and the hard flip + stash).
    # Only commits claimed by REQUESTED items count toward coverage.
    out = FixOutput(
        items=[
            FixItemResult(gh_id="C_1", disposition=DispositionKind.FIXED, commit_shas=["n1"]),
            FixItemResult(gh_id="GHOST", disposition=DispositionKind.FIXED, commit_shas=["n2"]),
        ]
    )
    v = audit_orphans(out, new_in_cluster={"n1", "n2"}, requested_gh_ids={"C_1"})
    assert v is not None
    assert v.code is ErrorCode.CONTRACT_FIX_ORPHAN_COMMIT
    assert "n2" in v.detail  # the GHOST's claim does not cover it


def test_orphan_violation_is_block_severity() -> None:
    # An orphan triggers a hard cluster flip + git stash; its escalation must be
    # BLOCK so sinks/operators distinguish it from soft audit WARNs (like containment).
    out = FixOutput(
        items=[FixItemResult(gh_id="C_1", disposition=DispositionKind.FIXED, commit_shas=["n1"])]
    )
    v = audit_orphans(out, new_in_cluster={"n1", "n2"}, requested_gh_ids={"C_1"})
    assert v is not None
    assert v.severity is Severity.BLOCK
