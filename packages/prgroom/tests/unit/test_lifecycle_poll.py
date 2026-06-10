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
from tests.fakes import RecordedRunner

_REF = PRRef(owner="octo", repo="demo", number=7)
_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _ok(payload: object) -> CommandResult:
    return CommandResult(returncode=0, stdout=json.dumps(payload), stderr="")


def _gh_http_error(status: int, message: str) -> CommandResult:
    body = json.dumps({"message": message, "status": str(status)})
    return CommandResult(returncode=1, stdout=body, stderr=f"gh: {message} (HTTP {status})")


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
    return GhCli(RecordedRunner(results))


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
    gh = GhCli(RecordedRunner([_ok({"headRefOid": ""})]))
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


def _review_comment(
    cid: int, login: str = "copilot", *, in_reply_to_id: int | None = None
) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": cid,
        "user": {"login": login},
        "body": "inline nit",
        "created_at": "2026-06-09T11:06:00Z",
    }
    if in_reply_to_id is not None:
        entry["in_reply_to_id"] = in_reply_to_id
    return entry


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


def test_top_level_review_comment_has_no_parent() -> None:
    # A top-level inline comment carries no in_reply_to_id → reply_to_comment_id 0.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(head_oid="same", review_comments=[_review_comment(31)])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    thread = next(i for i in state.items if i.kind is ItemKind.REVIEW_THREAD)
    assert thread.identity.gh_id == "31"
    assert thread.identity.reply_to_comment_id == 0


def test_reply_review_comment_carries_parent_in_reply_to_id() -> None:
    # A reply comment exposes in_reply_to_id (the PARENT comment's id) — that is
    # what reply_to_comment_id records, NOT the comment's own id.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(head_oid="same", review_comments=[_review_comment(32, in_reply_to_id=31)])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    thread = next(i for i in state.items if i.kind is ItemKind.REVIEW_THREAD)
    assert thread.identity.gh_id == "32"  # the reply's own id
    assert thread.identity.reply_to_comment_id == 31  # the parent it replies to


# ── reviewer engagement (§4.1) ──


def _requested_at(login: str = "copilot", *, at: datetime) -> dict[str, ReviewerState]:
    return {
        login: ReviewerState(
            identity=login,
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.REQUESTED,
            required=True,
            last_request_at=at,
        )
    }


# The fixture activity timestamps cluster at 11:00 to 11:06Z; a poll-time just
# after keeps the §4.1 finish-timeout (15m) from tripping so engagement is isolated.
_JUST_AFTER_ACTIVITY = datetime(2026, 6, 9, 11, 10, 0, tzinfo=UTC)
# For the 11:30Z multi-verdict fixture, a poll-time within the finish window.
_JUST_AFTER_VERDICT = datetime(2026, 6, 9, 11, 35, 0, tzinfo=UTC)


def test_requested_reviewer_engages_to_in_progress_on_non_review_comment() -> None:
    # A non-review activity (issue comment) after the request window is engagement
    # but NOT a terminal verdict — the reviewer advances to in_progress (§4.1).
    reviewers = _requested_at(at=_T0 - timedelta(hours=2))  # before the 11:00Z comment
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    gh = _gh(head_oid="same", issue_comments=[_issue_comment(11, login="copilot")])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(_JUST_AFTER_ACTIVITY), config=_config())
    rv = state.reviewers["copilot"]
    assert rv.status is ReviewerStatus.IN_PROGRESS


def test_engagement_stamps_activity_time_not_poll_time() -> None:
    # §4.1: last_review_at = the activity's own created_at/submitted_at, NOT poll
    # time — otherwise a crash gap resets the stall clock and defeats auto-decline.
    reviewers = _requested_at(at=_T0 - timedelta(hours=2))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    # The issue comment's created_at is 2026-06-09T11:00:00Z; poll time (now) is later.
    activity_time = datetime(2026, 6, 9, 11, 0, 0, tzinfo=UTC)
    now = _T0 + timedelta(hours=3)
    gh = _gh(head_oid="same", issue_comments=[_issue_comment(11, login="copilot")])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(now), config=_config())
    assert state.reviewers["copilot"].last_review_at == activity_time


def test_approved_review_flips_required_reviewer_to_review_found() -> None:
    # §4.1 + sequences.md L96: an APPROVED review is a terminal verdict written by
    # _poll → REVIEW_FOUND (satisfies G_REVIEWERS).
    reviewers = _requested_at(at=_T0 - timedelta(hours=2))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    approved = _review(21, login="copilot")
    approved["state"] = "APPROVED"
    gh = _gh(head_oid="same", reviews=[approved])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.reviewers["copilot"].status is ReviewerStatus.REVIEW_FOUND


