"""Pure cluster-output validator (§5 audit guards).

:func:`audit_cluster` checks the four §5 cluster invariants and returns one
:class:`~prgroom.agent.errors.AuditViolation` per breach (``[]`` when clean). It
is pure — no I/O, no clock, no state — so the orchestration layer
(:mod:`prgroom.agent.cluster`) can decide what to do with the result (retry,
degenerate fallback) without the audit knowing about effects.

The four invariants (§5):

#. **Total coverage / exclusivity** — every input ``item.identity.gh_id`` appears
   in exactly one cluster. Missing → ``CONTRACT_CLUSTER_COVERAGE``; appearing in
   two clusters is an exclusivity break, also ``CONTRACT_CLUSTER_COVERAGE``.
#. **Unique cluster ids** — a duplicate id → ``CONTRACT_CLUSTER_MALFORMED``.
#. **No unknown items** — a cluster naming a gh_id absent from the input →
   ``CONTRACT_CLUSTER_MALFORMED``.
#. **Non-empty rationale** — an empty/whitespace per-cluster rationale →
   ``CONTRACT_CLUSTER_MALFORMED``.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from prgroom.agent.errors import AuditViolation
from prgroom.errors import ErrorCode

if TYPE_CHECKING:
    from prgroom.agent.contracts import ClusterInput, ClusterOutput


def audit_cluster(req: ClusterInput, out: ClusterOutput) -> list[AuditViolation]:
    """Validate a cluster output against the §5 invariants. Pure; ``[]`` when clean."""
    violations: list[AuditViolation] = []
    input_ids = {item.identity.gh_id for item in req.items}

    _check_cluster_ids_unique(out, violations)
    _check_clusters_well_formed(out, input_ids, violations)
    _check_coverage(out, input_ids, violations)

    return violations


def _check_cluster_ids_unique(out: ClusterOutput, violations: list[AuditViolation]) -> None:
    counts = Counter(c.cluster_id for c in out.clusters)
    for cluster_id, count in counts.items():
        if count > 1:
            violations.append(
                AuditViolation(
                    code=ErrorCode.CONTRACT_CLUSTER_MALFORMED,
                    detail=f"duplicate cluster id {cluster_id!r} ({count} clusters)",
                )
            )


def _check_clusters_well_formed(
    out: ClusterOutput, input_ids: set[str], violations: list[AuditViolation]
) -> None:
    for cluster in out.clusters:
        if not cluster.rationale.strip():
            violations.append(
                AuditViolation(
                    code=ErrorCode.CONTRACT_CLUSTER_MALFORMED,
                    detail=f"cluster {cluster.cluster_id!r} has an empty rationale",
                )
            )
        unknown = [gh_id for gh_id in cluster.item_gh_ids if gh_id not in input_ids]
        if unknown:
            violations.append(
                AuditViolation(
                    code=ErrorCode.CONTRACT_CLUSTER_MALFORMED,
                    detail=f"cluster {cluster.cluster_id!r} names unknown items {unknown}",
                )
            )


def _check_coverage(
    out: ClusterOutput, input_ids: set[str], violations: list[AuditViolation]
) -> None:
    assignment_counts = Counter(gh_id for cluster in out.clusters for gh_id in cluster.item_gh_ids)
    missing = sorted(input_ids - set(assignment_counts))
    if missing:
        violations.append(
            AuditViolation(
                code=ErrorCode.CONTRACT_CLUSTER_COVERAGE,
                detail=f"items not assigned to any cluster: {missing}",
            )
        )
    duplicated = sorted(
        gh_id for gh_id, count in assignment_counts.items() if gh_id in input_ids and count > 1
    )
    if duplicated:
        violations.append(
            AuditViolation(
                code=ErrorCode.CONTRACT_CLUSTER_COVERAGE,
                detail=f"items assigned to more than one cluster: {duplicated}",
            )
        )
