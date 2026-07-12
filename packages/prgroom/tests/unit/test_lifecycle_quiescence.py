"""Tests for the §4.1 quiescence predicate, gate identification, and timeouts.

Coded decisions pinned here:

- The four hard gates (G_REVIEWERS / G_CI / G_DISPOSITIONS / G_NO_BLOCKERS) plus
  the idle timer, and that ALL must pass for quiescence.
- ``failing_gate`` names the first unmet gate for the status verb ("why didn't
  it quiesce?").
- ``evaluate_reviewer_timeouts`` auto-declines on start/finish timeout, and —
  critically — derives deadlines from ``now`` per call so a crash gap still
  declines (resumability: a frozen-then-advanced clock yields the same outcome as
  if the process never died).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from prgroom.lifecycle.quiescence import (
    QuiescenceGate,
    evaluate_reviewer_timeouts,
    failing_gate,
    quiescence_predicate,
)
from prgroom.prsession.enums import (
    DispositionKind,
    ItemKind,
    PRPhase,
    ReviewerKind,
    ReviewerStatus,
)
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Disposition,
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewerState,
    ReviewItem,
)

_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_IDLE = timedelta(minutes=10)
_START_TIMEOUT = timedelta(minutes=3)
_FINISH_TIMEOUT = timedelta(minutes=15)


def _reviewer(
    status: ReviewerStatus,
    *,
    required: bool = True,
    last_request_at: datetime = _T0,
    last_review_at: datetime | None = None,
) -> ReviewerState:
    return ReviewerState(
        identity="copilot",
        kind=ReviewerKind.BOT,
        status=status,
        required=required,
        last_request_at=last_request_at,
        last_review_at=last_review_at,
    )


def _dispositioned_item(kind: DispositionKind = DispositionKind.SKIPPED) -> ReviewItem:
    return ReviewItem(
        kind=ItemKind.ISSUE_COMMENT,
        identity=Identity(gh_id="c1"),
        author="copilot",
        body_excerpt="b",
        seen_at=_T0,
        disposition=Disposition(kind=kind, decided_at=_T0, decided_by="agent"),
    )


def _quiescent_state(
    *, ci_state: str = "success", last_activity_at: datetime = _T0
) -> PRGroomingState:
    return PRGroomingState(
        pr=PRRef(owner="octo", repo="demo", number=7),
        phase=PRPhase.AWAITING_REVIEW,
        pr_review_retries_used=1,
        last_polled_at=_T0,
        last_activity_at=last_activity_at,
        quiescence=QuiescenceState(ci_state=ci_state),
        last_pushed_head_sha="sha",
        reviewers={"copilot": _reviewer(ReviewerStatus.REVIEW_FOUND)},
        items=[_dispositioned_item()],
    )


# -- quiescence_predicate happy path ---------------------------------------


def test_quiescence_true_when_all_gates_pass_and_idle_elapsed() -> None:
    state = _quiescent_state()
    now = _T0 + _IDLE
    assert quiescence_predicate(state, now=now, idle_threshold=_IDLE) is True


def test_quiescence_true_with_ci_absent() -> None:
    state = _quiescent_state(ci_state="absent")
    now = _T0 + _IDLE
    assert quiescence_predicate(state, now=now, idle_threshold=_IDLE) is True


@pytest.mark.parametrize("declined_review", [ReviewerStatus.DECLINED, ReviewerStatus.REVIEW_FOUND])
def test_g_reviewers_satisfied_by_review_found_or_declined(
    declined_review: ReviewerStatus,
) -> None:
    state = _quiescent_state()
    state.reviewers["copilot"].status = declined_review
    now = _T0 + _IDLE
    assert quiescence_predicate(state, now=now, idle_threshold=_IDLE) is True


# -- each gate blocks ------------------------------------------------------


def test_g_reviewers_blocks_when_required_reviewer_not_engaged() -> None:
    state = _quiescent_state()
    state.reviewers["copilot"].status = ReviewerStatus.IN_PROGRESS
    now = _T0 + _IDLE
    assert quiescence_predicate(state, now=now, idle_threshold=_IDLE) is False
    assert failing_gate(state, now=now, idle_threshold=_IDLE) is QuiescenceGate.G_REVIEWERS


def test_optional_reviewer_does_not_gate() -> None:
    state = _quiescent_state()
    state.reviewers["human"] = _reviewer(ReviewerStatus.IN_PROGRESS, required=False)
    now = _T0 + _IDLE
    assert quiescence_predicate(state, now=now, idle_threshold=_IDLE) is True


def test_g_ci_blocks_when_pending_or_failure() -> None:
    state = _quiescent_state(ci_state="pending")
    now = _T0 + _IDLE
    assert quiescence_predicate(state, now=now, idle_threshold=_IDLE) is False
    assert failing_gate(state, now=now, idle_threshold=_IDLE) is QuiescenceGate.G_CI


def test_g_dispositions_blocks_when_item_unprocessed() -> None:
    state = _quiescent_state()
    state.items.append(
        ReviewItem(
            kind=ItemKind.ISSUE_COMMENT,
            identity=Identity(gh_id="c2"),
            author="copilot",
            body_excerpt="b",
            seen_at=_T0,
        )
    )
    now = _T0 + _IDLE
    assert quiescence_predicate(state, now=now, idle_threshold=_IDLE) is False
    assert failing_gate(state, now=now, idle_threshold=_IDLE) is QuiescenceGate.G_DISPOSITIONS


@pytest.mark.parametrize("blocker", [DispositionKind.ESCALATED, DispositionKind.FAILED])
def test_g_no_blockers_blocks_on_escalated_or_failed(blocker: DispositionKind) -> None:
    state = _quiescent_state()
    state.items.append(_dispositioned_item(kind=blocker))
    now = _T0 + _IDLE
    assert quiescence_predicate(state, now=now, idle_threshold=_IDLE) is False
    assert failing_gate(state, now=now, idle_threshold=_IDLE) is QuiescenceGate.G_NO_BLOCKERS


def test_idle_timer_blocks_when_too_recent() -> None:
    state = _quiescent_state()
    now = _T0 + _IDLE - timedelta(seconds=1)
    assert quiescence_predicate(state, now=now, idle_threshold=_IDLE) is False
    assert failing_gate(state, now=now, idle_threshold=_IDLE) is QuiescenceGate.G_IDLE_TIMER


def test_failing_gate_is_none_when_quiescent() -> None:
    state = _quiescent_state()
    now = _T0 + _IDLE
    assert failing_gate(state, now=now, idle_threshold=_IDLE) is None


def test_failing_gate_priority_reviewers_before_ci() -> None:
    # When both G_REVIEWERS and G_CI fail, the earlier-listed gate is named first.
    state = _quiescent_state(ci_state="failure")
    state.reviewers["copilot"].status = ReviewerStatus.IN_PROGRESS
    now = _T0 + _IDLE
    assert failing_gate(state, now=now, idle_threshold=_IDLE) is QuiescenceGate.G_REVIEWERS


# -- evaluate_reviewer_timeouts (auto-decline) -----------------------------


def test_no_start_timeout_declines_silent_reviewer() -> None:
    state = _quiescent_state()
    state.reviewers["copilot"] = _reviewer(ReviewerStatus.REQUESTED, last_request_at=_T0)
    now = _T0 + _START_TIMEOUT + timedelta(seconds=1)
    evaluate_reviewer_timeouts(
        state,
        now=now,
        review_start_timeout=_START_TIMEOUT,
        review_finish_timeout=_FINISH_TIMEOUT,
    )
    r = state.reviewers["copilot"]
    assert r.status == ReviewerStatus.DECLINED
    assert r.declined_reason == "timeout-no-start"
    assert r.declined_at == now


def test_no_start_timeout_keeps_requested_within_deadline() -> None:
    state = _quiescent_state()
    state.reviewers["copilot"] = _reviewer(ReviewerStatus.REQUESTED, last_request_at=_T0)
    now = _T0 + _START_TIMEOUT - timedelta(seconds=1)
    evaluate_reviewer_timeouts(
        state,
        now=now,
        review_start_timeout=_START_TIMEOUT,
        review_finish_timeout=_FINISH_TIMEOUT,
    )
    assert state.reviewers["copilot"].status == ReviewerStatus.REQUESTED


def test_finish_timeout_declines_stalled_reviewer() -> None:
    state = _quiescent_state()
    state.reviewers["copilot"] = _reviewer(
        ReviewerStatus.IN_PROGRESS, last_request_at=_T0, last_review_at=_T0
    )
    now = _T0 + _FINISH_TIMEOUT + timedelta(seconds=1)
    evaluate_reviewer_timeouts(
        state,
        now=now,
        review_start_timeout=_START_TIMEOUT,
        review_finish_timeout=_FINISH_TIMEOUT,
    )
    r = state.reviewers["copilot"]
    assert r.status == ReviewerStatus.DECLINED
    assert r.declined_reason == "timeout-stalled"


def test_timeouts_resumable_across_a_crash_gap() -> None:
    # Resumability invariant (§4.1): deadlines are DERIVED per call from `now`,
    # never stored. A reviewer requested at T0, evaluated only once much later
    # (process died and was re-invoked after the gap), still auto-declines —
    # the same outcome as if the process had polled continuously.
    state = _quiescent_state()
    state.reviewers["copilot"] = _reviewer(ReviewerStatus.REQUESTED, last_request_at=_T0)
    after_long_gap = _T0 + timedelta(hours=6)  # crash gap dwarfs the 3m start timeout
    evaluate_reviewer_timeouts(
        state,
        now=after_long_gap,
        review_start_timeout=_START_TIMEOUT,
        review_finish_timeout=_FINISH_TIMEOUT,
    )
    assert state.reviewers["copilot"].status == ReviewerStatus.DECLINED
    assert state.reviewers["copilot"].declined_reason == "timeout-no-start"