def test_changes_requested_review_flips_required_reviewer_to_review_found() -> None:
    # CHANGES_REQUESTED is equally terminal for G_REVIEWERS (the fix items it
    # produces gate via dispositions, not via reviewer status).
    reviewers = _requested_at(at=_T0 - timedelta(hours=2))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    gh = _gh(head_oid="same", reviews=[_review(21, login="copilot")])  # CHANGES_REQUESTED
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.reviewers["copilot"].status is ReviewerStatus.REVIEW_FOUND


def test_genuine_terminal_review_supersedes_a_prior_decline() -> None:
    # §4.1 reconciliation: an auto-decline (timeout-no-start / timeout-stalled) is a
    # *fallback* for a missing verdict — "requested but never engaged" / "engaged but
    # never produced a terminal review". A genuine post-request APPROVED /
    # CHANGES_REQUESTED review IS the verdict the decline stood in for, so it
    # supersedes the stale DECLINED and the reported status becomes REVIEW_FOUND.
    # (Both satisfy G_REVIEWERS, so quiescence is unaffected — only the reported
    # status changes, toward the more truthful one.)
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.DECLINED,
            required=True,
            last_request_at=_T0 - timedelta(hours=2),  # before the 11:05Z review
            declined_at=_T0 - timedelta(hours=1),
            declined_reason="timeout-no-start",
        )
    }
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    approved = _review(21, login="copilot")
    approved["state"] = "APPROVED"
    gh = _gh(head_oid="same", reviews=[approved])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(_JUST_AFTER_ACTIVITY), config=_config())
    assert state.reviewers["copilot"].status is ReviewerStatus.REVIEW_FOUND


def test_commented_review_does_not_flip_to_review_found_in_mvp() -> None:
    # §4.1 hedges the COMMENTED-terminal question to Section 5's contract; MVP
    # treats a COMMENTED review as engagement only (in_progress), not terminal.
    reviewers = _requested_at(at=_T0 - timedelta(hours=2))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    commented = _review(21, login="copilot")
    commented["state"] = "COMMENTED"
    gh = _gh(head_oid="same", reviews=[commented])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(_JUST_AFTER_ACTIVITY), config=_config())
    assert state.reviewers["copilot"].status is ReviewerStatus.IN_PROGRESS


def test_review_predating_request_does_not_flip_to_review_found() -> None:
    # A terminal review whose submitted_at predates last_request_at is pre-window
    # noise — it must not satisfy G_REVIEWERS on a stale verdict.
    reviewers = _requested_at(at=_T0 + timedelta(hours=1))  # requested AFTER the 11:05Z review
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    approved = _review(21, login="copilot")
    approved["state"] = "APPROVED"
    gh = _gh(head_oid="same", reviews=[approved])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.reviewers["copilot"].status is ReviewerStatus.REQUESTED


def test_terminal_verdict_keeps_latest_and_skips_authorless_review() -> None:
    # Two APPROVED reviews from one login (newer first, older second) must keep the
    # NEWER timestamp; a terminal review with no author login is skipped.
    newer = {
        "id": 22,
        "user": {"login": "copilot"},
        "state": "APPROVED",
        "body": "lgtm",
        "submitted_at": "2026-06-09T11:30:00Z",
    }
    older = {
        "id": 23,
        "user": {"login": "copilot"},
        "state": "APPROVED",
        "body": "earlier pass",
        "submitted_at": "2026-06-09T11:05:00Z",
    }
    authorless = {"id": 24, "user": {}, "state": "APPROVED", "submitted_at": "2026-06-09T11:40:00Z"}
    reviewers = _requested_at(at=_T0 - timedelta(hours=2))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    gh = _gh(head_oid="same", reviews=[newer, older, authorless])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(_JUST_AFTER_VERDICT), config=_config())
    rv = state.reviewers["copilot"]
    assert rv.status is ReviewerStatus.REVIEW_FOUND
    assert rv.last_review_at == datetime(2026, 6, 9, 11, 30, 0, tzinfo=UTC)  # the newer verdict


def test_terminal_reviewer_not_regressed_by_new_activity() -> None:
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    gh = _gh(head_oid="same", issue_comments=[_issue_comment(11, login="copilot")])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.reviewers["copilot"].status is ReviewerStatus.REVIEW_FOUND


