"""Tests for the audit-result value type + the violation→effect helpers (§8.6).

8.7 *computes*; it never mutates state. So these helpers turn an
:class:`AuditViolation` into the two value objects the lifecycle (8.15) will
apply — a FAILED :class:`Disposition` and an :class:`Escalation` — without
touching ``PRGroomingState`` or calling ``Sink.emit``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from prgroom.agent.errors import (
    AuditViolation,
    escalation_for,
    failed_disposition,
    provider_failure_disposition,
)
from prgroom.errors import ErrorCode
from prgroom.escalation import Severity
from prgroom.prsession.enums import DispositionKind, ItemKind
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


def test_audit_violation_defaults_severity_warn_and_no_gh_id() -> None:
    v = AuditViolation(code=ErrorCode.CONTRACT_CLUSTER_MALFORMED, detail="dup id 'c-1'")
    assert v.severity is Severity.WARN
    assert v.gh_id is None


def test_failed_disposition_carries_detail_as_rationale() -> None:
    v = AuditViolation(
        code=ErrorCode.CONTRACT_FIX_AUDIT_FAILED, detail="no commits for fixed", gh_id="C_1"
    )
    d = failed_disposition(v, now=_NOW, decided_by="prgroom")
    assert d.kind is DispositionKind.FAILED
    assert d.decided_at == _NOW
    assert d.decided_by == "prgroom"
    assert d.rationale == "no commits for fixed"


def test_escalation_for_carries_detail_severity_and_item() -> None:
    item = _item("C_1")
    v = AuditViolation(
        code=ErrorCode.CONTRACT_FIX_ORPHAN_COMMIT,
        detail="orphan commit deadbeef",
        severity=Severity.BLOCK,
    )
    esc = escalation_for(v, pr=_REF, item=item)
    assert esc.pr is _REF
    assert esc.reason == "orphan commit deadbeef"
    assert esc.severity is Severity.BLOCK
    assert esc.item is item


def test_escalation_for_defaults_item_none() -> None:
    v = AuditViolation(code=ErrorCode.CONTRACT_CLUSTER_COVERAGE, detail="missing C_2")
    esc = escalation_for(v, pr=_REF)
    assert esc.item is None
    assert esc.severity is Severity.WARN


def test_provider_failure_disposition_is_failed_with_error_detail() -> None:
    # A both-fail (AllProvidersFailedError) is NOT an audit violation, but the
    # lifecycle treats it identically: FAILED + escalation. The error detail
    # becomes the rationale.
    d = provider_failure_disposition(
        "all providers failed: ollama, haiku", now=_NOW, decided_by="prgroom"
    )
    assert d.kind is DispositionKind.FAILED
    assert d.rationale == "all providers failed: ollama, haiku"
    assert d.decided_at == _NOW
    assert d.decided_by == "prgroom"
