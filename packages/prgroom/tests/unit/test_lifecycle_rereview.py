"""Tests for ``rereview_pr`` — the lock-held ``_rereview`` lifecycle internal (§3.2/§3.4).

After a push invalidates prior reviews, ``_rereview`` re-requests every required
reviewer in ``{not_requested, declined}`` via the gh "remove + re-add" dance (the
quirk that forces a fresh bot review), then moves each to ``requested`` so a second
pass is a no-op. The mocked seam is the subprocess boundary (``GhCli`` driven by a
``RecordedRunner``); the issued DELETE/POST commands and the reviewer-state
transition are the observable behavior. Works on a deepcopy; no store write (§3.3).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prgroom.deps import Deps
from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.gh import GhCli
from prgroom.lifecycle.rereview import rereview_pr
from prgroom.proc import CommandResult
from prgroom.prsession.enums import PRPhase, ReviewerKind, ReviewerStatus
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import PRGroomingState, QuiescenceState, ReviewerState
from tests.conftest import FixedRandomness, FrozenClock
from tests.fakes import RecordedRunner

_REF = PRRef(owner="octo", repo="demo", number=7)
_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_LATER = datetime(2026, 6, 9, 13, 0, 0, tzinfo=UTC)


def _ok() -> CommandResult:
    return CommandResult(returncode=0, stdout="{}", stderr="")


def _not_found() -> CommandResult:
    return CommandResult(returncode=1, stdout="", stderr="gh: Not Found (HTTP 404)")


def _deps(now: datetime = _LATER) -> Deps:
    return Deps(clock=FrozenClock(now), randomness=FixedRandomness())


def _reviewer(
    status: ReviewerStatus, *, identity: str = "copilot", required: bool = True
) -> ReviewerState:
    return ReviewerState(
        identity=identity,
        kind=ReviewerKind.BOT,
        status=status,
        required=required,
        last_request_at=_T0,
    )


def _state(reviewers: dict[str, ReviewerState]) -> PRGroomingState:
    return PRGroomingState(
        pr=_REF,
        phase=PRPhase.FIXES_PENDING,
        pr_review_retries_used=2,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(),
        reviewers=reviewers,
    )


def test_rereview_re_requests_a_not_requested_required_reviewer() -> None:
    runner = RecordedRunner([_ok(), _ok()])
    out = rereview_pr(
        _state({"copilot": _reviewer(ReviewerStatus.NOT_REQUESTED)}),
        ref=_REF,
        gh=GhCli(runner),
        deps=_deps(),
    )
    # The remove + re-add dance: DELETE then POST requested_reviewers, each naming
    # the reviewer in the gh array-field form.
    assert [c[3] for c in runner.calls] == ["DELETE", "POST"]
    for argv in runner.calls:
        assert "repos/octo/demo/pulls/7/requested_reviewers" in argv
        assert "reviewers[]=copilot" in argv
    # And the reviewer moves to `requested` (so a second pass is a no-op) at `now`.
    assert out.reviewers["copilot"].status is ReviewerStatus.REQUESTED
    assert out.reviewers["copilot"].last_request_at == _LATER


def test_rereview_re_requests_a_declined_required_reviewer() -> None:
    runner = RecordedRunner([_ok(), _ok()])
    out = rereview_pr(
        _state({"copilot": _reviewer(ReviewerStatus.DECLINED)}),
        ref=_REF,
        gh=GhCli(runner),
        deps=_deps(),
    )
    assert [c[3] for c in runner.calls] == ["DELETE", "POST"]
    assert out.reviewers["copilot"].status is ReviewerStatus.REQUESTED


def test_rereview_maps_a_vanished_pr_to_a_terminal_error() -> None:
    # A 404 on the reviewer-request call (PR/repo deleted mid-run) must surface as
    # a terminal PrgroomError, not leak GhNotFoundError as a raw traceback.
    with pytest.raises(PrgroomError) as exc:
        rereview_pr(
            _state({"copilot": _reviewer(ReviewerStatus.NOT_REQUESTED)}),
            ref=_REF,
            gh=GhCli(RecordedRunner([_not_found()])),
            deps=_deps(),
        )
    assert exc.value.code is ErrorCode.RUNTIME_GH_TERMINAL
    assert exc.value.tier is Tier.RUNTIME_TERMINAL_USER


def test_rereview_skips_a_non_required_reviewer() -> None:
    # Optional reviewers don't gate quiescence and aren't re-requested.
    runner = RecordedRunner([])  # any gh call would raise "exhausted"
    out = rereview_pr(
        _state({"human": _reviewer(ReviewerStatus.NOT_REQUESTED, required=False)}),
        ref=_REF,
        gh=GhCli(runner),
        deps=_deps(),
    )
    assert runner.calls == []
    assert out.reviewers["human"].status is ReviewerStatus.NOT_REQUESTED


def test_rereview_is_a_noop_when_no_required_reviewer_is_stale() -> None:
    # A required reviewer mid-pass (requested / in_progress) or already engaged
    # (review_found) is not disturbed.
    runner = RecordedRunner([])
    out = rereview_pr(
        _state(
            {
                "copilot": _reviewer(ReviewerStatus.REQUESTED),
                "codeowner": _reviewer(ReviewerStatus.REVIEW_FOUND, identity="codeowner"),
            }
        ),
        ref=_REF,
        gh=GhCli(runner),
        deps=_deps(),
    )
    assert runner.calls == []
    assert out.reviewers["copilot"].status is ReviewerStatus.REQUESTED
    assert out.reviewers["codeowner"].status is ReviewerStatus.REVIEW_FOUND


def test_withdrawn_reviewer_is_never_re_requested() -> None:
    # A reviewer declined as request-withdrawn had their pending request removed on
    # GitHub's side. Re-requesting would DELETE+POST them back onto the PR, silently
    # overriding that. No gh call at all should be issued for them (spec behavior 16).
    from prgroom.lifecycle.predicates import WITHDRAWN_REASON

    reviewers = {"copilot": _reviewer(ReviewerStatus.DECLINED)}
    reviewers["copilot"].declined_reason = WITHDRAWN_REASON
    runner = RecordedRunner([])  # any gh call would raise StopIteration / IndexError
    state = rereview_pr(_state(reviewers), ref=_REF, gh=GhCli(runner), deps=_deps())
    assert state.reviewers["copilot"].status is ReviewerStatus.DECLINED
    assert state.reviewers["copilot"].declined_reason == WITHDRAWN_REASON


def test_timeout_declined_reviewer_is_still_re_requested() -> None:
    # The narrowing is specific to the withdrawal reason — a timeout decline is
    # still a missing verdict a fresh push deserves another shot at.
    reviewers = {"copilot": _reviewer(ReviewerStatus.DECLINED)}
    reviewers["copilot"].declined_reason = "timeout-no-start"
    state = rereview_pr(
        _state(reviewers), ref=_REF, gh=GhCli(RecordedRunner([_ok(), _ok()])), deps=_deps()
    )
    assert state.reviewers["copilot"].status is ReviewerStatus.REQUESTED
    assert state.reviewers["copilot"].last_request_at == _LATER
