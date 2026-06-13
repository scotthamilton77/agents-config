"""Audit-result value type + the violation→effect helpers (§8.6).

8.7 is the pure audit + dispatch-orchestration layer: it *computes* what the
lifecycle (8.15) will later *apply*. An :class:`AuditViolation` is the unit of
that computation — one contract-invariant breach, carrying its registry code, a
public-safe detail, the item it flips to ``failed`` (or ``None`` for a
structural/cluster-level breach), and the escalation severity.

The two helpers turn a violation into the value objects the lifecycle applies —
a FAILED :class:`~prgroom.prsession.state.Disposition` and an
:class:`~prgroom.escalation.Escalation`. They never mutate
:class:`~prgroom.prsession.state.PRGroomingState` and never call ``Sink.emit``;
those effects are the lifecycle's (a later bead).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from prgroom.escalation import Escalation, Severity
from prgroom.prsession.enums import DispositionKind
from prgroom.prsession.state import Disposition

if TYPE_CHECKING:
    from datetime import datetime

    from prgroom.errors import ErrorCode
    from prgroom.prsession.pr_ref import PRRef
    from prgroom.prsession.state import ReviewItem


@dataclass(frozen=True, slots=True)
class AuditViolation:
    """One contract-invariant breach found by an audit (§8.6).

    ``gh_id is None`` marks a structural/cluster-level breach (e.g. an orphan
    commit) that has no single owning item; the caller decides which items it
    flips. A containment breach is security-relevant and rides at
    :attr:`Severity.BLOCK`; everything else defaults to :attr:`Severity.WARN`.
    """

    code: ErrorCode
    detail: str
    gh_id: str | None = None
    severity: Severity = Severity.WARN


def failed_disposition(v: AuditViolation, *, now: datetime, decided_by: str) -> Disposition:
    """Build the FAILED :class:`Disposition` a violation produces (§8.6).

    The violation ``detail`` becomes the disposition rationale (the cause the
    end-of-cycle resolver reads when it promotes a FAILED item to
    ``human-gated``); ``now`` is the injected clock reading.
    """
    return Disposition(
        kind=DispositionKind.FAILED, decided_at=now, decided_by=decided_by, rationale=v.detail
    )


def escalation_for(v: AuditViolation, *, pr: PRRef, item: ReviewItem | None = None) -> Escalation:
    """Build the :class:`Escalation` a violation produces (§8.6).

    The violation ``detail`` becomes the escalation reason and its ``severity``
    rides through. The caller supplies the triggering ``item`` when one applies.
    """
    return Escalation(pr=pr, reason=v.detail, severity=v.severity, item=item)


def provider_failure_disposition(detail: str, *, now: datetime, decided_by: str) -> Disposition:
    """Build the FAILED :class:`Disposition` for a both-fail (§5 both-fail).

    An ``AllProvidersFailedError`` is not an audit violation, but the lifecycle
    treats it identically: FAILED + escalation. The error ``detail`` (which names
    every provider link that was tried) becomes the rationale.
    """
    return Disposition(
        kind=DispositionKind.FAILED, decided_at=now, decided_by=decided_by, rationale=detail
    )
