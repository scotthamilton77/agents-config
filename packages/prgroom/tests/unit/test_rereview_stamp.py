"""``rereview_pr`` stamps ``last_rereviewed_sha`` after a clean re-request pass.

The stamp records the HEAD the freshly-asked reviewers will now see, so
``push_awaiting_rereview`` flips false once the dance completes. It advances even
when no reviewer was stale (the guard already gated entry); a mid-loop POST failure
that raises leaves it un-advanced (the deepcopy is discarded).
"""

from datetime import UTC, datetime

from prgroom.lifecycle.rereview import rereview_pr
from prgroom.prsession.enums import ReviewerKind, ReviewerStatus
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import ReviewerState, bootstrap_state

_NOW = datetime(2026, 6, 19, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return _NOW


class _Deps:
    clock = _Clock()


class _RecordingGh:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def rest(self, method: str, path: str, *, fields=None):
        self.calls.append((method, path, fields))
        return {}


def _ref() -> PRRef:
    return PRRef(owner="o", repo="r", number=1)


def _state_with_stale_required():
    s = bootstrap_state(_ref(), now=_NOW)
    s.last_review_invalidated_sha = "head1"
    s.reviewers["copilot"] = ReviewerState(
        identity="copilot",
        kind=ReviewerKind.BOT,
        status=ReviewerStatus.NOT_REQUESTED,
        required=True,
        last_request_at=_NOW,
    )
    return s


def test_clean_rereview_stamps_last_rereviewed_sha() -> None:
    s = _state_with_stale_required()
    out = rereview_pr(s, ref=_ref(), gh=_RecordingGh(), deps=_Deps())
    assert out.last_rereviewed_sha == "head1"
    assert out.reviewers["copilot"].status is ReviewerStatus.REQUESTED


def test_no_stale_reviewer_still_stamps() -> None:
    # No refreshable reviewer -> dance loop body never runs, but the stamp still
    # advances so push_awaiting_rereview goes false (the guard already gated entry).
    s = bootstrap_state(_ref(), now=_NOW)
    s.last_review_invalidated_sha = "head1"
    out = rereview_pr(s, ref=_ref(), gh=_RecordingGh(), deps=_Deps())
    assert out.last_rereviewed_sha == "head1"
