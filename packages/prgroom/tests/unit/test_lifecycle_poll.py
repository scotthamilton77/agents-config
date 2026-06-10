"""Tests for ``poll_pr`` — the read-only ``_poll`` lifecycle internal (§3.2/§3.4/§4.1).

The single mocked seam is the subprocess boundary: ``GhCli`` is driven by a
``RecordedRunner`` queuing the gh REST responses in the exact order ``poll_pr``
issues them — head OID, PR resource, issue comments, reviews, review comments,
CI status. Everything else (state, clock, config) is real. No code we own is
mocked (§7.6).

``poll_pr`` is read-only: it mutates a returned ``PRGroomingState`` copy and never
writes to GitHub. The caller owns ``store.write``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from prgroom.config import PrgroomConfig
from prgroom.deps import Deps
from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.gh import GhCli
from prgroom.lifecycle import poll_pr
from prgroom.proc import CommandResult
from prgroom.prsession.enums import (
    ItemKind,
    PRPhase,
    ReviewerKind,
    ReviewerStatus,
)
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewerState,
    ReviewItem,
    bootstrap_state,
)
from tests.conftest import FixedRandomness, FrozenClock

_REF = PRRef(owner="octo", repo="demo", number=7)
_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _ok(payload: object) -> CommandResult:
    return CommandResult(returncode=0, stdout=json.dumps(payload), stderr="")


def _gh_http_error(status: int, message: str) -> CommandResult:
    body = json.dumps({"message": message, "status": str(status)})
    return CommandResult(returncode=1, stdout=body, stderr=f"gh: {message} (HTTP {status})")


class _QueueRunner:
    """A CommandRunner fake replaying queued CommandResults in FIFO order.

    Mirrors ``tests.fakes.RecordedRunner`` but records nothing extra — poll tests
    assert on resulting state, not argv. Exhaustion raises so an unexpected extra
    gh call is never silently masked by an empty result.
    """

    def __init__(self, results: list[CommandResult]) -> None:
        self._results = list(results)
        self.calls: list[list[str]] = []

    def run(
        self,
        argv,  # Sequence[str]; matches the CommandRunner Protocol
        *,
        input: str | None = None,  # noqa: ARG002  # Protocol keyword, unused here
        timeout: float | None = None,  # noqa: ARG002  # Protocol keyword, unused here
    ) -> CommandResult:
        self.calls.append(list(argv))
        if not self._results:
            msg = f"_QueueRunner exhausted: unexpected call {list(argv)!r}"
            raise AssertionError(msg)
        return self._results.pop(0)


def _gh(
    *,
    head_oid: str = "headsha1",
    pr_merged: bool = False,
    issue_comments: list[dict[str, object]] | None = None,
    reviews: list[dict[str, object]] | None = None,
    review_comments: list[dict[str, object]] | None = None,
    ci: str = "success",
) -> GhCli:
    """Build a GhCli queuing the six poll reads in the order ``poll_pr`` issues them."""
    pr = (
        {"state": "closed", "merged_at": "2026-06-09T10:00:00Z"}
        if pr_merged
        else {"state": "open", "merged_at": None}
    )
    results = [
        _ok({"headRefOid": head_oid}),
        _ok(pr),
        _ok(issue_comments or []),
        _ok(reviews or []),
        _ok(review_comments or []),
        _ok({"state": ci}),
    ]
    return GhCli(_QueueRunner(results))


def _deps(now: datetime = _T0) -> Deps:
    return Deps(clock=FrozenClock(now), randomness=FixedRandomness())


def _config() -> PrgroomConfig:
    return PrgroomConfig()


def _idle_state() -> PRGroomingState:
    return bootstrap_state(_REF, now=_T0)


def _state(
    *,
    phase: PRPhase,
    round_: int = 1,
    last_poll_sha: str = "headsha1",
    last_pushed_head_sha: str = "",
    reviewers: dict[str, ReviewerState] | None = None,
) -> PRGroomingState:
    return PRGroomingState(
        pr=_REF,
        phase=phase,
        round=round_,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(),
        last_poll_sha=last_poll_sha,
        last_pushed_head_sha=last_pushed_head_sha,
        reviewers=reviewers or {},
    )


def _required_reviewer(status: ReviewerStatus) -> dict[str, ReviewerState]:
    return {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=status,
            required=True,
            last_request_at=_T0,
        )
    }


# ── bootstrap (last_poll_sha == "") ──


def test_bootstrap_non_empty_head_anchors_round_one_and_awaiting_review() -> None:
    state = poll_pr(_idle_state(), ref=_REF, gh=_gh(head_oid="abc"), deps=_deps(), config=_config())
    assert state.round == 1
    assert state.last_poll_sha == "abc"
    assert state.phase is PRPhase.AWAITING_REVIEW


def test_bootstrap_empty_head_leaves_round_zero_and_idle() -> None:
    # An empty remote HEAD short-circuits: head_ref_oid is the only gh call.
    gh = GhCli(_QueueRunner([_ok({"headRefOid": ""})]))
    state = poll_pr(_idle_state(), ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.round == 0
    assert state.last_poll_sha == ""
    assert state.phase is PRPhase.IDLE


def test_bootstrap_does_not_double_bump_when_push_already_anchored() -> None:
    # _push may have already set round=1; bootstrap is idempotent (max(round, 1)).
    start = _state(phase=PRPhase.IDLE, round_=1, last_poll_sha="", last_pushed_head_sha="abc")
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="abc"), deps=_deps(), config=_config())
    assert state.round == 1
    assert state.last_poll_sha == "abc"


# ── unchanged SHA (idempotent no-op on the push axis) ──


def test_unchanged_sha_does_not_bump_round_or_touch_reviewers() -> None:
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    start = _state(
        phase=PRPhase.AWAITING_REVIEW, round_=2, last_poll_sha="same", reviewers=reviewers
    )
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="same"), deps=_deps(), config=_config())
    assert state.round == 2
    assert state.reviewers["copilot"].status is ReviewerStatus.REVIEW_FOUND


# ── CLI's own push (new_head == last_pushed_head_sha) ──


def test_cli_own_push_advances_poll_sha_without_round_bump_or_reviewer_flip() -> None:
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        round_=2,
        last_poll_sha="old",
        last_pushed_head_sha="new",
        reviewers=reviewers,
    )
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="new"), deps=_deps(), config=_config())
    assert state.round == 2  # _push already counted it
    assert state.last_poll_sha == "new"
    # _push already flipped reviewers; _poll must leave them untouched.
    assert state.reviewers["copilot"].status is ReviewerStatus.REVIEW_FOUND


# ── external push (new_head != last_pushed_head_sha) ──


def test_external_push_bumps_round_and_flips_required_review_found() -> None:
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        round_=2,
        last_poll_sha="old",
        last_pushed_head_sha="mine",
        reviewers=reviewers,
    )
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="theirs"), deps=_deps(), config=_config())
    assert state.round == 3
    assert state.last_poll_sha == "theirs"
    assert state.last_pushed_head_sha == "mine"  # untouched — not the CLI's push
    assert state.reviewers["copilot"].status is ReviewerStatus.NOT_REQUESTED


def test_external_push_does_not_flip_optional_reviewer() -> None:
    reviewers = {
        "human": ReviewerState(
            identity="human",
            kind=ReviewerKind.HUMAN,
            status=ReviewerStatus.REVIEW_FOUND,
            required=False,
            last_request_at=_T0,
        )
    }
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        round_=1,
        last_poll_sha="old",
        last_pushed_head_sha="mine",
        reviewers=reviewers,
    )
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="theirs"), deps=_deps(), config=_config())
    assert state.reviewers["human"].status is ReviewerStatus.REVIEW_FOUND


def test_poll_does_not_mutate_caller_state() -> None:
    start = _idle_state()
    poll_pr(start, ref=_REF, gh=_gh(head_oid="abc"), deps=_deps(), config=_config())
    # The caller's object is untouched; poll_pr works on a copy and returns it.
    assert start.round == 0
    assert start.last_poll_sha == ""
    assert start.phase is PRPhase.IDLE


# ── item ingestion + phase resolution (§3.2 poll row) ──


def _issue_comment(cid: int, login: str = "copilot") -> dict[str, object]:
    return {
        "id": cid,
        "user": {"login": login},
        "body": "x" * 250,  # > 200 to exercise the body_excerpt truncation
        "created_at": "2026-06-09T11:00:00Z",
    }


def _review(rid: int, login: str = "copilot") -> dict[str, object]:
    return {
        "id": rid,
        "user": {"login": login},
        "state": "CHANGES_REQUESTED",
        "body": "please fix",
        "submitted_at": "2026-06-09T11:05:00Z",
    }


def _review_comment(cid: int, login: str = "copilot") -> dict[str, object]:
    return {
        "id": cid,
        "user": {"login": login},
        "body": "inline nit",
        "created_at": "2026-06-09T11:06:00Z",
    }


def test_new_reviewer_item_moves_awaiting_review_to_fixes_pending() -> None:
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(head_oid="same", issue_comments=[_issue_comment(11)])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.phase is PRPhase.FIXES_PENDING
    assert len(state.items) == 1
    item = state.items[0]
    assert item.kind is ItemKind.ISSUE_COMMENT
    assert item.identity.gh_id == "11"
    assert item.author == "copilot"
    assert len(item.body_excerpt) == 200  # first 200 chars only


def test_ingests_all_three_item_kinds() -> None:
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(
        head_oid="same",
        issue_comments=[_issue_comment(11)],
        reviews=[_review(21)],
        review_comments=[_review_comment(31)],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    kinds = {item.kind for item in state.items}
    assert kinds == {ItemKind.ISSUE_COMMENT, ItemKind.REVIEW_SUMMARY, ItemKind.REVIEW_THREAD}


def test_duplicate_item_not_reappended_and_does_not_retrigger_phase() -> None:
    # The item already lives in state.items under the same (kind, gh_id) key.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    start.items.append(
        ReviewItem(
            kind=ItemKind.ISSUE_COMMENT,
            identity=Identity(gh_id="11"),
            author="copilot",
            body_excerpt="prior",
            seen_at=_T0,
        )
    )
    gh = _gh(head_oid="same", issue_comments=[_issue_comment(11)])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert len(state.items) == 1  # no re-append
    assert state.phase is PRPhase.AWAITING_REVIEW  # no new-item edge fired


def test_review_thread_carries_reply_to_comment_id() -> None:
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(head_oid="same", review_comments=[_review_comment(31)])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    thread = next(i for i in state.items if i.kind is ItemKind.REVIEW_THREAD)
    assert thread.identity.reply_to_comment_id == 31


# ── reviewer engagement (§4.1) ──


def test_requested_reviewer_engages_to_in_progress_on_authored_review() -> None:
    reviewers = _required_reviewer(ReviewerStatus.REQUESTED)
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    gh = _gh(head_oid="same", reviews=[_review(21, login="copilot")])
    now = _T0 + timedelta(minutes=1)
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(now), config=_config())
    rv = state.reviewers["copilot"]
    assert rv.status is ReviewerStatus.IN_PROGRESS
    assert rv.last_review_at == now


def test_terminal_reviewer_not_regressed_by_new_activity() -> None:
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    gh = _gh(head_oid="same", issue_comments=[_issue_comment(11, login="copilot")])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.reviewers["copilot"].status is ReviewerStatus.REVIEW_FOUND


# ── reviewer timeout (§4.1 auto-decline) ──


def test_requested_reviewer_past_start_timeout_auto_declines() -> None:
    reviewers = _required_reviewer(ReviewerStatus.REQUESTED)
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    # No engagement this poll; advance the clock past the default 3m start timeout.
    later = _T0 + timedelta(minutes=5)
    gh = _gh(head_oid="same")
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(later), config=_config())
    rv = state.reviewers["copilot"]
    assert rv.status is ReviewerStatus.DECLINED
    assert rv.declined_reason == "timeout-no-start"


# ── CI rollup (§4.1 G_CI input) ──


def test_ci_success_recorded() -> None:
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(head_oid="same", ci="success")
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.quiescence.ci_state == "success"


def test_ci_404_maps_to_absent() -> None:
    # The status endpoint 404s when no CI is configured for the commit → "absent".
    results = [
        _ok({"headRefOid": "same"}),
        _ok({"state": "open", "merged_at": None}),
        _ok([]),
        _ok([]),
        _ok([]),
        _gh_http_error(404, "Not Found"),
    ]
    gh = GhCli(_QueueRunner(results))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.quiescence.ci_state == "absent"


# ── merge detection ──


def test_pr_merged_moves_to_merged_regardless_of_items() -> None:
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(head_oid="same", pr_merged=True, issue_comments=[_issue_comment(11)])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.phase is PRPhase.MERGED


# ── direct idle → fixes-pending (bootstrap + item already filed) ──


def test_bootstrap_with_existing_item_jumps_to_fixes_pending() -> None:
    start = _idle_state()
    gh = _gh(head_oid="abc", issue_comments=[_issue_comment(11)])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.round == 1
    assert state.phase is PRPhase.FIXES_PENDING


# ── poll from terminal-for-CLI phases (§3.2 poll row) ──


def test_poll_from_merged_is_noop() -> None:
    # merged is graph-terminal; a poll observes nothing actionable and stays.
    start = _state(phase=PRPhase.MERGED, last_poll_sha="same")
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="same"), deps=_deps(), config=_config())
    assert state.phase is PRPhase.MERGED


def test_quiesced_external_push_reenters_awaiting_review() -> None:
    start = _state(
        phase=PRPhase.QUIESCED, round_=1, last_poll_sha="old", last_pushed_head_sha="mine"
    )
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="theirs"), deps=_deps(), config=_config())
    assert state.phase is PRPhase.AWAITING_REVIEW
    assert state.round == 2


def test_human_gated_external_push_reenters_fixes_pending() -> None:
    start = _state(
        phase=PRPhase.HUMAN_GATED, round_=1, last_poll_sha="old", last_pushed_head_sha="mine"
    )
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="theirs"), deps=_deps(), config=_config())
    assert state.phase is PRPhase.FIXES_PENDING
    assert state.round == 2


def test_quiesced_new_item_reenters_fixes_pending() -> None:
    start = _state(phase=PRPhase.QUIESCED, last_poll_sha="same")
    gh = _gh(head_oid="same", issue_comments=[_issue_comment(11)])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.phase is PRPhase.FIXES_PENDING


def test_item_with_missing_timestamp_uses_clock_now() -> None:
    # A gh comment payload missing its timestamp field falls back to clock now()
    # rather than crashing (defensive — gh shapes vary).
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    no_ts = {"id": 11, "user": {"login": "copilot"}, "body": "no timestamp"}
    now = _T0 + timedelta(minutes=3)
    gh = _gh(head_oid="same", issue_comments=[no_ts])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(now), config=_config())
    assert state.items[0].seen_at == now


# ── last_activity_at advances on observed mutation ──


def test_last_activity_advances_on_new_item() -> None:
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    now = _T0 + timedelta(minutes=2)
    gh = _gh(head_oid="same", issue_comments=[_issue_comment(11)])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(now), config=_config())
    assert state.last_activity_at == now


def test_last_activity_unchanged_on_quiet_poll() -> None:
    # Unchanged SHA, no items, CI already matches state → no activity, no advance.
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    start.quiescence = QuiescenceState(ci_state="success")
    now = _T0 + timedelta(minutes=2)
    gh = _gh(head_oid="same", ci="success")
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(now), config=_config())
    assert state.last_activity_at == _T0


# ── gh error-code mapping (read-only; §3.6/§3.7) ──


def test_transient_gh_failure_propagates_unchanged() -> None:
    # A 503 on the reviews list surfaces RUNTIME_GH_TRANSIENT from the adapter;
    # poll_pr lets it propagate unchanged (scheduler retries).
    results = [
        _ok({"headRefOid": "same"}),
        _ok({"state": "open", "merged_at": None}),
        _ok([]),  # issue comments
        _gh_http_error(503, "Service Unavailable"),  # reviews list fails
    ]
    gh = GhCli(_QueueRunner(results))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    with pytest.raises(PrgroomError) as exc:
        poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert exc.value.code is ErrorCode.RUNTIME_GH_TRANSIENT
    assert exc.value.tier is Tier.RUNTIME_TRANSIENT


def test_terminal_gh_failure_propagates_unchanged() -> None:
    # A 401 on the head-oid read surfaces RUNTIME_GH_TERMINAL; propagated as-is.
    gh = GhCli(_QueueRunner([_gh_http_error(401, "Bad credentials")]))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    with pytest.raises(PrgroomError) as exc:
        poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert exc.value.code is ErrorCode.RUNTIME_GH_TERMINAL
    assert exc.value.tier is Tier.RUNTIME_TERMINAL_USER


def test_pr_resource_404_maps_to_gh_terminal() -> None:
    # A 404 on the PR resource (PR/repo vanished mid-run) is terminal — the
    # adapter raises the typed GhNotFoundError, poll_pr maps it to RUNTIME_GH_TERMINAL.
    results = [
        _ok({"headRefOid": "same"}),
        _gh_http_error(404, "Not Found"),  # pulls/{n} 404
    ]
    gh = GhCli(_QueueRunner(results))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    with pytest.raises(PrgroomError) as exc:
        poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert exc.value.code is ErrorCode.RUNTIME_GH_TERMINAL
    assert exc.value.tier is Tier.RUNTIME_TERMINAL_USER


def test_graphql_failed_error_propagates_unchanged() -> None:
    # poll_pr issues no GraphQL in MVP, but any PrgroomError a gh call raises —
    # including RUNTIME_GRAPHQL_FAILED — must propagate untouched (no re-wrap).
    class _RaisingGh:
        def head_ref_oid(self, ref: PRRef) -> str:  # noqa: ARG002
            raise PrgroomError(tier=Tier.RUNTIME_TRANSIENT, code=ErrorCode.RUNTIME_GRAPHQL_FAILED)

        def rest(self, method: str, path: str, *, fields=None):  # noqa: ARG002
            raise AssertionError("unreachable")  # pragma: no cover

        def graphql(self, query: str, variables):  # noqa: ARG002
            raise AssertionError("unreachable")  # pragma: no cover

    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    with pytest.raises(PrgroomError) as exc:
        poll_pr(start, ref=_REF, gh=_RaisingGh(), deps=_deps(), config=_config())
    assert exc.value.code is ErrorCode.RUNTIME_GRAPHQL_FAILED
