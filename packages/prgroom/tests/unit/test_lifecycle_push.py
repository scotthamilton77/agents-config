"""Tests for ``push_pr`` — the lock-held ``_push`` lifecycle internal (§3.2/§3.4/§3.5).

``push_pr`` is the first write verb: it uploads the fix agent's queued commits to
the PR's head branch, counts the consumed PR-review retry (the initial observed
push is free, §3.4), records ``last_pushed_head_sha``, and flips stale required
reviews so the post-push ``_rereview`` re-asks them. The mocked seam
is the gh/git adapter surface (duck-typed fakes); state, config, and the reviewer
flip are real. ``push_pr`` works on a deepcopy and never writes the store (§3.3).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prgroom.config import PrgroomConfig
from prgroom.errors import ErrorCode, PreconditionError, PrgroomError, Tier
from prgroom.gh import GhNotFoundError
from prgroom.lifecycle.push import has_queued_fix_commits, push_pr
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


class VanishedGh:
    """A gh surface whose reads 404 (PR/repo deleted mid-run)."""

    def head_ref_oid(self, ref: PRRef) -> str:
        del ref
        raise GhNotFoundError

    def head_ref_name(self, ref: PRRef) -> str:
        del ref
        raise GhNotFoundError


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
    retries_: int = 0,
    phase: PRPhase = PRPhase.FIXES_PENDING,
    reviewers: dict[str, ReviewerState] | None = None,
    last_poll_sha: str = "anchor",
    last_pushed_head_sha: str = "",
) -> PRGroomingState:
    # last_poll_sha defaults non-empty: the typical mid-flight state has already
    # observed the initial push via _poll, so the next CLI push is a retry (§3.4).
    return PRGroomingState(
        pr=_REF,
        phase=phase,
        pr_review_retries_used=retries_,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(),
        last_poll_sha=last_poll_sha,
        last_pushed_head_sha=last_pushed_head_sha,
        reviewers=reviewers or {},
    )


def test_push_uploads_queued_commits_and_counts_a_retry() -> None:
    git = FakeGit(head="newhead", queued=["c1"])
    out = push_pr(
        _state(retries_=1),
        ref=_REF,
        gh=FakeGh(head_name="feature-x"),
        git=git,
        config=PrgroomConfig(),
    )
    assert git.pushes == [("origin", "HEAD:feature-x")]
    assert out.pr_review_retries_used == 2
    assert out.last_pushed_head_sha == "newhead"


def test_push_stamps_review_invalidated_sha() -> None:
    git = FakeGit(head="newhead", queued=["c1"])
    out = push_pr(
        _state(retries_=1),
        ref=_REF,
        gh=FakeGh(head_name="feature-x"),
        git=git,
        config=PrgroomConfig(),
    )
    assert out.last_pushed_head_sha == "newhead"
    assert out.last_review_invalidated_sha == "newhead"


def test_push_no_queued_commits_is_a_noop() -> None:
    # Remote tip already matches local (rev_list empty) → nothing to push: no git
    # push, counter untouched, last_pushed_head_sha untouched (§3.4 idempotency).
    git = FakeGit(queued=[])
    out = push_pr(
        _state(retries_=2),
        ref=_REF,
        gh=FakeGh(),
        git=git,
        config=PrgroomConfig(),
    )
    assert git.pushes == []
    assert out.pr_review_retries_used == 2
    assert out.last_pushed_head_sha == ""


def test_push_initial_push_consumes_no_retry() -> None:
    # First-ever review-eliciting push on a freshly-opened PR (no SHA observed by
    # either code path): the initial push is free — the 0-indexed counter stays 0
    # (§3.4 _push bootstrap).
    out = push_pr(
        _state(retries_=0, last_poll_sha="", last_pushed_head_sha=""),
        ref=_REF,
        gh=FakeGh(),
        git=FakeGit(head="newhead", queued=["c1"]),
        config=PrgroomConfig(),
    )
    assert out.pr_review_retries_used == 0
    assert out.last_pushed_head_sha == "newhead"


def test_push_after_own_prior_push_counts_a_retry() -> None:
    # A second CLI push before any successful poll observation: last_poll_sha is
    # still empty but last_pushed_head_sha marks the initial push as spent, so
    # this one consumes a retry (§3.4 — the two bootstrap branches are one-shot).
    out = push_pr(
        _state(retries_=0, last_poll_sha="", last_pushed_head_sha="prior"),
        ref=_REF,
        gh=FakeGh(),
        git=FakeGit(queued=["c2"]),
        config=PrgroomConfig(),
    )
    assert out.pr_review_retries_used == 1


def test_push_flips_stale_required_review_found_to_not_requested() -> None:
    # A successful push changes HEAD, so a required reviewer's review on the old
    # SHA is stale → flipped to not_requested for the post-push _rereview (§3.4).
    reviewers = {
        "copilot": _reviewer(ReviewerStatus.REVIEW_FOUND, required=True),
        "human": _reviewer(ReviewerStatus.REVIEW_FOUND, required=False),
    }
    out = push_pr(
        _state(retries_=1, reviewers=reviewers),
        ref=_REF,
        gh=FakeGh(),
        git=FakeGit(queued=["c1"]),
        config=PrgroomConfig(),
    )
    assert out.reviewers["copilot"].status is ReviewerStatus.NOT_REQUESTED
    # Optional reviewers are untouched — only required reviews gate quiescence.
    assert out.reviewers["human"].status is ReviewerStatus.REVIEW_FOUND


def test_push_maps_a_vanished_pr_to_a_terminal_error() -> None:
    # A 404 mid-run (PR/repo deleted) must surface as a terminal PrgroomError, not
    # leak GhNotFoundError as a raw traceback past the CLI's `except PrgroomError`.
    git = FakeGit(queued=["c1"])
    with pytest.raises(PrgroomError) as exc:
        push_pr(
            _state(retries_=1),
            ref=_REF,
            gh=VanishedGh(),
            git=git,
            config=PrgroomConfig(),
        )
    assert exc.value.code is ErrorCode.RUNTIME_GH_TERMINAL
    assert exc.value.tier is Tier.RUNTIME_TERMINAL_USER
    assert git.pushes == []


def test_push_rejection_propagates_and_leaves_state_unmutated() -> None:
    # A rejected push surfaces RUNTIME_PUSH_REJECTED; the counter/reviewers are
    # mutated only AFTER a successful push, so the caller keeps its pre-push state.
    reviewers = {"copilot": _reviewer(ReviewerStatus.REVIEW_FOUND)}
    state = _state(retries_=1, reviewers=reviewers)
    with pytest.raises(PrgroomError) as exc:
        push_pr(
            state,
            ref=_REF,
            gh=FakeGh(),
            git=RejectingGit(queued=["c1"]),
            config=PrgroomConfig(),
        )
    assert exc.value.code is ErrorCode.RUNTIME_PUSH_REJECTED
    assert state.pr_review_retries_used == 1
    assert state.reviewers["copilot"].status is ReviewerStatus.REVIEW_FOUND


def test_push_warns_when_it_exhausts_the_retry_budget() -> None:
    # §3.5: the push that consumes the last PR-review retry emits a one-line
    # advisory so operators know the next fix cycle will gate to human-gated.
    msgs: list[str] = []
    push_pr(
        _state(retries_=2),
        ref=_REF,
        gh=FakeGh(),
        git=FakeGit(queued=["c1"]),
        config=PrgroomConfig(pr_review_retries=3),
        warn=msgs.append,
    )
    assert any("pr_review_retries=3" in m for m in msgs)


def test_push_on_the_wrong_branch_raises_and_pushes_nothing() -> None:
    # The first live mutation must not trust the ambient checkout: if the worktree
    # is on a branch other than the PR head branch (§3.4 "local PR-branch HEAD"),
    # push refuses before any git push rather than publish the wrong commits.
    git = FakeGit(queued=["c1"], branch="main")
    with pytest.raises(PreconditionError) as exc:
        push_pr(
            _state(retries_=1),
            ref=_REF,
            gh=FakeGh(head_name="feature-x"),
            git=git,
            config=PrgroomConfig(),
        )
    assert exc.value.code is ErrorCode.PRECONDITION_WRONG_BRANCH
    assert git.pushes == []


def test_push_below_the_budget_is_silent() -> None:
    msgs: list[str] = []
    push_pr(
        _state(retries_=1),
        ref=_REF,
        gh=FakeGh(),
        git=FakeGit(queued=["c1"]),
        config=PrgroomConfig(pr_review_retries=3),
        warn=msgs.append,
    )
    assert msgs == []


def test_push_past_the_budget_does_not_re_warn() -> None:
    # §3.5: the advisory fires only on the push that consumes the *last* retry,
    # not on every push once past it. A direct `prgroom push` at retries==budget
    # (no pre-push guard) takes the counter past the budget and must stay silent —
    # re-warning would print an inaccurate "exhausted" line for an already-spent
    # budget.
    msgs: list[str] = []
    push_pr(
        _state(retries_=3),
        ref=_REF,
        gh=FakeGh(),
        git=FakeGit(queued=["c1"]),
        config=PrgroomConfig(pr_review_retries=3),
        warn=msgs.append,
    )
    assert msgs == []


def test_has_queued_fix_commits_maps_404_to_terminal() -> None:
    # PR #165 review: a 404 on the remote-HEAD read (vanished PR/repo) maps to a
    # terminal PrgroomError here, never a raw GhNotFoundError — so the run-loop's
    # PrgroomError-only handlers (_execute_step / run_lifecycle) catch it.
    with pytest.raises(PrgroomError) as excinfo:
        has_queued_fix_commits(VanishedGh(), FakeGit(), _REF)
    assert excinfo.value.tier is Tier.RUNTIME_TERMINAL_USER
    assert excinfo.value.code is ErrorCode.RUNTIME_GH_TERMINAL


def test_default_budget_allows_six_review_eliciting_pushes_including_initial() -> None:
    # Off-by-one pinned by the 8.25 reframe: the default budget of 5 retries
    # permits up to 6 review-eliciting pushes — the free initial plus 5 retries —
    # and the advisory fires exactly on the push consuming the last retry.
    msgs: list[str] = []
    state = _state(retries_=0, last_poll_sha="", last_pushed_head_sha="")
    for expected in [0, 1, 2, 3, 4, 5]:  # initial push, then five retries
        state = push_pr(
            state,
            ref=_REF,
            gh=FakeGh(),
            git=FakeGit(queued=["c"]),
            config=PrgroomConfig(),
            warn=msgs.append,
        )
        assert state.pr_review_retries_used == expected
    assert len(msgs) == 1  # only the budget-exhausting sixth push warns
    assert "pr_review_retries=5" in msgs[0]
