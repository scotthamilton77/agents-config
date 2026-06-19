"""Pure state predicates the §3.3 run-loop and resolver depend on (§3.4).

Every function here is a pure read (or, for :func:`flip_stale_required_reviews`,
an in-place mutation) over the in-memory :class:`PRGroomingState` the run-loop
threads — no clock, no RNG, no network. The two cycle-relative predicates
(``push_uploaded_commits_this_cycle``, ``new_lifecycle_gate_this_cycle``) take the
cycle-start snapshot value as a keyword argument rather than reading a stored
"prior cycle" field, because the spec keeps no such field — the run-loop captures
the snapshot at cycle entry and hands it back here.

``has_queued_fix_commits`` is deliberately absent: §3.4 forbids a state field for
the commit queue (the remote tip is the source of truth), so that signal is an
effectful git read the run-loop supplies to the resolver as a bool. The pure
spine never computes it.
"""

from __future__ import annotations

from prgroom.prsession.enums import ReviewerStatus
from prgroom.prsession.state import PRGroomingState, ReviewerState

# Reviewer statuses that a post-push ``rereview`` re-requests (§3.4). After
# ``flip_stale_required_reviews`` runs, ``review_found`` reviewers have moved into
# ``not_requested``, so this set captures every required reviewer needing a fresh ask.
_REFRESHABLE_STATUSES: frozenset[ReviewerStatus] = frozenset(
    {ReviewerStatus.NOT_REQUESTED, ReviewerStatus.DECLINED}
)


def has_required_reviewers_to_refresh(state: PRGroomingState) -> bool:
    """True iff ≥1 ``required`` reviewer is in ``{not_requested, declined}`` (§3.4).

    Gates the post-push ``_rereview`` call. False when no required reviewers exist
    (the PR has no Copilot/codeowner required reviewer set) or all are mid-pass
    (``requested`` / ``in_progress``) or already engaged (``review_found``).
    """
    return any(r.required and r.status in _REFRESHABLE_STATUSES for r in state.reviewers.values())


def push_uploaded_commits_this_cycle(
    state: PRGroomingState, *, cycle_start_pushed_sha: str
) -> bool:
    """True iff ``_push`` advanced ``last_pushed_head_sha`` during this cycle (§3.4).

    The run-loop snapshots ``last_pushed_head_sha`` at cycle entry and passes it as
    ``cycle_start_pushed_sha``; a difference means the most recent ``_push`` uploaded
    ≥1 commit, which gates the post-push ``_rereview`` and the priority-4 resolver rule.
    """
    return state.last_pushed_head_sha != cycle_start_pushed_sha


def push_awaiting_rereview(state: PRGroomingState) -> bool:
    """True iff a review-invalidating HEAD has not yet been rereviewed (§3.4, §6).

    Compares the persisted ``last_review_invalidated_sha`` (stamped by ``_push`` on
    its own commit upload AND by ``_poll`` on an observed external push) against
    ``last_rereviewed_sha`` (stamped by ``_rereview`` on a clean re-request). Unlike
    the cycle-relative ``push_uploaded_commits_this_cycle``, this is durable across a
    cycle that pushed then aborted in ``_reply``/``_resolve``, and it fires for
    external pushes too. Gated downstream by ``has_required_reviewers_to_refresh``.
    """
    return state.last_review_invalidated_sha != state.last_rereviewed_sha


def new_lifecycle_gate_this_cycle(state: PRGroomingState, *, previous_error: str | None) -> bool:
    """True iff a lifecycle gate APPEARED this cycle — unset->set (§3.3, §4).

    A "new gate" is the transition from no gating error to one (``previous_error is
    None`` and ``state.last_error`` now set), per the §3.4 definition ("was set this
    cycle and was NOT set in the prior cycle"). The run-loop uses this to clear
    ``lifecycle_escalation_filed`` exactly once per gate so the loop-top Sink emits one
    event per gate, not one per cycle. A PR that was ALREADY gated last cycle (a
    non-None prior error) is not a fresh gate even if the specific code differs —
    re-firing would emit a duplicate Sink event for an already-reported condition.
    ``previous_error`` is the cycle-start snapshot of ``state.last_error``.
    """
    return previous_error is None and state.last_error is not None


def flip_stale_required_reviews(reviewers: dict[str, ReviewerState]) -> bool:
    """Invalidate prior reviews bound to a superseded SHA (§3.4 shared flip).

    A new push (CLI's own in ``_push``, or external in ``_poll``) changes HEAD, so
    every ``required`` reviewer in ``review_found`` had its review on the old SHA;
    flip those to ``not_requested`` so the post-push ``_rereview`` re-asks them.
    Reviewers in ``{requested, in_progress, declined}`` and all optional reviewers
    are left untouched. Mutates ``reviewers`` in place; returns whether any flipped.
    """
    flipped = False
    for r in reviewers.values():
        if r.required and r.status == ReviewerStatus.REVIEW_FOUND:
            r.status = ReviewerStatus.NOT_REQUESTED
            flipped = True
    return flipped
