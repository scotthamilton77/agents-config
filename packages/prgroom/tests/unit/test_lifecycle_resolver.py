"""Table-driven tests for the §3.2 end-of-cycle phase resolver.

The resolver is a SIX-priority, first-match-wins cascade over a ``fixes-pending``
state plus two effectful signals the run-loop supplies (queued-commits from git,
quiescence from §4.1). The load-bearing property is **first-match-wins**: when
several conditions hold at once, the highest-priority one decides. The table below
pins each priority AND the precedence between them (e.g. cap+escalated → cap wins).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prgroom.lifecycle.resolver import ResolvedPhase, resolve_end_of_cycle_phase
from prgroom.prsession.enums import DispositionKind, ItemKind, PRPhase
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Disposition,
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewItem,
)

_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_CAP = 3


def _item(kind: DispositionKind) -> ReviewItem:
    return ReviewItem(
        kind=ItemKind.ISSUE_COMMENT,
        identity=Identity(gh_id=f"c-{kind.value}"),
        author="copilot",
        body_excerpt="b",
        seen_at=_NOW,
        disposition=Disposition(kind=kind, decided_at=_NOW, decided_by="agent"),
    )


def _state(*, retries_: int = 1, items: list[ReviewItem] | None = None) -> PRGroomingState:
    return PRGroomingState(
        pr=PRRef(owner="octo", repo="demo", number=7),
        phase=PRPhase.FIXES_PENDING,
        pr_review_retries_used=retries_,
        last_polled_at=_NOW,
        last_activity_at=_NOW,
        quiescence=QuiescenceState(),
        items=items or [],
    )


def _resolve(
    state: PRGroomingState,
    *,
    has_queued_commits: bool,
    quiescent: bool,
    pushed_this_cycle: bool,
) -> ResolvedPhase:
    return resolve_end_of_cycle_phase(
        state,
        now=_NOW,
        pr_review_retries=_CAP,
        has_queued_commits=has_queued_commits,
        pushed_this_cycle=pushed_this_cycle,
        quiescent=quiescent,
    )


# -- priority 1: hard cap --------------------------------------------------


def test_p1_cap_trips_to_human_gated_with_cap_error() -> None:
    result = _resolve(
        _state(retries_=_CAP), has_queued_commits=True, quiescent=False, pushed_this_cycle=False
    )
    assert result.phase == PRPhase.HUMAN_GATED
    assert result.last_error == "LIFECYCLE_PR_REVIEW_EXHAUSTED"
    assert result.quiesced_at is None


def test_p1_cap_not_tripped_below_pr_review_retries() -> None:
    # retries below the budget → the guard does not fire even with queued commits.
    result = _resolve(
        _state(retries_=_CAP - 1, items=[_item(DispositionKind.FIXED)]),
        has_queued_commits=True,
        quiescent=False,
        pushed_this_cycle=True,
    )
    assert result.phase == PRPhase.AWAITING_REVIEW  # priority 4 (commit pushed)


def test_p1_cap_first_match_wins_over_escalated_and_failed() -> None:
    # cap + escalated + failed all hold; cap (priority 1) must win.
    state = _state(
        retries_=_CAP, items=[_item(DispositionKind.ESCALATED), _item(DispositionKind.FAILED)]
    )
    result = _resolve(state, has_queued_commits=True, quiescent=False, pushed_this_cycle=False)
    assert result.phase == PRPhase.HUMAN_GATED
    assert result.last_error == "LIFECYCLE_PR_REVIEW_EXHAUSTED"


# -- priority 2: any FAILED ------------------------------------------------


def test_p2_failed_item_gates_human_without_last_error() -> None:
    # No cap trip (no queued commits): a failed item alone → human-gated, last_error
    # left to the per-item rationale (resolver does not set it for priority 2).
    state = _state(items=[_item(DispositionKind.FAILED)])
    result = _resolve(state, has_queued_commits=False, quiescent=False, pushed_this_cycle=False)
    assert result.phase == PRPhase.HUMAN_GATED
    assert result.last_error is None


def test_p2_failed_wins_over_escalated() -> None:
    state = _state(items=[_item(DispositionKind.ESCALATED), _item(DispositionKind.FAILED)])
    result = _resolve(state, has_queued_commits=False, quiescent=False, pushed_this_cycle=False)
    assert result.phase == PRPhase.HUMAN_GATED
    assert result.last_error is None


# -- priority 3: unresolved ESCALATED --------------------------------------


def test_p3_escalated_item_gates_human() -> None:
    state = _state(items=[_item(DispositionKind.ESCALATED)])
    result = _resolve(state, has_queued_commits=False, quiescent=False, pushed_this_cycle=False)
    assert result.phase == PRPhase.HUMAN_GATED
    assert result.last_error is None


# -- priority 4: commit pushed this cycle ----------------------------------


def test_p4_commit_pushed_returns_awaiting_review() -> None:
    state = _state(items=[_item(DispositionKind.FIXED)])
    result = _resolve(state, has_queued_commits=False, quiescent=False, pushed_this_cycle=True)
    assert result.phase == PRPhase.AWAITING_REVIEW
    assert result.last_error is None
    assert result.quiesced_at is None


# -- priority 5: zero-push + quiescence ------------------------------------


def test_p5_zero_push_and_quiescent_returns_quiesced_with_timestamp() -> None:
    state = _state(items=[_item(DispositionKind.SKIPPED)])
    result = _resolve(state, has_queued_commits=False, quiescent=True, pushed_this_cycle=False)
    assert result.phase == PRPhase.QUIESCED
    assert result.quiesced_at == _NOW
    assert result.last_error is None


def test_p5_quiescent_but_pushed_does_not_quiesce() -> None:
    # pushed_this_cycle short-circuits at priority 4 before quiescence is consulted.
    state = _state(items=[_item(DispositionKind.FIXED)])
    result = _resolve(state, has_queued_commits=False, quiescent=True, pushed_this_cycle=True)
    assert result.phase == PRPhase.AWAITING_REVIEW


# -- priority 6: fall-through ----------------------------------------------


def test_p6_no_push_not_quiescent_falls_through_to_awaiting_review() -> None:
    state = _state(items=[_item(DispositionKind.SKIPPED)])
    result = _resolve(state, has_queued_commits=False, quiescent=False, pushed_this_cycle=False)
    assert result.phase == PRPhase.AWAITING_REVIEW
    assert result.last_error is None
    assert result.quiesced_at is None


@pytest.mark.parametrize(
    ("phase", "retries_", "items", "queued", "pushed", "quiescent", "expected"),
    [
        # cap wins over everything
        ("p1", _CAP, [DispositionKind.ESCALATED], True, False, True, PRPhase.HUMAN_GATED),
        # failed beats escalated/quiescence
        ("p2", 1, [DispositionKind.FAILED], False, False, True, PRPhase.HUMAN_GATED),
        # escalated beats quiescence
        ("p3", 1, [DispositionKind.ESCALATED], False, False, True, PRPhase.HUMAN_GATED),
        # commit pushed beats quiescence
        ("p4", 1, [DispositionKind.FIXED], False, True, True, PRPhase.AWAITING_REVIEW),
        # quiescence when nothing higher fired
        ("p5", 1, [DispositionKind.SKIPPED], False, False, True, PRPhase.QUIESCED),
        # fall-through
        ("p6", 1, [DispositionKind.WONT_FIX], False, False, False, PRPhase.AWAITING_REVIEW),
    ],
)
def test_first_match_wins_cascade(
    phase: str,
    retries_: int,
    items: list[DispositionKind],
    queued: bool,
    pushed: bool,
    quiescent: bool,
    expected: PRPhase,
) -> None:
    state = _state(retries_=retries_, items=[_item(k) for k in items])
    result = _resolve(
        state, has_queued_commits=queued, quiescent=quiescent, pushed_this_cycle=pushed
    )
    assert result.phase == expected, f"{phase}: expected {expected}, got {result.phase}"
