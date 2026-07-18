"""``run_cluster`` orchestration — retry-once, then degenerate fallback (§5).

This is the dispatch-orchestration half of the cluster path: it calls the
:class:`~prgroom.agent.contracts.ClusterContract`, audits the output with
:func:`~prgroom.agent.cluster_audit.audit_cluster`, and on failure retries once.
A second failure — whether an audit breach or a both-fail
(:class:`~prgroom.agent.dispatcher.AllProvidersFailedError`) — falls back to
**per-item degenerate clusters**: one cluster per input item, with a cluster id
derived deterministically from the gh_id (``degen-<gh_id>``, no clock/counter).
Degenerate output is coverage-complete by construction, so there is no escaping
the coverage invariant — even a totally-unavailable agent yields a usable
clustering, built directly without any dispatch.

8.7 boundary: this returns a :class:`ClusterRunResult`; it never mutates
``PRGroomingState`` or transitions phases.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from prgroom.agent.cluster_audit import audit_cluster
from prgroom.agent.contracts import ClusterOutput, ClusterResult
from prgroom.agent.dispatcher import AllProvidersFailedError

if TYPE_CHECKING:
    from prgroom.agent.contracts import ClusterContract, ClusterInput

_DEGENERATE_RATIONALE = "degenerate fallback: agent clustering failed twice; one cluster per item"


@dataclass(frozen=True, slots=True)
class ClusterRunResult:
    """The computed result of one ``run_cluster`` call (8.7 returns; 8.15 applies).

    ``assignments`` maps each input ``gh_id`` to its final ``cluster_id``;
    ``degenerate`` records whether the per-item fallback was used; ``attempts``
    counts dispatches (1 clean, 2 retried/fell-back) for telemetry and tests.
    """

    clusters: list[ClusterResult]
    assignments: dict[str, str]
    degenerate: bool
    attempts: int


def _degenerate(req: ClusterInput) -> list[ClusterResult]:
    """One cluster per input item, id derived from the gh_id. Coverage-complete."""
    return [
        ClusterResult(
            cluster_id=f"degen-{item.identity.gh_id}",
            item_gh_ids=[item.identity.gh_id],
            rationale=_DEGENERATE_RATIONALE,
        )
        for item in req.items
    ]


def _assignments(clusters: list[ClusterResult]) -> dict[str, str]:
    return {gh_id: c.cluster_id for c in clusters for gh_id in c.item_gh_ids}


def _result(clusters: list[ClusterResult], *, degenerate: bool, attempts: int) -> ClusterRunResult:
    return ClusterRunResult(
        clusters=clusters,
        assignments=_assignments(clusters),
        degenerate=degenerate,
        attempts=attempts,
    )


def _try_dispatch(req: ClusterInput, dispatcher: ClusterContract) -> ClusterOutput | None:
    """Dispatch + audit once. Returns the output if clean, else ``None``.

    A both-fail (``AllProvidersFailedError``) is treated the same as an audit
    breach: a ``None`` that drives the caller toward retry/fallback.
    """
    try:
        dispatched = dispatcher.cluster(req)
    except AllProvidersFailedError:
        return None
    out = dispatched.output
    return out if not audit_cluster(req, out) else None


def run_cluster(req: ClusterInput, dispatcher: ClusterContract) -> ClusterRunResult:
    """Dispatch → audit → retry-once → degenerate fallback (§5). Pure of state.

    Clustering decides no disposition, so it records no provenance: the
    degenerate path never dispatched, and an audit-rejected dispatch's winner
    is discarded with its output.
    """
    for attempt in (1, 2):
        out = _try_dispatch(req, dispatcher)
        if out is not None:
            return _result(out.clusters, degenerate=False, attempts=attempt)
    return _result(_degenerate(req), degenerate=True, attempts=2)