def test_engaged_terminal_reviewer_refreshes_last_review_without_status_change() -> None:
    # A post-request item from a reviewer already at review_found refreshes
    # last_review_at but does NOT regress the terminal status (§4.1).
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.REVIEW_FOUND,
            required=True,
            last_request_at=_T0 - timedelta(hours=2),  # before the 11:00Z comment
        )
    }
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    now = _T0 + timedelta(minutes=1)
    gh = _gh(head_oid="same", issue_comments=[_issue_comment(11, login="copilot")])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(now), config=_config())
    rv = state.reviewers["copilot"]
    assert rv.status is ReviewerStatus.REVIEW_FOUND  # unchanged
    # Refreshed to the activity's own timestamp (the 11:00Z comment), not poll time.
    assert rv.last_review_at == datetime(2026, 6, 9, 11, 0, 0, tzinfo=UTC)


def test_item_predating_request_does_not_count_as_engagement() -> None:
    # §4.1: engagement is activity AFTER last_request_at. A stale comment authored
    # before the (re-)request window must not flip the reviewer to in_progress.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.REQUESTED,
            required=True,
            last_request_at=_T0 + timedelta(hours=1),  # requested AFTER the comment below
        )
    }
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    # The comment's created_at (_issue_comment uses 2026-06-09T11:00:00Z == _T0-1h)
    # predates last_request_at, so it is pre-window noise, not engagement.
    gh = _gh(head_oid="same", issue_comments=[_issue_comment(11, login="copilot")])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    rv = state.reviewers["copilot"]
    assert rv.status is ReviewerStatus.REQUESTED  # not advanced
    assert rv.last_review_at is None


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


def test_ci_failure_passed_through() -> None:
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(head_oid="same", ci="failure")
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.quiescence.ci_state == "failure"


def test_ci_unknown_rollup_maps_to_pending() -> None:
    # An empty/unknown combined-status state (not in {success, pending, failure})
    # is treated as pending — CI exists but is not yet a gate-satisfying verdict.
    results = [
        _ok({"headRefOid": "same"}),
        _ok({"state": "open", "merged_at": None}),
        _ok([]),
        _ok([]),
        _ok([]),
        _ok({"state": ""}),  # gh returns empty when no rollup verdict yet
    ]
    gh = GhCli(RecordedRunner(results))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.quiescence.ci_state == "pending"


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
    gh = GhCli(RecordedRunner(results))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.quiescence.ci_state == "absent"


def test_ci_error_maps_to_failure() -> None:
    # GitHub's combined-status returns state in {success, pending, failure, error};
    # an `error` rollup is a CI error, not "not yet" — map it to failure, not pending.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(head_oid="same", ci="error")
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.quiescence.ci_state == "failure"


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


def _review_found_at(verdict_at: datetime, *, requested_at: datetime) -> dict[str, ReviewerState]:
    return {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.REVIEW_FOUND,
            required=True,
            last_request_at=requested_at,
            last_review_at=verdict_at,
        )
    }


def _ingested_review_summary(rid: int, *, login: str = "copilot") -> ReviewItem:
    # The REVIEW_SUMMARY item a prior poll would already hold for review id `rid`,
    # so a steady-state re-poll re-observes the verdict without ingesting a new item.
    return ReviewItem(
        kind=ItemKind.REVIEW_SUMMARY,
        identity=Identity(gh_id=str(rid)),
        author=login,
        body_excerpt="please fix the loop",
        seen_at=datetime(2026, 6, 9, 11, 5, 0, tzinfo=UTC),
    )


def test_stable_terminal_review_quiet_poll_is_a_noop() -> None:
    # Steady state: the reviewer is already REVIEW_FOUND with last_review_at at the
    # verdict time, the verdict's REVIEW_SUMMARY item is ALREADY in state (ingested a
    # prior poll), and the SAME APPROVED review is still in the gh payload. A
    # subsequent quiet poll must be a NO-OP — engagement is idempotent — so
    # last_activity_at does NOT advance (else the idle gate could never trip and the
    # PR would never quiesce).
    verdict_at = datetime(2026, 6, 9, 11, 5, 0, tzinfo=UTC)  # the _review submitted_at
    reviewers = _review_found_at(verdict_at, requested_at=_T0 - timedelta(hours=2))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    start.quiescence = QuiescenceState(ci_state="success")
    start.items.append(_ingested_review_summary(21))  # already seen → not re-ingested
    approved = _review(21, login="copilot")
    approved["state"] = "APPROVED"
    now = _T0 + timedelta(minutes=2)
    gh = _gh(head_oid="same", reviews=[approved], ci="success")
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(now), config=_config())
    assert state.reviewers["copilot"].status is ReviewerStatus.REVIEW_FOUND
    assert state.last_activity_at == _T0  # idle clock NOT reset by a stable verdict


