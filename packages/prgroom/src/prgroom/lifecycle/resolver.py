"""End-of-cycle phase resolution — the §3.2 six-priority cascade.

``resolve_end_of_cycle_phase`` decides the next phase for a ``fixes-pending`` state
after a full cycle. It is a **pure** first-match-wins cascade: the highest-priority
condition that holds decides, and lower priorities are not consulted. The run-loop
applies the returned :class:`ResolvedPhase` (phase + optional ``last_error`` +
optional ``quiesced_at``) to state.

The two effectful inputs — whether a cap-tripping push is queued (a git read,
§3.4) and whether the §4.1 quiescence predicate is satisfied — are passed in as
booleans by the run-loop, keeping this function gh/git/clock-free. ``now`` is used
only to stamp ``quiesced_at`` on the priority-5 transition.

Priority order (first match wins):

1. Pre-push retry budget (pr_review_retries_used ≥ pr_review_retries AND queued
   commits) → ``human-gated`` + ``LIFECYCLE_PR_REVIEW_EXHAUSTED``. The
   budget-tripping push is refused, never uploaded.
2. Any ``FAILED`` item → ``human-gated`` (cause is per-item ``rationale``; resolver
   does NOT set ``last_error`` — that is reserved for the ``PROPAGATE`` error path).
3. Any unresolved ``ESCALATED`` item → ``human-gated``.
4. ≥1 commit pushed this cycle → ``awaiting-review``.
5. Zero push AND quiescence trips → ``quiesced`` (stamps ``quiesced_at``).
6. Otherwise → ``awaiting-review``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from prgroom.errors import ErrorCode
from prgroom.prsession.enums import DispositionKind, PRPhase
from prgroom.prsession.state import PRGroomingState


@dataclass(frozen=True, slots=True)
class ResolvedPhase:
    """The resolver's verdict — the run-loop applies all three fields to state.

    ``last_error`` is the budget code on priority 1 and ``None`` everywhere else (a
    ``FAILED`` item's cause lives in its per-item ``rationale``, not here). ``quiesced_at``
    is set only on the priority-5 quiesced transition.
    """

    phase: PRPhase
    last_error: str | None = None
    quiesced_at: datetime | None = None


def retry_budget_exhausted(state: PRGroomingState, pr_review_retries: int) -> bool:
    """The §3.5 budget-trip core: the counter has consumed the whole retry budget.

    Pure and cheap — callers AND it with their own ``has_queued`` reading (an
    effectful git/gh read), checking this predicate FIRST so an untripped budget
    short-circuits the read. Single owner of the ``>=`` comparison so the guard,
    the terminal-entry re-arm, and the end-of-cycle cascade cannot drift.
    """
    return state.pr_review_retries_used >= pr_review_retries


def apply_retry_budget_gate(state: PRGroomingState) -> None:
    """Gate a budget-tripping push to ``human-gated`` (§3.5) — the shared refusal.

    Sets ``LIFECYCLE_PR_REVIEW_EXHAUSTED`` and clears ``lifecycle_escalation_filed``
    so the run loop-top flush fires exactly one Sink event. Single owner of the
    refusal mutation: the run pipeline's cap-guard and the direct ``push`` CLI verb
    both apply it, so neither path can publish a push the other would refuse.
    """
    state.phase = PRPhase.HUMAN_GATED
    state.last_error = ErrorCode.LIFECYCLE_PR_REVIEW_EXHAUSTED.value
    state.lifecycle_escalation_filed = False


def _has_disposition_kind(state: PRGroomingState, kind: DispositionKind) -> bool:
    return any(
        item.disposition is not None and item.disposition.kind == kind for item in state.items
    )


def resolve_end_of_cycle_phase(
    state: PRGroomingState,
    *,
    now: datetime,
    pr_review_retries: int,
    has_queued_commits: bool,
    pushed_this_cycle: bool,
    quiescent: bool,
) -> ResolvedPhase:
    """Resolve the next phase from ``fixes-pending`` via the §3.2 cascade.

    First-match-wins: see the module docstring for the priority list.
    ``state.pr_review_retries_used`` and ``state.items`` are read but not mutated;
    the run-loop applies the result.
    """
    # Priority 1 — pre-push retry budget (§3.5). Checked before the push so the
    # budget-tripping commit is refused rather than uploaded.
    if has_queued_commits and retry_budget_exhausted(state, pr_review_retries):
        return ResolvedPhase(
            phase=PRPhase.HUMAN_GATED,
            last_error=ErrorCode.LIFECYCLE_PR_REVIEW_EXHAUSTED.value,
        )
    # Priority 2 — any FAILED item (any cause). Cause is per-item rationale.
    if _has_disposition_kind(state, DispositionKind.FAILED):
        return ResolvedPhase(phase=PRPhase.HUMAN_GATED)
    # Priority 3 — any unresolved ESCALATED item.
    if _has_disposition_kind(state, DispositionKind.ESCALATED):
        return ResolvedPhase(phase=PRPhase.HUMAN_GATED)
    # Priority 4 — ≥1 commit pushed this cycle: back to awaiting-review for re-review.
    if pushed_this_cycle:
        return ResolvedPhase(phase=PRPhase.AWAITING_REVIEW)
    # Priority 5 — zero push AND quiescence trips: rest at quiesced.
    if quiescent:
        return ResolvedPhase(phase=PRPhase.QUIESCED, quiesced_at=now)
    # Priority 6 — no push, not yet quiescent: keep waiting.
    return ResolvedPhase(phase=PRPhase.AWAITING_REVIEW)
