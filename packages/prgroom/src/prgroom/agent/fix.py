"""``run_fix`` orchestration — assemble → dispatch → parse → audit → stash (§5, §8.6).

This is the heavy half of the agent layer and the sharpest expression of the 8.7
boundary: **8.7 computes; the lifecycle (8.15) applies.** ``run_fix`` reads git
through the injected :class:`~prgroom.git.client.GitClient`, runs the three pure
audits (:func:`~prgroom.agent.fix_audit.audit_fix_items`,
:func:`~prgroom.agent.fix_audit.audit_orphans`,
:func:`~prgroom.agent.memory_audit.audit_memory`), builds the per-item
:class:`~prgroom.prsession.state.Disposition` objects and the list of
:class:`~prgroom.escalation.Escalation` objects, and performs the ``git stash``
isolation effect. It returns a :class:`FixRunResult`.

It does NOT: mutate ``PRGroomingState`` / ``ReviewItem`` (it is never passed one),
call ``Sink.emit``, transition phases, set ``state.last_error``, assemble the PR
snapshot, or read ``gh``. Audit failures surface as per-item
``disposition.kind = FAILED``; the end-of-cycle resolver already promotes any
FAILED item to ``human-gated``, so this layer never duplicates that.

Containment vs orphan are both **hard cluster-flipping** violations: either one
flips every item in the cluster to FAILED and triggers exactly one ``git stash``
to preserve the contamination for inspection. A merely per-item audit failure
(e.g. a ``fixed`` with no commits) that added no orphan commits flips only that
item and does NOT stash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from prgroom.agent.dispatcher import AllProvidersFailedError
from prgroom.agent.errors import (
    AuditViolation,
    escalation_for,
    failed_disposition,
    provider_failure_disposition,
)
from prgroom.agent.fix_audit import audit_fix_items, audit_orphans
from prgroom.agent.memory_audit import audit_memory
from prgroom.errors import ErrorCode
from prgroom.escalation import Escalation, Severity
from prgroom.prsession.state import Disposition

if TYPE_CHECKING:
    from datetime import datetime

    from prgroom.agent.contracts import FixContract, FixInput, FixItemResult, FixOutput, MemoryEntry
    from prgroom.git.client import GitClient
    from prgroom.prsession.pr_ref import PRRef
    from prgroom.prsession.state import ReviewItem

# A both-fail escalation is a WARN: the un-dispositioned items are restart-safe and
# the scheduler retries on the next cadence (see AllProvidersFailedError's tier).
_BOTH_FAIL_SEVERITY = Severity.WARN


@dataclass(frozen=True, slots=True)
class FixRunResult:
    """The computed result of one ``run_fix`` call (8.7 returns; 8.15 applies).

    ``dispositions`` has one entry per gh_id in the cluster; ``escalations`` are
    the events the lifecycle will emit; ``stashed`` records whether the isolation
    effect fired; ``deferred_memory`` are accepted non-CONTEXTUAL entries the
    repo-wide router will later home; ``unwritten`` are declared-but-unwritten
    memory paths — a SOFT warning the lifecycle logs (not an escalation). Logging
    is an *effect*, so it stays on the 8.15 side of the boundary; 8.7 only carries
    the data. In the MVP (declared==written) this is always empty.
    """

    dispositions: dict[str, Disposition]
    escalations: list[Escalation]
    stashed: bool
    deferred_memory: list[MemoryEntry] = field(default_factory=list)
    unwritten: list[str] = field(default_factory=list)


def run_fix(
    req: FixInput,
    dispatcher: FixContract,
    git: GitClient,
    *,
    now: datetime,
    decided_by: str,
    known_thread_ids: set[str] | None = None,
) -> FixRunResult:
    """Dispatch the fix contract, audit the output, and isolate contamination.

    On ``AllProvidersFailedError`` (both-fail): every cluster item → FAILED +
    escalation, no stash (nothing was produced). Otherwise: read the pre/post
    HEADs, compute the commit sets, run the audits, and build dispositions.
    """
    pre = git.head_sha()
    try:
        out = dispatcher.fix(req)
    except AllProvidersFailedError as exc:
        return _both_fail_result(req, exc, now=now, decided_by=decided_by)

    post = git.head_sha()
    ancestors_of_pre = set(git.rev_list(pre))
    new_in_cluster = set(git.rev_list(f"{pre}..{post}"))

    item_violations = audit_fix_items(
        req, out, ancestors_of_pre=ancestors_of_pre, new_in_cluster=new_in_cluster
    )
    orphan = audit_orphans(out, new_in_cluster=new_in_cluster)
    memory = audit_memory(
        out,
        memory_dir=req.memory_dir,
        written_paths=set(out.memory_writes),
        known_thread_ids=_resolve_thread_ids(req, known_thread_ids),
    )

    # MVP passes ``written_paths = declared`` to the memory audit, so
    # ``memory.unwritten`` is empty by construction here (no false soft-warnings).
    # The pure audit still computes it for a future caller that stats the dir; the
    # data rides on the result for 8.15 to log (logging is an effect — 8.15's job).
    return _build_result(
        req,
        out,
        git,
        now=now,
        decided_by=decided_by,
        item_violations=item_violations,
        orphan=orphan,
        memory_violations=memory.violations,
        deferred_memory=memory.deferred,
        unwritten=memory.unwritten,
    )


def _resolve_thread_ids(req: FixInput, known_thread_ids: set[str] | None) -> set[str]:
    if known_thread_ids is not None:
        return known_thread_ids
    return {it.identity.thread_id for it in req.items if it.identity.thread_id}


def _items_by_gh(req: FixInput) -> dict[str, ReviewItem]:
    return {it.identity.gh_id: it for it in req.items}


def _both_fail_result(
    req: FixInput, exc: AllProvidersFailedError, *, now: datetime, decided_by: str
) -> FixRunResult:
    by_gh = _items_by_gh(req)
    dispositions = {
        gh_id: provider_failure_disposition(exc.detail, now=now, decided_by=decided_by)
        for gh_id in req.item_gh_ids
    }
    escalations = [
        Escalation(
            pr=req.pr, reason=exc.detail, severity=_BOTH_FAIL_SEVERITY, item=by_gh.get(gh_id)
        )
        for gh_id in req.item_gh_ids
    ]
    return FixRunResult(dispositions=dispositions, escalations=escalations, stashed=False)


def _build_result(
    req: FixInput,
    out: FixOutput,
    git: GitClient,
    *,
    now: datetime,
    decided_by: str,
    item_violations: dict[str, AuditViolation],
    orphan: AuditViolation | None,
    memory_violations: list[AuditViolation],
    deferred_memory: list[MemoryEntry],
    unwritten: list[str],
) -> FixRunResult:
    by_gh = _items_by_gh(req)
    cluster_flip = orphan is not None or bool(memory_violations)

    dispositions: dict[str, Disposition] = {}
    escalations: list[Escalation] = []
    for row in out.items:
        disposition, escalation = _disposition_for_item(
            row,
            item=by_gh.get(row.gh_id),
            pr=req.pr,
            now=now,
            decided_by=decided_by,
            per_item_violation=item_violations.get(row.gh_id),
            cluster_flip=cluster_flip,
        )
        dispositions[row.gh_id] = disposition
        if escalation is not None:
            escalations.append(escalation)

    escalations.extend(_cluster_escalations(orphan, memory_violations, pr=req.pr))

    if cluster_flip:
        git.stash()

    return FixRunResult(
        dispositions=dispositions,
        escalations=escalations,
        stashed=cluster_flip,
        deferred_memory=deferred_memory,
        unwritten=unwritten,
    )


def _disposition_for_item(
    row: FixItemResult,
    *,
    item: ReviewItem | None,
    pr: PRRef,
    now: datetime,
    decided_by: str,
    per_item_violation: AuditViolation | None,
    cluster_flip: bool,
) -> tuple[Disposition, Escalation | None]:
    """Map one fix row to its disposition (+ escalation if it fails).

    Precedence: a cluster-wide hard violation (orphan/containment) flips every
    item; otherwise a per-item audit violation flips just this one; otherwise the
    agent's disposition maps straight through.
    """
    violation = per_item_violation
    if cluster_flip and violation is None:
        violation = _cluster_flip_marker(row)

    if violation is not None:
        disposition = failed_disposition(violation, now=now, decided_by=decided_by)
        return disposition, escalation_for(violation, pr=pr, item=item)

    return _clean_disposition(row, now=now, decided_by=decided_by), None


def _cluster_flip_marker(row: FixItemResult) -> AuditViolation:
    """A FAILED marker for an otherwise-clean item swept up by a cluster-wide breach."""
    return AuditViolation(
        code=ErrorCode.CONTRACT_FIX_AUDIT_FAILED,
        detail="cluster failed by a structural/containment violation",
        gh_id=row.gh_id,
    )


def _clean_disposition(row: FixItemResult, *, now: datetime, decided_by: str) -> Disposition:
    return Disposition(
        kind=row.disposition,
        decided_at=now,
        decided_by=decided_by,
        rationale=row.rationale,
        commits=list(row.commit_shas),
        response_path=row.response_path,
        gate=row.recommended_gate,
    )


def _cluster_escalations(
    orphan: AuditViolation | None, memory_violations: list[AuditViolation], *, pr: PRRef
) -> list[Escalation]:
    out: list[Escalation] = []
    if orphan is not None:
        out.append(escalation_for(orphan, pr=pr))
    out.extend(escalation_for(v, pr=pr) for v in memory_violations)
    return out
