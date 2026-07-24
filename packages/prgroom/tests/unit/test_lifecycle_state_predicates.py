"""Tests for the §3.4 pure state predicates and the shared reviewer-flip.

These pin coded decisions the §3.3 run-loop and the resolver depend on:

- ``has_required_reviewers_to_refresh`` — which reviewer statuses re-arm rereview.
- ``push_uploaded_commits_this_cycle`` — "did THIS cycle's _push upload commits?",
  computed by comparing the live pushed-SHA to the cycle-start snapshot.
- ``new_lifecycle_gate_this_cycle`` — one Sink event per fresh gate, by comparing
  the live ``last_error`` to the prior-cycle value.
- ``flip_stale_required_reviews`` — the shared SHA-invalidation flip that both
  ``_push`` and ``_poll``'s external-push branch apply (§3.4).

``has_queued_fix_commits`` is intentionally NOT here: §3.4 forbids a state field
for the commit queue, so the queued-commits signal is an effectful git read the
run-loop bead supplies as a bool to the resolver. The pure spine never computes it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from prgroom.lifecycle.predicates import (
    WITHDRAWN_REASON,
    flip_stale_required_reviews,
    has_required_reviewers_to_refresh,
    new_lifecycle_gate_this_cycle,
    push_uploaded_commits_this_cycle,
    reviewer_needs_refresh,
)
from prgroom.prsession.enums import PRPhase, ReviewerKind, ReviewerStatus
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    PRGroomingState,
    QuiescenceState,
    ReviewerState,
)

_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _reviewer(
    status: ReviewerStatus,
    *,
    required: bool = True,
    declined_reason: str | None = None,
) -> ReviewerState:
    return ReviewerState(
        identity="copilot",
        kind=ReviewerKind.BOT,
        status=status,
        required=required,
        last_request_at=_NOW,
        declined_reason=declined_reason,
    )


def _state(**overrides: object) -> PRGroomingState:
    base: dict[str, object] = {
        "pr": PRRef(owner="octo", repo="demo", number=7),
        "phase": PRPhase.FIXES_PENDING,
        "pr_review_retries_used": 1,
        "last_polled_at": _NOW,
        "last_activity_at": _NOW,
        "quiescence": QuiescenceState(),
    }
    base.update(overrides)
    return PRGroomingState(**base)  # type: ignore[arg-type]


# -- has_required_reviewers_to_refresh -------------------------------------


@pytest.mark.parametrize(
    ("status", "required", "expected"),
    [
        (ReviewerStatus.NOT_REQUESTED, True, True),
        (ReviewerStatus.DECLINED, True, True),
        (ReviewerStatus.REVIEW_FOUND, True, False),
        (ReviewerStatus.REQUESTED, True, False),
        (ReviewerStatus.IN_PROGRESS, True, False),
        (ReviewerStatus.NOT_REQUESTED, False, False),  # optional reviewer never gates
        (ReviewerStatus.DECLINED, False, False),
    ],
)
def test_has_required_reviewers_to_refresh(
    status: ReviewerStatus, required: bool, expected: bool
) -> None:
    state = _state(reviewers={"copilot": _reviewer(status, required=required)})
    assert has_required_reviewers_to_refresh(state) is expected


def test_has_required_reviewers_to_refresh_false_when_no_reviewers() -> None:
    assert has_required_reviewers_to_refresh(_state()) is False


# -- reviewer_needs_refresh ------------------------------------------------


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        (ReviewerStatus.NOT_REQUESTED, None, True),
        (ReviewerStatus.DECLINED, "timeout-no-start", True),
        (ReviewerStatus.DECLINED, "timeout-stalled", True),
        (ReviewerStatus.DECLINED, "user-declined", True),
        (ReviewerStatus.DECLINED, None, True),
        # The one exclusion: an operator (or GitHub) pulled the request. Re-asking
        # would silently override that action.
        (ReviewerStatus.DECLINED, WITHDRAWN_REASON, False),
        (ReviewerStatus.REQUESTED, None, False),
        (ReviewerStatus.IN_PROGRESS, None, False),
        (ReviewerStatus.REVIEW_FOUND, None, False),
    ],
)
def test_reviewer_needs_refresh(status: ReviewerStatus, reason: str | None, expected: bool) -> None:
    assert reviewer_needs_refresh(_reviewer(status, declined_reason=reason)) is expected


def test_has_required_reviewers_to_refresh_skips_withdrawn_reviewer() -> None:
    # A withdrawn reviewer must not re-arm the rereview step (spec behavior 16):
    # rereview_pr would DELETE+POST them back onto the PR.
    state = _state(
        reviewers={"copilot": _reviewer(ReviewerStatus.DECLINED, declined_reason=WITHDRAWN_REASON)}
    )
    assert has_required_reviewers_to_refresh(state) is False


# -- push_uploaded_commits_this_cycle --------------------------------------


def test_push_uploaded_commits_true_when_pushed_sha_changed_this_cycle() -> None:
    state = _state(last_pushed_head_sha="newsha")
    assert push_uploaded_commits_this_cycle(state, cycle_start_pushed_sha="oldsha") is True


def test_push_uploaded_commits_false_when_pushed_sha_unchanged() -> None:
    state = _state(last_pushed_head_sha="samesha")
    assert push_uploaded_commits_this_cycle(state, cycle_start_pushed_sha="samesha") is False


# -- new_lifecycle_gate_this_cycle -----------------------------------------


def test_new_lifecycle_gate_true_when_error_set_this_cycle() -> None:
    state = _state(last_error="LIFECYCLE_PR_REVIEW_EXHAUSTED")
    assert new_lifecycle_gate_this_cycle(state, previous_error=None) is True


def test_new_lifecycle_gate_false_when_error_carried_over() -> None:
    state = _state(last_error="LIFECYCLE_PR_REVIEW_EXHAUSTED")
    previous = "LIFECYCLE_PR_REVIEW_EXHAUSTED"
    assert new_lifecycle_gate_this_cycle(state, previous_error=previous) is False


def test_new_lifecycle_gate_false_when_no_error() -> None:
    assert new_lifecycle_gate_this_cycle(_state(last_error=None), previous_error=None) is False


def test_new_lifecycle_gate_false_when_error_changed_non_none_to_non_none() -> None:
    # §3.3/§4: the predicate means "a gate APPEARED this cycle" (unset->set), so it
    # fires exactly one Sink event per gate. A PR that was ALREADY gated last cycle
    # (a non-None last_error) is not a fresh gate even if the specific code differs;
    # re-firing would emit a duplicate Sink event for an already-reported condition.
    state = _state(last_error="STATE_CORRUPT")
    result = new_lifecycle_gate_this_cycle(state, previous_error="LIFECYCLE_PR_REVIEW_EXHAUSTED")
    assert result is False


# -- flip_stale_required_reviews -------------------------------------------


def test_flip_stale_required_reviews_flips_only_required_review_found() -> None:
    reviewers = {
        "req-found": _reviewer(ReviewerStatus.REVIEW_FOUND, required=True),
        "opt-found": _reviewer(ReviewerStatus.REVIEW_FOUND, required=False),
        "req-progress": _reviewer(ReviewerStatus.IN_PROGRESS, required=True),
        "req-requested": _reviewer(ReviewerStatus.REQUESTED, required=True),
        "req-declined": _reviewer(ReviewerStatus.DECLINED, required=True),
    }
    flip_stale_required_reviews(reviewers)

    assert reviewers["req-found"].status == ReviewerStatus.NOT_REQUESTED
    assert reviewers["opt-found"].status == ReviewerStatus.REVIEW_FOUND  # optional untouched
    assert reviewers["req-progress"].status == ReviewerStatus.IN_PROGRESS  # not review_found
    assert reviewers["req-requested"].status == ReviewerStatus.REQUESTED
    assert reviewers["req-declined"].status == ReviewerStatus.DECLINED


def test_flip_stale_required_reviews_returns_whether_it_flipped_anything() -> None:
    flipped = {"r": _reviewer(ReviewerStatus.REVIEW_FOUND, required=True)}
    nothing = {"r": _reviewer(ReviewerStatus.DECLINED, required=True)}
    assert flip_stale_required_reviews(flipped) is True
    assert flip_stale_required_reviews(nothing) is False


def test_flip_stale_required_reviews_stamps_boundary_when_now_supplied() -> None:
    # The external-push flip stamps the invalidation boundary on last_request_at so a
    # pre-push terminal verdict cannot re-qualify; last_review_at is left intact.
    old_request = _NOW - timedelta(hours=1)
    old_verdict = _NOW - timedelta(minutes=55)
    reviewer = _reviewer(ReviewerStatus.REVIEW_FOUND, required=True)
    reviewer.last_request_at = old_request
    reviewer.last_review_at = old_verdict
    reviewer.last_review_id = 500
    flip_stale_required_reviews({"r": reviewer}, now=_NOW)
    assert reviewer.status == ReviewerStatus.NOT_REQUESTED
    assert reviewer.last_request_at == _NOW  # boundary advanced to the push clock
    assert reviewer.last_review_at == old_verdict  # verdict stamps untouched
    assert reviewer.last_review_id == 500


def test_flip_stale_required_reviews_leaves_boundary_when_now_omitted() -> None:
    # _push omits `now` — its in-cycle rereview re-stamps last_request_at, so the flip
    # itself must not move the boundary (preserving the pre-change behavior).
    old_request = _NOW - timedelta(hours=1)
    reviewer = _reviewer(ReviewerStatus.REVIEW_FOUND, required=True)
    reviewer.last_request_at = old_request
    flip_stale_required_reviews({"r": reviewer})
    assert reviewer.status == ReviewerStatus.NOT_REQUESTED
    assert reviewer.last_request_at == old_request  # untouched without `now`
