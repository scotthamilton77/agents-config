"""Tests for ``push_pr`` — the lock-held ``_push`` lifecycle internal (§3.2/§3.4/§3.5).

``push_pr`` is the first write verb: it uploads the fix agent's queued commits to
the PR's head branch, bumps ``round``, records ``last_pushed_head_sha``, and flips
stale required reviews so the post-push ``_rereview`` re-asks them. The mocked seam
is the gh/git adapter surface (duck-typed fakes); state, config, and the reviewer
flip are real. ``push_pr`` works on a deepcopy and never writes the store (§3.3).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prgroom.config import PrgroomConfig
from prgroom.errors import ErrorCode, PreconditionError, PrgroomError, Tier
from prgroom.lifecycle.push import push_pr
from prgroom.prsession.enums import PRPhase, ReviewerKind, ReviewerStatus
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    PRGroomingState,
    QuiescenceState,
    ReviewerState,
)

_REF = PRRef(owner="octo", repo="demo", number=7)
_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


class FakeGh:
    """Duck-typed gh surface ``push_pr`` consumes: remote HEAD + head-branch name."""

    def __init__(self, *, head_oid: str = "remotesha", head_name: str = "feature-x") -> None:
        self._oid = head_oid
        self._name = head_name

    def head_ref_oid(self, ref: PRRef) -> str:
        del ref
        return self._oid

    def head_ref_name(self, ref: PRRef) -> str:
        del ref
        return self._name


class FakeGit:
    """Duck-typed git surface; records the push refspec and replays a queued list."""

    def __init__(
        self,
        *,
        head: str = "localsha",
        queued: list[str] | None = None,
        branch: str = "feature-x",
    ) -> None:
        self._head = head
        self._queued = list(queued) if queued is not None else []
        self._branch = branch
        self.pushes: list[tuple[str, str]] = []

    def current_branch(self) -> str:
        return self._branch

    def head_sha(self) -> str:
        return self._head

    def rev_list(self, range_: str) -> list[str]:
        del range_
        return list(self._queued)

    def push(self, remote: str, branch: str) -> None:
        self.pushes.append((remote, branch))


class RejectingGit(FakeGit):
    """A git fake whose push is rejected by the remote (terminal)."""

    def push(self, remote: str, branch: str) -> None:
        del remote, branch
        raise PrgroomError(
            tier=Tier.RUNTIME_TERMINAL_USER,
            code=ErrorCode.RUNTIME_PUSH_REJECTED,
            detail="![remote rejected] feature-x (protected branch)",
        )


def _reviewer(status: ReviewerStatus, *, required: bool = True) -> ReviewerState:
    return ReviewerState(
        identity="copilot",
        kind=ReviewerKind.BOT,
        status=status,
        required=required,
        last_request_at=_T0,
    )


def _state(
    *,
    round_: int = 1,
    phase: PRPhase = PRPhase.FIXES_PENDING,
    reviewers: dict[str, ReviewerState] | None = None,
) -> PRGroomingState:
    return PRGroomingState(
        pr=_REF,
        phase=phase,
        round=round_,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(),
        reviewers=reviewers or {},
    )


def test_push_uploads_queued_commits_and_bumps_round() -> None:
    git = FakeGit(head="newhead", queued=["c1"])
    out = push_pr(
        _state(round_=1),
        ref=_REF,
        gh=FakeGh(head_name="feature-x"),
        git=git,
        config=PrgroomConfig(),
    )
    assert git.pushes == [("origin", "HEAD:feature-x")]
    assert out.round == 2
    assert out.last_pushed_head_sha == "newhead"


def test_push_no_queued_commits_is_a_noop() -> None:
    # Remote tip already matches local (rev_list empty) → nothing to push: no git
    # push, round untouched, last_pushed_head_sha untouched (§3.4 idempotency).
    git = FakeGit(queued=[])
    out = push_pr(
        _state(round_=2),
        ref=_REF,
        gh=FakeGh(),
        git=git,
        config=PrgroomConfig(),
    )
    assert git.pushes == []
    assert out.round == 2
    assert out.last_pushed_head_sha == ""


def test_push_bootstraps_round_zero_to_one() -> None:
    # First-ever CLI push on a freshly-opened PR (round 0): the single increment
    # anchors the counter at 1 (§3.4 _push bootstrap).
    out = push_pr(
        _state(round_=0),
        ref=_REF,
        gh=FakeGh(),
        git=FakeGit(queued=["c1"]),
        config=PrgroomConfig(),
    )
    assert out.round == 1


def test_push_flips_stale_required_review_found_to_not_requested() -> None:
    # A successful push changes HEAD, so a required reviewer's review on the old
    # SHA is stale → flipped to not_requested for the post-push _rereview (§3.4).
    reviewers = {
        "copilot": _reviewer(ReviewerStatus.REVIEW_FOUND, required=True),
        "human": _reviewer(ReviewerStatus.REVIEW_FOUND, required=False),
    }
    out = push_pr(
        _state(round_=1, reviewers=reviewers),
        ref=_REF,
        gh=FakeGh(),
        git=FakeGit(queued=["c1"]),
        config=PrgroomConfig(),
    )
    assert out.reviewers["copilot"].status is ReviewerStatus.NOT_REQUESTED
    # Optional reviewers are untouched — only required reviews gate quiescence.
    assert out.reviewers["human"].status is ReviewerStatus.REVIEW_FOUND


def test_push_rejection_propagates_and_leaves_state_unmutated() -> None:
    # A rejected push surfaces RUNTIME_PUSH_REJECTED; round/reviewers are mutated
    # only AFTER a successful push, so the caller keeps its pre-push state.
    reviewers = {"copilot": _reviewer(ReviewerStatus.REVIEW_FOUND)}
    state = _state(round_=1, reviewers=reviewers)
    with pytest.raises(PrgroomError) as exc:
        push_pr(
            state,
            ref=_REF,
            gh=FakeGh(),
            git=RejectingGit(queued=["c1"]),
            config=PrgroomConfig(),
        )
    assert exc.value.code is ErrorCode.RUNTIME_PUSH_REJECTED
    assert state.round == 1
    assert state.reviewers["copilot"].status is ReviewerStatus.REVIEW_FOUND


def test_push_warns_when_it_reaches_the_round_cap() -> None:
    # §3.5: the push that advances round to max_rounds emits a one-line advisory
    # so operators know the next fix cycle will gate to human-gated.
    msgs: list[str] = []
    push_pr(
        _state(round_=2),
        ref=_REF,
        gh=FakeGh(),
        git=FakeGit(queued=["c1"]),
        config=PrgroomConfig(max_rounds=3),
        warn=msgs.append,
    )
    assert any("max_rounds=3" in m for m in msgs)


def test_push_on_the_wrong_branch_raises_and_pushes_nothing() -> None:
    # The first live mutation must not trust the ambient checkout: if the worktree
    # is on a branch other than the PR head branch (§3.4 "local PR-branch HEAD"),
    # push refuses before any git push rather than publish the wrong commits.
    git = FakeGit(queued=["c1"], branch="main")
    with pytest.raises(PreconditionError) as exc:
        push_pr(
            _state(round_=1),
            ref=_REF,
            gh=FakeGh(head_name="feature-x"),
            git=git,
            config=PrgroomConfig(),
        )
    assert exc.value.code is ErrorCode.PRECONDITION_WRONG_BRANCH
    assert git.pushes == []


def test_push_below_the_cap_is_silent() -> None:
    msgs: list[str] = []
    push_pr(
        _state(round_=1),
        ref=_REF,
        gh=FakeGh(),
        git=FakeGit(queued=["c1"]),
        config=PrgroomConfig(max_rounds=3),
        warn=msgs.append,
    )
    assert msgs == []
