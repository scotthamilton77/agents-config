"""Quiescence decision — hard gates + idle timer (§4.1).

``quiescence_predicate`` answers "is this PR done enough to rest at ``quiesced``?"
as the conjunction of four binary hard gates and a soft idle buffer. The gates are
operator-debuggable: ``failing_gate`` names the first unmet one so ``prgroom
status`` can answer "why didn't it quiesce?".

``evaluate_reviewer_timeouts`` is the ``_poll``-time auto-decline logic. Per the
§4.1 resumability invariant, timeout deadlines are **derived per evaluation** from
the injected ``now`` and never stored — so a reviewer whose deadline elapsed during
a crash gap still auto-declines on the next poll, identical to the no-crash path.

The clock arrives as an explicit ``now`` argument (the run-loop passes
``deps.clock.now()``); these functions reach for no stdlib singleton, keeping them
deterministic under test.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from prgroom.prsession.enums import DispositionKind, ReviewerStatus
from prgroom.prsession.state import PRGroomingState, ReviewerState

# CI states that satisfy G_CI (§4.1): a green build, or no CI configured at all.
_CI_OK: frozenset[str] = frozenset({"success", "absent"})
# Reviewer statuses that satisfy G_REVIEWERS for a required reviewer (§4.1).
_REVIEWER_DONE: frozenset[ReviewerStatus] = frozenset(
    {ReviewerStatus.REVIEW_FOUND, ReviewerStatus.DECLINED}
)
# Dispositions that block quiescence — they route to human-gated before this
# predicate is reached, so reaching them here is a defensive sanity gate (§4.1).
_BLOCKER_DISPOSITIONS: frozenset[DispositionKind] = frozenset(
    {DispositionKind.ESCALATED, DispositionKind.FAILED}
)


class QuiescenceGate(StrEnum):
    """The named quiescence gates, in evaluation order (§4.1).

    The ``.value`` is the operator-facing label surfaced by ``prgroom status`` to
    answer "why didn't it quiesce?".
    """

    G_REVIEWERS = "reviewers"
    G_CI = "ci"
    G_DISPOSITIONS = "dispositions"
    G_NO_BLOCKERS = "no_blockers"
    G_IDLE_TIMER = "idle_timer"


def _g_reviewers(state: PRGroomingState) -> bool:
    return all(r.status in _REVIEWER_DONE for r in state.reviewers.values() if r.required)


def _g_ci(state: PRGroomingState) -> bool:
    return state.quiescence.ci_state in _CI_OK


def _g_dispositions(state: PRGroomingState) -> bool:
    return all(item.disposition is not None for item in state.items)


def _g_no_blockers(state: PRGroomingState) -> bool:
    return not any(
        item.disposition is not None and item.disposition.kind in _BLOCKER_DISPOSITIONS
        for item in state.items
    )


def _g_idle(state: PRGroomingState, *, now: datetime, idle_threshold: timedelta) -> bool:
    return now - state.last_activity_at >= idle_threshold


def failing_gate(
    state: PRGroomingState, *, now: datetime, idle_threshold: timedelta
) -> QuiescenceGate | None:
    """The first unmet quiescence gate, or ``None`` if the PR is quiescent (§4.1).

    Gates are checked in :class:`QuiescenceGate` declaration order so the operator
    sees the most-fundamental blocker first (reviewers before CI before idle).
    """
    if not _g_reviewers(state):
        return QuiescenceGate.G_REVIEWERS
    if not _g_ci(state):
        return QuiescenceGate.G_CI
    if not _g_dispositions(state):
        return QuiescenceGate.G_DISPOSITIONS
    if not _g_no_blockers(state):
        return QuiescenceGate.G_NO_BLOCKERS
    if not _g_idle(state, now=now, idle_threshold=idle_threshold):
        return QuiescenceGate.G_IDLE_TIMER
    return None


def quiescence_predicate(
    state: PRGroomingState, *, now: datetime, idle_threshold: timedelta
) -> bool:
    """True iff every hard gate passes AND the idle timer has elapsed (§4.1)."""
    return failing_gate(state, now=now, idle_threshold=idle_threshold) is None


def evaluate_reviewer_timeouts(
    state: PRGroomingState,
    *,
    now: datetime,
    review_start_timeout: timedelta,
    review_finish_timeout: timedelta,
) -> None:
    """Auto-decline reviewers past their start/finish timeout (§4.1, ``_poll`` add-on).

    Mutates ``state.reviewers`` in place. Deadlines are derived from ``now`` on every
    call (never stored), so elapsed time across a crash gap counts and the outcome
    matches an uninterrupted poll. ``declined_reason`` records which timeout fired so
    the operator can tell silence (``timeout-no-start`` / ``timeout-stalled``) from an
    explicit pass (``user-declined``, set elsewhere).
    """
    for r in state.reviewers.values():
        no_start = (
            r.status == ReviewerStatus.REQUESTED
            and r.last_review_at is None
            and now - r.last_request_at > review_start_timeout
        )
        stalled = (
            r.status == ReviewerStatus.IN_PROGRESS
            and r.last_review_at is not None
            and now - r.last_review_at > review_finish_timeout
        )
        if no_start:
            _decline(r, now=now, reason="timeout-no-start")
        elif stalled:
            _decline(r, now=now, reason="timeout-stalled")


def _decline(reviewer: ReviewerState, *, now: datetime, reason: str) -> None:
    reviewer.status = ReviewerStatus.DECLINED
    reviewer.declined_at = now
    reviewer.declined_reason = reason