def test_stable_terminal_review_does_not_regress_last_review_at() -> None:
    # A newer non-review comment previously advanced last_review_at past the verdict
    # time; a later quiet poll carrying only the stable (older) terminal verdict must
    # NOT pull last_review_at back to the older verdict timestamp.
    verdict_at = datetime(2026, 6, 9, 11, 5, 0, tzinfo=UTC)
    newer_review_at = datetime(2026, 6, 9, 11, 30, 0, tzinfo=UTC)  # a later comment bumped it
    reviewers = _review_found_at(newer_review_at, requested_at=_T0 - timedelta(hours=2))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    start.quiescence = QuiescenceState(ci_state="success")
    start.items.append(_ingested_review_summary(21))  # already seen → not re-ingested
    approved = _review(21, login="copilot")  # submitted_at == verdict_at (11:05Z, older)
    approved["state"] = "APPROVED"
    now = _T0 + timedelta(minutes=2)
    gh = _gh(head_oid="same", reviews=[approved], ci="success")
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(now), config=_config())
    assert state.reviewers["copilot"].last_review_at == newer_review_at  # not regressed
    assert verdict_at < newer_review_at  # guard: the verdict really is the older time


def test_auto_decline_only_poll_does_not_advance_last_activity() -> None:
    # §4.1 (idle-timer paragraph): last_activity_at tracks PR-SIDE mutations only
    # (new comment / review / push / CI change / label change); it is explicitly
    # "not to detect bot inactivity (per-reviewer timeouts ... own that case)". An
    # auto-decline is prgroom's own internal timeout firing — NOT PR activity — so
    # it must not advance last_activity_at, or the idle gate could never trip and
    # the PR would never quiesce.
    reviewers = _required_reviewer(ReviewerStatus.REQUESTED)  # last_request_at == _T0
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    start.quiescence = QuiescenceState(ci_state="success")  # no CI-change mutation either
    # No new items; advance the clock past the 3m start timeout so the reviewer
    # auto-declines and that is the ONLY state change this poll.
    later = _T0 + timedelta(minutes=5)
    gh = _gh(head_oid="same", ci="success")
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(later), config=_config())
    assert state.reviewers["copilot"].status is ReviewerStatus.DECLINED  # the timeout fired
    assert state.last_activity_at == _T0  # but the idle clock did NOT reset


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
    gh = GhCli(RecordedRunner(results))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    with pytest.raises(PrgroomError) as exc:
        poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert exc.value.code is ErrorCode.RUNTIME_GH_TRANSIENT
    assert exc.value.tier is Tier.RUNTIME_TRANSIENT


def test_terminal_gh_failure_propagates_unchanged() -> None:
    # A 401 on the head-oid read surfaces RUNTIME_GH_TERMINAL; propagated as-is.
    gh = GhCli(RecordedRunner([_gh_http_error(401, "Bad credentials")]))
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
    gh = GhCli(RecordedRunner(results))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    with pytest.raises(PrgroomError) as exc:
        poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert exc.value.code is ErrorCode.RUNTIME_GH_TERMINAL
    assert exc.value.tier is Tier.RUNTIME_TERMINAL_USER


def test_head_oid_404_maps_to_gh_terminal_not_raw_not_found() -> None:
    # head_ref_oid is a separate 404-capable call (the FIRST gh read). A vanished
    # PR/repo must surface as PrgroomError/RUNTIME_GH_TERMINAL (the CLI only catches
    # PrgroomError) — NOT a raw GhNotFoundError that escapes as an uncaught traceback.
    gh = GhCli(RecordedRunner([_gh_http_error(404, "Not Found")]))  # head-oid 404
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    with pytest.raises(PrgroomError) as exc:
        poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert exc.value.code is ErrorCode.RUNTIME_GH_TERMINAL
    assert exc.value.tier is Tier.RUNTIME_TERMINAL_USER


def test_ingest_list_404_maps_to_gh_terminal() -> None:
    # A 404 on one of the comment/review list GETs (PR/repo vanished mid-ingest)
    # is equally terminal — blast-radius parity with the head-oid and PR-resource reads.
    results = [
        _ok({"headRefOid": "same"}),
        _ok({"state": "open", "merged_at": None}),
        _gh_http_error(404, "Not Found"),  # issue-comments list 404
    ]
    gh = GhCli(RecordedRunner(results))
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
