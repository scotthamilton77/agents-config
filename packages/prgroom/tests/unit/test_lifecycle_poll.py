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
from prgroom.lifecycle.poll import _review_activity_by_login, _terminal_review_verdicts
from prgroom.lifecycle.quiescence import reviewers_gate_satisfied
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


# The poll CI read is check-runs first, so `_gh`'s ci= knob maps to a single check run.
# success/failure/pending cover every `_gh` caller; the combined-status FALLBACK path
# (empty check runs) is exercised by the dedicated fallback tests, never by `_gh`.
_CI_TO_CHECK_RUN: dict[str, dict[str, object]] = {
    "success": {"status": "completed", "conclusion": "success"},
    "failure": {"status": "completed", "conclusion": "failure"},
    "pending": {"status": "in_progress", "conclusion": None},
}


def _ci_check_runs_read(ci: str) -> CommandResult:
    return _ok({"total_count": 1, "check_runs": [_CI_TO_CHECK_RUN[ci]]})


def _gh(
    *,
    head_oid: str = "headsha1",
    pr_merged: bool = False,
    requested_reviewers: list[str | dict[str, object]] | None = None,
    issue_comments: list[dict[str, object]] | None = None,
    reviews: list[dict[str, object]] | None = None,
    review_comments: list[dict[str, object]] | None = None,
    thread_nodes: list[dict[str, object]] | None = None,
    ci: str = "success",
) -> GhCli:
    """Build a GhCli queuing the poll reads in the order ``poll_pr`` issues them.

    When ``review_comments`` is non-empty, ``poll_pr`` issues an extra GraphQL
    ``reviewThreads`` read (the thread-id map) between the review-comments REST read
    and the CI read; ``thread_nodes`` supplies that envelope's nodes (default empty
    → every review-thread item degrades to ``thread_id == ""``).

    ``requested_reviewers`` seeds the PR resource's pending-review-request array
    (bare logins, or full gh user dicts when ``type``/bot-suffix matters).
    """
    pr = (
        {"state": "closed", "merged_at": "2026-06-09T10:00:00Z"}
        if pr_merged
        else {"state": "open", "merged_at": None}
    )
    # GitHub's pulls/{n} carries the pending review requests on the PR resource.
    # Accepts bare logins for brevity; a dict passes a full gh user object through
    # (used by the bot-classification tests).
    pr["requested_reviewers"] = [
        {"login": r} if isinstance(r, str) else r for r in (requested_reviewers or [])
    ]
    results = [
        _ok({"headRefOid": head_oid}),
        _ok(pr),
        _ok(issue_comments or []),
        _ok(reviews or []),
        _ok(review_comments or []),
    ]
    if review_comments:
        results.append(_thread_map_ok(thread_nodes or []))
    results.append(_ci_check_runs_read(ci))
    return GhCli(RecordedRunner(results))


def _gh_with_teams(*, head_oid: str, teams: list[dict[str, object]]) -> GhCli:
    """A poll-order GhCli whose PR resource carries requested_teams but no reviewers."""
    return GhCli(
        RecordedRunner(
            [
                _ok({"headRefOid": head_oid}),
                _ok(
                    {
                        "state": "open",
                        "merged_at": None,
                        "requested_reviewers": [],
                        "requested_teams": teams,
                    }
                ),
                _ok([]),  # issue comments
                _ok([]),  # reviews
                _ok([]),  # review comments
                _ci_check_runs_read("success"),
            ]
        )
    )


def _deps(now: datetime = _T0) -> Deps:
    return Deps(clock=FrozenClock(now), randomness=FixedRandomness())


def _config() -> PrgroomConfig:
    return PrgroomConfig()


def _idle_state() -> PRGroomingState:
    return bootstrap_state(_REF, now=_T0)


def _state(
    *,
    phase: PRPhase,
    retries_: int = 0,
    last_poll_sha: str = "headsha1",
    last_pushed_head_sha: str = "",
    reviewers: dict[str, ReviewerState] | None = None,
) -> PRGroomingState:
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


def test_bootstrap_non_empty_head_costs_no_retry_and_reaches_awaiting_review() -> None:
    # The initial observed push anchors the 0-indexed counter at 0 (§3.4): the
    # first review-eliciting push is free; only subsequent pushes consume retries.
    state = poll_pr(_idle_state(), ref=_REF, gh=_gh(head_oid="abc"), deps=_deps(), config=_config())
    assert state.pr_review_retries_used == 0
    assert state.last_poll_sha == "abc"
    assert state.phase is PRPhase.AWAITING_REVIEW


def test_bootstrap_empty_head_leaves_counter_zero_and_idle() -> None:
    # An empty remote HEAD short-circuits: head_ref_oid is the only gh call.
    gh = GhCli(RecordedRunner([_ok({"headRefOid": ""})]))
    state = poll_pr(_idle_state(), ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.pr_review_retries_used == 0
    assert state.last_poll_sha == ""
    assert state.phase is PRPhase.IDLE


def test_bootstrap_does_not_count_retries_spent_by_prior_pushes() -> None:
    # _push bootstrap (initial, free) plus one CLI retry may precede the first
    # successful poll; the poll bootstrap only anchors last_poll_sha — it never
    # touches the counter (§3.4: the two bootstrap branches are mutually exclusive
    # with attribution, and the initial-push anchor costs nothing).
    start = _state(phase=PRPhase.IDLE, retries_=1, last_poll_sha="", last_pushed_head_sha="abc")
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="abc"), deps=_deps(), config=_config())
    assert state.pr_review_retries_used == 1
    assert state.last_poll_sha == "abc"


# ── unchanged SHA (idempotent no-op on the push axis) ──


def test_unchanged_sha_does_not_count_a_retry_or_touch_reviewers() -> None:
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    start = _state(
        phase=PRPhase.AWAITING_REVIEW, retries_=2, last_poll_sha="same", reviewers=reviewers
    )
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="same"), deps=_deps(), config=_config())
    assert state.pr_review_retries_used == 2
    assert state.reviewers["copilot"].status is ReviewerStatus.REVIEW_FOUND


# ── CLI's own push (new_head == last_pushed_head_sha) ──


def test_cli_own_push_advances_poll_sha_without_retry_count_or_reviewer_flip() -> None:
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        retries_=2,
        last_poll_sha="old",
        last_pushed_head_sha="new",
        reviewers=reviewers,
    )
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="new"), deps=_deps(), config=_config())
    assert state.pr_review_retries_used == 2  # _push already counted it
    assert state.last_poll_sha == "new"
    # _push already flipped reviewers; _poll must leave them untouched.
    assert state.reviewers["copilot"].status is ReviewerStatus.REVIEW_FOUND


# ── external push (new_head != last_pushed_head_sha) ──


def test_external_push_counts_a_retry_and_flips_required_review_found() -> None:
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        retries_=2,
        last_poll_sha="old",
        last_pushed_head_sha="mine",
        reviewers=reviewers,
    )
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="theirs"), deps=_deps(), config=_config())
    assert state.pr_review_retries_used == 3
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
        retries_=1,
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
    assert start.pr_review_retries_used == 0
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


def test_own_posted_reply_is_not_ingested_as_new_item() -> None:
    # Recursive-self-reply fix: prgroom replied by POSTing a new issue comment whose
    # id was recorded on own_reply_id. A later poll sees that comment in the gh payload
    # but must NOT re-ingest it as a fresh review item (else it re-triages forever).
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    start.items.append(
        ReviewItem(
            kind=ItemKind.REVIEW_SUMMARY,
            identity=Identity(gh_id="21"),
            author="copilot",
            body_excerpt="please fix",
            seen_at=_T0,
            replied=True,
            own_reply_id=99001,
        )
    )
    # gh returns our own posted reply (id 99001) plus a genuinely new comment (id 12).
    gh = _gh(
        head_oid="same",
        issue_comments=[_issue_comment(99001), _issue_comment(12)],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    ingested_ids = {i.identity.gh_id for i in state.items if i.kind is ItemKind.ISSUE_COMMENT}
    assert "99001" not in ingested_ids  # our own reply dropped
    assert "12" in ingested_ids  # a different comment still ingested (no over-filter)


def test_ingest_skips_marker_bearing_comment_without_ledger_entry() -> None:
    # Verb-atomicity §6 / behavior 9 — the PR #211 recursive-echo regression guard
    # (the ledger-lost window): a crash after a POST but before persist loses
    # own_reply_id, so the ledger set cannot exclude the posted comment. The
    # idempotency marker in its body is the state-independent backstop: never
    # ingest prgroom's own posted effect, ledger or no ledger.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    marked = {
        "id": 500,
        "user": {"login": "some-bot"},
        "body": "Fixed in abc1234.\n\n<!-- prgroom:reply:issue_comment:12 -->",
        "created_at": "2026-06-09T11:00:00Z",
    }
    gh = _gh(head_oid="same", issue_comments=[marked, _issue_comment(12)])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    ingested_ids = {i.identity.gh_id for i in state.items}
    assert "500" not in ingested_ids  # marker-bearing == our own effect, dropped
    assert "12" in ingested_ids


def test_ingest_keeps_marker_free_comments_from_any_author() -> None:
    # Verb-atomicity §6 / behavior 10: strict full-grammar matching — a comment
    # merely MENTIONING "prgroom:reply" in prose (any author) still ingests.
    # Exclusion stays content-keyed, never author-keyed.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    prose = {
        "id": 600,
        "user": {"login": "copilot"},
        "body": "the prgroom:reply:issue_comment:12 marker convention looks fine to me",
        "created_at": "2026-06-09T11:00:00Z",
    }
    gh = _gh(head_oid="same", issue_comments=[prose])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert {i.identity.gh_id for i in state.items} == {"600"}


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


def _thread_map_ok(nodes: list[dict[str, object]]) -> CommandResult:
    """A gh-api-graphql reviewThreads success envelope (the thread-id map read)."""
    return _ok({"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": nodes}}}}})


def test_review_thread_item_gets_graphql_node_id_as_thread_id() -> None:
    # The core qmoz5 fix: a review-thread item's thread_id is the GraphQL PRRT_*
    # node id its comment maps to — not "" (the old floor) and not the REST id.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = GhCli(
        RecordedRunner(
            [
                _ok({"headRefOid": "same"}),
                _ok({"state": "open", "merged_at": None}),
                _ok([]),  # issue comments
                _ok([]),  # reviews
                _ok([_review_comment(31)]),  # review comments (REST databaseId 31)
                _thread_map_ok([{"id": "PRRT_x", "comments": {"nodes": [{"databaseId": 31}]}}]),
                _check_runs_ok([_check_run()]),  # CI (check runs)
            ]
        )
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    thread = next(i for i in state.items if i.kind is ItemKind.REVIEW_THREAD)
    assert thread.identity.gh_id == "31"
    assert thread.identity.thread_id == "PRRT_x"


def test_review_thread_thread_id_empty_when_unmapped() -> None:
    # A comment absent from the GraphQL map (e.g. beyond the page cap) degrades to
    # "" rather than mis-keying — the §8.2 floor, applied per-item.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = GhCli(
        RecordedRunner(
            [
                _ok({"headRefOid": "same"}),
                _ok({"state": "open", "merged_at": None}),
                _ok([]),
                _ok([]),
                _ok([_review_comment(31)]),
                _thread_map_ok([]),  # empty map → no node id for comment 31
                _check_runs_ok([_check_run()]),  # CI (check runs)
            ]
        )
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    thread = next(i for i in state.items if i.kind is ItemKind.REVIEW_THREAD)
    assert thread.identity.thread_id == ""


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
    gh = _gh(head_oid="same", requested_reviewers=["copilot"])
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


def test_ci_combined_status_unknown_rollup_maps_to_pending() -> None:
    # Fallback path: a commit with no check runs falls back to combined-status; an
    # empty/unknown state there (not success/pending/failure) is treated as pending.
    results = [
        _ok({"headRefOid": "same"}),
        _ok({"state": "open", "merged_at": None}),
        _ok([]),
        _ok([]),
        _ok([]),
        _ok({"total_count": 0, "check_runs": []}),  # no check runs → fall back
        _ok({"state": ""}),  # combined-status has no rollup verdict yet
    ]
    gh = GhCli(RecordedRunner(results))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.quiescence.ci_state == "pending"


def test_ci_check_runs_404_falls_back_to_combined_status() -> None:
    # An unexpected 404 on the check-runs endpoint is not terminal: treat it as "no
    # check runs" and fall back to combined-status rather than erroring.
    results = [
        _ok({"headRefOid": "same"}),
        _ok({"state": "open", "merged_at": None}),
        _ok([]),
        _ok([]),
        _ok([]),
        _gh_http_error(404, "Not Found"),  # check-runs 404 → fall back
        _ok({"state": "success"}),  # combined-status carries the verdict
    ]
    gh = GhCli(RecordedRunner(results))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.quiescence.ci_state == "success"


def test_ci_combined_status_error_maps_to_failure() -> None:
    # Fallback path: combined-status returns state in {success, pending, failure, error};
    # an `error` rollup is a CI error, not "not yet" — map it to failure, not pending.
    results = [
        _ok({"headRefOid": "same"}),
        _ok({"state": "open", "merged_at": None}),
        _ok([]),
        _ok([]),
        _ok([]),
        _ok({"total_count": 0, "check_runs": []}),  # no check runs → fall back
        _ok({"state": "error"}),
    ]
    gh = GhCli(RecordedRunner(results))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
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
    assert state.pr_review_retries_used == 0
    assert state.phase is PRPhase.FIXES_PENDING


# ── poll from terminal-for-CLI phases (§3.2 poll row) ──


def test_poll_from_merged_is_noop() -> None:
    # merged is graph-terminal; a poll observes nothing actionable and stays.
    start = _state(phase=PRPhase.MERGED, last_poll_sha="same")
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="same"), deps=_deps(), config=_config())
    assert state.phase is PRPhase.MERGED


def test_quiesced_external_push_reenters_awaiting_review() -> None:
    start = _state(
        phase=PRPhase.QUIESCED, retries_=1, last_poll_sha="old", last_pushed_head_sha="mine"
    )
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="theirs"), deps=_deps(), config=_config())
    assert state.phase is PRPhase.AWAITING_REVIEW
    assert state.pr_review_retries_used == 2


def test_human_gated_external_push_reenters_fixes_pending() -> None:
    start = _state(
        phase=PRPhase.HUMAN_GATED, retries_=1, last_poll_sha="old", last_pushed_head_sha="mine"
    )
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="theirs"), deps=_deps(), config=_config())
    assert state.phase is PRPhase.FIXES_PENDING
    assert state.pr_review_retries_used == 2


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
    gh = _gh(head_oid="same", ci="success", requested_reviewers=["copilot"])
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


# ── CI via check-runs (Actions-only repos) + list pagination (jkha6) ──


def _check_run(status: str = "completed", conclusion: str | None = "success") -> dict[str, object]:
    return {"status": status, "conclusion": conclusion}


def _check_runs_ok(runs: list[dict[str, object]]) -> CommandResult:
    return _ok({"total_count": len(runs), "check_runs": runs})


def _poll_reads(
    *,
    head: str = "same",
    issue_comments: list[dict[str, object]] | None = None,
    reviews: list[dict[str, object]] | None = None,
    review_comments: list[dict[str, object]] | None = None,
    thread_nodes: list[dict[str, object]] | None = None,
    trailing: list[CommandResult],
) -> list[CommandResult]:
    """The fixed head/PR/issue/reviews/review-comments prefix + caller-supplied CI reads.

    Mirrors ``_gh`` but returns the raw result list so a test can hold the
    ``RecordedRunner`` and assert on the argv (e.g. ``--paginate``). ``trailing``
    carries the CI reads: one check-runs read, plus a combined-status read only when
    the test exercises the empty-check-runs fallback.
    """
    reads = [
        _ok({"headRefOid": head}),
        _ok({"state": "open", "merged_at": None}),
        _ok(issue_comments or []),
        _ok(reviews or []),
        _ok(review_comments or []),
    ]
    if review_comments:
        reads.append(_thread_map_ok(thread_nodes or []))
    reads.extend(trailing)
    return reads


def test_ci_derives_success_from_check_runs_not_blind_combined_status() -> None:
    # The core jkha6 defect-2 fix: on an Actions-only repo the legacy combined-status
    # endpoint returns pending/total_count=0 forever. poll must read check-runs and
    # roll a completed/success run up to ci_state="success" — never blinded by (nor
    # even reading) combined-status when check runs exist.
    runner = RecordedRunner(_poll_reads(trailing=[_check_runs_ok([_check_run()])]))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(start, ref=_REF, gh=GhCli(runner), deps=_deps(), config=_config())
    assert state.quiescence.ci_state == "success"


def test_ci_check_runs_in_progress_maps_to_pending() -> None:
    runner = RecordedRunner(
        _poll_reads(trailing=[_check_runs_ok([_check_run(status="in_progress", conclusion=None)])])
    )
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(start, ref=_REF, gh=GhCli(runner), deps=_deps(), config=_config())
    assert state.quiescence.ci_state == "pending"


def test_ci_check_runs_failure_conclusion_maps_to_failure() -> None:
    runner = RecordedRunner(
        _poll_reads(trailing=[_check_runs_ok([_check_run(conclusion="failure")])])
    )
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(start, ref=_REF, gh=GhCli(runner), deps=_deps(), config=_config())
    assert state.quiescence.ci_state == "failure"


def test_ci_failed_run_wins_over_still_running_run() -> None:
    # Precedence: a definitive failure beats an in-progress run — CI won't go green.
    runner = RecordedRunner(
        _poll_reads(
            trailing=[
                _check_runs_ok(
                    [
                        _check_run(conclusion="failure"),
                        _check_run(status="in_progress", conclusion=None),
                    ]
                )
            ]
        )
    )
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(start, ref=_REF, gh=GhCli(runner), deps=_deps(), config=_config())
    assert state.quiescence.ci_state == "failure"


def test_ci_neutral_and_skipped_conclusions_count_as_success() -> None:
    runner = RecordedRunner(
        _poll_reads(
            trailing=[
                _check_runs_ok([_check_run(conclusion="neutral"), _check_run(conclusion="skipped")])
            ]
        )
    )
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(start, ref=_REF, gh=GhCli(runner), deps=_deps(), config=_config())
    assert state.quiescence.ci_state == "success"


def test_ci_falls_back_to_combined_status_when_no_check_runs() -> None:
    # A repo whose CI posts classic commit statuses (no check runs) must still work:
    # empty check-runs → fall back to the combined-status endpoint.
    runner = RecordedRunner(_poll_reads(trailing=[_check_runs_ok([]), _ok({"state": "success"})]))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(start, ref=_REF, gh=GhCli(runner), deps=_deps(), config=_config())
    assert state.quiescence.ci_state == "success"


def test_ci_absent_when_no_check_runs_and_no_combined_status() -> None:
    # Empty check-runs + a 404 on combined-status (no CI configured at all) → absent.
    runner = RecordedRunner(
        _poll_reads(trailing=[_check_runs_ok([]), _gh_http_error(404, "Not Found")])
    )
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(start, ref=_REF, gh=GhCli(runner), deps=_deps(), config=_config())
    assert state.quiescence.ci_state == "absent"


def test_list_reads_request_pagination() -> None:
    # Defect-1 fix: the three REST list reads (issue comments, reviews, review
    # comments) must pass --paginate so items beyond GitHub's 30-per-page default are
    # ingested. The single-object reads (PR resource, check-runs) must NOT paginate.
    runner = RecordedRunner(_poll_reads(trailing=[_check_runs_ok([_check_run()])]))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    poll_pr(start, ref=_REF, gh=GhCli(runner), deps=_deps(), config=_config())
    for path in (
        "repos/octo/demo/issues/7/comments",
        "repos/octo/demo/pulls/7/reviews",
        "repos/octo/demo/pulls/7/comments",
    ):
        assert any(path in call and "--paginate" in call for call in runner.calls), path
    # exactly the three list reads paginate — the PR resource and check-runs do not
    assert sum("--paginate" in call for call in runner.calls) == 3


def test_ingests_reviews_beyond_the_first_thirty() -> None:
    # Regression guard (acceptance-mandated): gh --paginate concatenates pages into
    # one array, so poll must ingest every item, not cap at 30. (PR #234 froze because
    # a re-review landed on page 4 and was never seen.)
    many = [_review(1000 + i) for i in range(35)]
    runner = RecordedRunner(_poll_reads(reviews=many, trailing=[_check_runs_ok([_check_run()])]))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(start, ref=_REF, gh=GhCli(runner), deps=_deps(), config=_config())
    assert sum(i.kind is ItemKind.REVIEW_SUMMARY for i in state.items) == 35


# ── reviewer registry reconciliation (§2.1) ──


def test_pending_request_seeds_a_required_reviewer() -> None:
    # Behavior 1: GitHub listing a pending request is the seed signal. Status is
    # REQUESTED (not NOT_REQUESTED) so rereview's refreshable set does not
    # immediately re-ask a reviewer GitHub already asked.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["alice"]),
        deps=_deps(),
        config=_config(),
    )
    alice = state.reviewers["alice"]
    assert alice.identity == "alice"
    assert alice.status is ReviewerStatus.REQUESTED
    assert alice.required is True
    assert alice.kind is ReviewerKind.HUMAN
    assert alice.last_request_at == _T0
    assert alice.last_review_at is None


@pytest.mark.parametrize(
    "user",
    [
        {"login": "copilot", "type": "Bot"},
        {"login": "copilot[bot]"},  # no type field — the defensive suffix fallback
    ],
)
def test_bot_request_object_seeds_bot_kind(user: dict[str, object]) -> None:
    # Behavior 4 (request half): classification mirrors human_review._is_bot.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[user]),
        deps=_deps(),
        config=_config(),
    )
    assert state.reviewers[str(user["login"])].kind is ReviewerKind.BOT


def test_already_known_requested_reviewer_is_left_alone() -> None:
    # Behavior 5: reconciliation is idempotent — a still-requested known reviewer is
    # not reset, re-stamped, or duplicated.
    earlier = _T0 - timedelta(hours=3)
    reviewers = _requested_at(at=earlier)
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"]),
        deps=_deps(),
        config=_config(),
    )
    assert len(state.reviewers) == 1
    assert state.reviewers["copilot"].last_request_at == earlier  # not re-stamped


def test_requested_teams_are_read_and_ignored() -> None:
    # Behavior 10: team objects carry a slug, not members, and GitHub attributes
    # reviews to individual logins — so a team entry seeds nothing.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh_with_teams(head_oid="same", teams=[{"slug": "platform"}])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.reviewers == {}


def test_seeding_a_reviewer_advances_last_activity() -> None:
    # Behavior 11 (seed half): a newly-discovered reviewer is PR-side activity.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    start.quiescence = QuiescenceState(ci_state="success")
    later = _T0 + timedelta(minutes=5)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", ci="success", requested_reviewers=["alice"]),
        deps=_deps(later),
        config=_config(),
    )
    assert state.last_activity_at == later


def test_quiet_reviewer_poll_does_not_advance_last_activity() -> None:
    # Behavior 11 (no-noise half): an unchanged reviewer set is not activity, or the
    # idle gate could never trip.
    reviewers = _requested_at(at=_T0 - timedelta(minutes=1))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    start.quiescence = QuiescenceState(ci_state="success")
    later = _T0 + timedelta(minutes=1)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", ci="success", requested_reviewers=["copilot"]),
        deps=_deps(later),
        config=_config(),
    )
    assert state.last_activity_at == _T0


def test_first_poll_after_response_seeds_a_terminal_reviewer() -> None:
    # Behavior 2 — the critical regression guard. GitHub drops a reviewer from
    # requested_reviewers the moment they submit, so on a first poll AFTER a fast
    # reviewer responded, the pending-request array is the wrong (empty) signal and
    # the reviews collection is the only one carrying them.
    review_at = "2026-06-09T11:00:00Z"
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(
        head_oid="same",
        requested_reviewers=[],  # already cleared by GitHub
        reviews=[
            {
                "id": 900,
                "state": "APPROVED",
                "submitted_at": review_at,
                "user": {"login": "alice"},
                "body": "lgtm",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    alice = state.reviewers["alice"]
    assert alice.status is ReviewerStatus.REVIEW_FOUND
    assert alice.last_review_at == datetime(2026, 6, 9, 11, 0, 0, tzinfo=UTC)
    # last_request_at is backdated to the review, NOT poll time: _observe_engagement
    # only counts activity STRICTLY newer than last_request_at, so stamping `now`
    # would make this very review permanently fail that comparison.
    assert alice.last_request_at == datetime(2026, 6, 9, 11, 0, 0, tzinfo=UTC)


def test_first_poll_after_commented_response_seeds_in_progress() -> None:
    # Behavior 3: COMMENTED is not terminal in this codebase's MVP model
    # (_TERMINAL_REVIEW_STATES), so it seeds engagement — never REVIEW_FOUND, and
    # never a decline.
    #
    # Uses _JUST_AFTER_ACTIVITY (not the default _deps() clock, 50+ minutes later)
    # so evaluate_reviewer_timeouts's stalled-decline check — which fires on any
    # IN_PROGRESS reviewer whose last_review_at is older than review_finish_timeout
    # (15 min default) — does not immediately re-decline the reviewer this same
    # poll seeds; see test_commented_review_does_not_flip_to_review_found_in_mvp for
    # the identical convention on the pre-existing-reviewer path.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(
        head_oid="same",
        reviews=[
            {
                "id": 901,
                "state": "COMMENTED",
                "submitted_at": "2026-06-09T11:00:00Z",
                "user": {"login": "alice"},
                "body": "one thought",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(_JUST_AFTER_ACTIVITY), config=_config())
    assert state.reviewers["alice"].status is ReviewerStatus.IN_PROGRESS


def test_review_object_seeds_bot_kind() -> None:
    # Behavior 4 (review half): same classification path from a review's user object.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(
        head_oid="same",
        reviews=[
            {
                "id": 902,
                "state": "APPROVED",
                "submitted_at": "2026-06-09T11:00:00Z",
                "user": {"login": "copilot", "type": "Bot"},
                "body": "lgtm",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.reviewers["copilot"].kind is ReviewerKind.BOT


def test_drive_by_reviewer_is_not_required() -> None:
    # Behavior 15: `required` tracks GitHub actually ASKING. A login that reviewed
    # uninvited must not gain the power to block quiescence just by having an opinion.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(
        head_oid="same",
        requested_reviewers=[],
        reviews=[
            {
                "id": 903,
                "state": "COMMENTED",
                "submitted_at": "2026-06-09T11:00:00Z",
                "user": {"login": "randomdev"},
                "body": "drive-by",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.reviewers["randomdev"].required is False
    assert reviewers_gate_satisfied(state) is True  # an optional reviewer never gates


def test_pending_request_outranks_historical_verdict_on_seed() -> None:
    # Behavior 17 (Codex P2 regression guard): GitHub removes a login from
    # requested_reviewers the instant it submits ANY review, so a first-seen login
    # STILL present in requested_reviewers that ALSO carries an older APPROVED verdict
    # can only mean the request post-dates that verdict — a re-request whose fresh
    # review is still pending. Seed REQUESTED at `now` (NOT REVIEW_FOUND from the stale
    # verdict), keeping `required` True so the gate stays UNSATISFIED. The review's
    # 11:00Z timestamp (_T0 - 1h) is older than poll time, so _observe_engagement's
    # "strictly after last_request_at" gate cannot revive the historical verdict either.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(
        head_oid="same",
        requested_reviewers=["alice"],
        reviews=[
            {
                "id": 904,
                "state": "APPROVED",
                "submitted_at": "2026-06-09T11:00:00Z",  # _T0 - 1h, before `now`
                "user": {"login": "alice"},
                "body": "lgtm",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    alice = state.reviewers["alice"]
    assert alice.required is True
    assert alice.status is ReviewerStatus.REQUESTED  # fresh request wins over verdict
    assert alice.last_request_at == _T0  # stamped `now`, not backdated to the review
    assert reviewers_gate_satisfied(state) is False  # the wanted re-review is pending


def _declined(reason: str, *, login: str = "copilot") -> dict[str, ReviewerState]:
    return {
        login: ReviewerState(
            identity=login,
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.DECLINED,
            required=True,
            last_request_at=_T0 - timedelta(hours=2),
            declined_at=_T0 - timedelta(hours=1),
            declined_reason=reason,
        )
    }


def test_withdrawn_reviewer_reactivates_when_re_requested() -> None:
    # Behavior 6: request-withdrawn is the one decline reason DEFINED by an observed
    # absence, so a later reappearance is a genuine transition worth re-arming.
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="same",
        reviewers=_declined("request-withdrawn"),
    )
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"]),
        deps=_deps(),
        config=_config(),
    )
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.REQUESTED
    assert copilot.last_request_at == _T0
    assert copilot.declined_at is None
    assert copilot.declined_reason is None


def test_withdrawn_reviewer_reactivates_to_review_found_on_fresh_verdict() -> None:
    # A withdrawn reviewer re-requested this poll who ALSO submitted a terminal review in
    # the window between the PR-resource GET and the later reviews GET is genuine fresh
    # engagement (its timestamp post-dates the recorded withdrawal at declined_at).
    # Reactivate straight into REVIEW_FOUND with request/review stamps backdated to the
    # verdict, so _observe_engagement's strictly-after gate does not then permanently
    # reject the now-historical review poll after poll. Invariant (1): fresh
    # post-withdrawal engagement is never permanently rejected.
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="same",
        reviewers=_declined("request-withdrawn"),  # declined_at = _T0 - 1h = 11:00Z
    )
    fresh_verdict = {
        "id": 31,
        "user": {"login": "copilot"},
        "state": "APPROVED",
        "body": "lgtm",
        "submitted_at": "2026-06-09T11:30:00Z",  # AFTER the 11:00Z withdrawal
    }
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"], reviews=[fresh_verdict]),
        deps=_deps(),
        config=_config(),
    )
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.REVIEW_FOUND
    assert copilot.last_review_at == datetime(2026, 6, 9, 11, 30, tzinfo=UTC)
    assert copilot.last_request_at == datetime(2026, 6, 9, 11, 30, tzinfo=UTC)
    assert copilot.declined_at is None
    assert copilot.declined_reason is None
    assert reviewers_gate_satisfied(state) is True


def test_withdrawn_reviewer_reactivates_to_requested_on_historical_verdict() -> None:
    # Invariant (2): a review whose timestamp PREDATES the recorded withdrawal is a
    # pre-withdrawal historical verdict, not the fresh re-review the new request wants.
    # It must NOT satisfy the fresh request — reactivate to REQUESTED at `now`, leaving
    # the gate unsatisfied until the wanted review actually lands (mirrors the
    # requested-wins rule _seed_reviewer applies to a first-seen re-request).
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="same",
        reviewers=_declined("request-withdrawn"),  # declined_at = _T0 - 1h = 11:00Z
    )
    historical_verdict = {
        "id": 32,
        "user": {"login": "copilot"},
        "state": "APPROVED",
        "body": "lgtm",
        "submitted_at": "2026-06-09T10:30:00Z",  # BEFORE the 11:00Z withdrawal
    }
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"], reviews=[historical_verdict]),
        deps=_deps(),
        config=_config(),
    )
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.REQUESTED
    assert copilot.last_request_at == _T0
    assert copilot.declined_at is None
    assert copilot.declined_reason is None
    assert reviewers_gate_satisfied(state) is False


def test_withdrawn_reviewer_reactivates_to_in_progress_on_fresh_comment() -> None:
    # Fresh NON-terminal engagement (a COMMENTED review after the withdrawal) reopens the
    # reviewer as IN_PROGRESS rather than REQUESTED — they are actively engaged again —
    # while still leaving the gate unsatisfied (no terminal verdict yet).
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="same",
        reviewers=_declined("request-withdrawn"),  # declined_at = _T0 - 1h = 11:00Z
    )
    fresh_comment = {
        "id": 33,
        "user": {"login": "copilot"},
        "state": "COMMENTED",
        "body": "still looking",
        # AFTER the 11:00Z withdrawal and within the 15m finish timeout of `now` (12:00Z),
        # so the same-poll timeout pass does not immediately re-stall the reopened reviewer.
        "submitted_at": "2026-06-09T11:50:00Z",
    }
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"], reviews=[fresh_comment]),
        deps=_deps(),
        config=_config(),
    )
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.IN_PROGRESS
    assert copilot.last_review_at == datetime(2026, 6, 9, 11, 50, tzinfo=UTC)
    assert copilot.declined_at is None
    assert copilot.declined_reason is None
    assert reviewers_gate_satisfied(state) is False


def test_post_withdrawal_drive_by_across_polls_does_not_satisfy_a_later_re_request() -> None:
    # The multi-poll drive-by: a withdrawn reviewer submits a drive-by review that the
    # reconciler observes on an intermediate poll (still withdrawn, before any
    # re-request), then the operator re-requests on a later poll. Because the review
    # PREDATES the re-request, it must NOT promote the reviewer to REVIEW_FOUND — the
    # re-request wants a fresh review the drive-by cannot stand in for. The gate must end
    # UNSATISFIED (REQUESTED). requested_reviewers carries no request timestamp, so the
    # ordering is established structurally: the drive-by's timestamp is recorded on
    # last_review_at when first observed while withdrawn, and the later reactivation then
    # sees terminal_at NOT strictly after that boundary.
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="same",
        reviewers=_declined("request-withdrawn"),  # declined_at = _T0 - 1h = 11:00Z
    )
    drive_by = {
        "id": 34,
        "user": {"login": "copilot"},
        "state": "APPROVED",
        "body": "lgtm",
        "submitted_at": "2026-06-09T11:30:00Z",  # AFTER the 11:00Z withdrawal
    }
    # Intermediate poll: drive-by observed while STILL withdrawn (login not re-requested).
    mid = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[], reviews=[drive_by]),
        deps=_deps(_T0 - timedelta(minutes=29)),  # 11:31Z
        config=_config(),
    )
    copilot_mid = mid.reviewers["copilot"]
    # A drive-by against a pulled request does not resurrect the reviewer, but its
    # timestamp is recorded so the later re-request can be ordered against it.
    assert copilot_mid.status is ReviewerStatus.DECLINED
    assert copilot_mid.declined_reason == "request-withdrawn"
    assert copilot_mid.last_review_at == datetime(2026, 6, 9, 11, 30, tzinfo=UTC)

    # Later poll: operator re-requests. The stale drive-by must not satisfy it.
    final = poll_pr(
        mid,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"], reviews=[drive_by]),
        deps=_deps(_T0 - timedelta(minutes=28)),  # 11:32Z
        config=_config(),
    )
    copilot = final.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.REQUESTED
    assert copilot.declined_at is None
    assert copilot.declined_reason is None
    assert reviewers_gate_satisfied(final) is False


def test_re_requested_reviewer_after_drive_by_still_times_out() -> None:
    # Recovery guard for the fix above: a reviewer reactivated to REQUESTED after a stale
    # drive-by must not be permanently stuck. Clearing last_review_at on reactivation
    # keeps the review-start timeout (which only fires on last_review_at is None) alive,
    # so a re-requested reviewer who never delivers the wanted fresh review still auto-
    # declines and the PR can quiesce — the drive-by does not disable the stall clock.
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="same",
        reviewers=_declined("request-withdrawn"),  # declined_at = _T0 - 1h = 11:00Z
    )
    drive_by = {
        "id": 34,
        "user": {"login": "copilot"},
        "state": "APPROVED",
        "body": "lgtm",
        "submitted_at": "2026-06-09T11:30:00Z",
    }
    mid = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[], reviews=[drive_by]),
        deps=_deps(_T0 - timedelta(minutes=29)),  # 11:31Z
        config=_config(),
    )
    reactivated = poll_pr(
        mid,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"], reviews=[drive_by]),
        deps=_deps(_T0 - timedelta(minutes=28)),  # 11:32Z — REQUESTED, last_review_at cleared
        config=_config(),
    )
    assert reactivated.reviewers["copilot"].last_review_at is None
    # No fresh review lands; > review_start_timeout (3m) after the 11:32Z re-request.
    final = poll_pr(
        reactivated,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"], reviews=[drive_by]),
        deps=_deps(_T0 - timedelta(minutes=24)),  # 11:36Z
        config=_config(),
    )
    copilot = final.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.DECLINED
    assert copilot.declined_reason == "timeout-no-start"
    assert reviewers_gate_satisfied(final) is True


@pytest.mark.parametrize("reason", ["timeout-no-start", "timeout-stalled"])
def test_timeout_declined_reviewer_does_not_reactivate(reason: str) -> None:
    # Behavior 14 — the GLM critical regression guard. A timeout decline is a purely
    # LOCAL mutation (quiescence._decline makes no gh call), so the reviewer is still
    # listed in requested_reviewers every poll, forever. Reactivating on bare presence
    # would undo the decline within the same cycle it fired, making the timeout gate
    # impossible to durably satisfy and the PR impossible to quiesce.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=_declined(reason))
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"]),
        deps=_deps(),
        config=_config(),
    )
    assert state.reviewers["copilot"].status is ReviewerStatus.DECLINED
    assert state.reviewers["copilot"].declined_reason == reason


def test_timeout_declined_reviewer_still_satisfies_the_gate_across_polls() -> None:
    # The consequence behavior 14 protects: with the decline intact, G_REVIEWERS
    # passes and the PR can actually reach quiescence.
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="same",
        reviewers=_declined("timeout-no-start"),
    )
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"]),
        deps=_deps(),
        config=_config(),
    )
    assert reviewers_gate_satisfied(state) is True


def test_drive_by_review_found_promoted_and_rewindowed_when_formally_requested() -> None:
    # The reported gap: a drive-by (required=False) who later lands in
    # requested_reviewers is a NEW ask. GitHub drops a login from requested_reviewers
    # the instant it reviews, so a REVIEW_FOUND entry re-listed there is a re-request.
    # Promote to required AND restart the window (clearing last_review_at) so the gate
    # blocks on the pending re-review rather than passing on the stale verdict.
    reviewers = {
        "randomdev": ReviewerState(
            identity="randomdev",
            kind=ReviewerKind.HUMAN,
            status=ReviewerStatus.REVIEW_FOUND,
            required=False,
            last_request_at=_T0 - timedelta(hours=2),
            last_review_at=_T0 - timedelta(hours=2),
        )
    }
    start = _state(phase=PRPhase.QUIESCED, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["randomdev"]),
        deps=_deps(),
        config=_config(),
    )
    rv = state.reviewers["randomdev"]
    assert rv.required is True
    assert rv.status is ReviewerStatus.REQUESTED
    assert rv.last_request_at == _T0
    assert rv.last_review_at is None
    assert reviewers_gate_satisfied(state) is False


def test_required_review_found_reviewer_rewindowed_when_re_requested() -> None:
    # A formally-required reviewer who already reviewed and is re-listed in
    # requested_reviewers gets a fresh request window — the operator wants a new review
    # of new work, and the gate must not stay satisfied on the prior verdict.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.REVIEW_FOUND,
            required=True,
            last_request_at=_T0 - timedelta(hours=2),
            last_review_at=_T0 - timedelta(hours=1),
        )
    }
    start = _state(phase=PRPhase.QUIESCED, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"]),
        deps=_deps(),
        config=_config(),
    )
    rv = state.reviewers["copilot"]
    assert rv.required is True
    assert rv.status is ReviewerStatus.REQUESTED
    assert rv.last_request_at == _T0
    assert rv.last_review_at is None
    assert reviewers_gate_satisfied(state) is False


def test_not_requested_required_reviewer_rewindowed_when_github_re_requests() -> None:
    # NOT_REQUESTED is a post-push flip awaiting re-ask. If GitHub itself already lists
    # the reviewer in requested_reviewers (an operator re-requested before prgroom's
    # rereview ran), that presence is the new ask: move to REQUESTED at `now` and clear
    # the stale invalidated-review stamp so the start timeout can still fire.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.NOT_REQUESTED,
            required=True,
            last_request_at=_T0 - timedelta(hours=2),
            last_review_at=_T0 - timedelta(hours=1),
        )
    }
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"]),
        deps=_deps(),
        config=_config(),
    )
    rv = state.reviewers["copilot"]
    assert rv.status is ReviewerStatus.REQUESTED
    assert rv.last_request_at == _T0
    assert rv.last_review_at is None
    assert reviewers_gate_satisfied(state) is False


def test_review_found_reviewer_rewindow_keeps_a_same_poll_fresh_verdict() -> None:
    # The bb92bde window-restart carries the same same-poll race the withdrawn-
    # reactivation path already handles: a NEW review can land between the PR-resource GET
    # (still listing the login as pending) and the later reviews GET. Restarting to
    # REQUESTED at `now` and clearing last_review_at would strand it — a second-precision
    # timestamp in the same second as `now` is not strictly greater than the freshly
    # stamped last_request_at, so _observe_engagement rejects it and the next poll reads
    # the absent request as a withdrawal. Order this poll's activity against the PRIOR
    # last_review_at instead: a verdict newer than it is fresh post-re-request engagement
    # → REVIEW_FOUND with both stamps backdated to the review.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.REVIEW_FOUND,
            required=True,
            last_request_at=_T0 - timedelta(hours=3),
            last_review_at=_T0 - timedelta(hours=2),
        )
    }
    fresh_verdict = {
        "id": 41,
        "user": {"login": "copilot"},
        "state": "CHANGES_REQUESTED",
        "body": "needs work",
        "submitted_at": "2026-06-09T12:00:00Z",  # same second as `now` — the race window
    }
    start = _state(phase=PRPhase.QUIESCED, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"], reviews=[fresh_verdict]),
        deps=_deps(),
        config=_config(),
    )
    rv = state.reviewers["copilot"]
    assert rv.status is ReviewerStatus.REVIEW_FOUND
    assert rv.last_review_at == _T0
    assert rv.last_request_at == _T0
    assert reviewers_gate_satisfied(state) is True


def test_review_found_reviewer_rewindow_rejects_a_historical_verdict() -> None:
    # The invariant bb92bde established must survive the fresh-verdict handling: the OLD
    # review that made the reviewer REVIEW_FOUND (timestamp == prior last_review_at) is
    # NOT newer than the boundary, so it is a historical verdict, not the re-review the
    # new ask wants. Restart to REQUESTED at `now`, clear last_review_at, gate unsatisfied.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.REVIEW_FOUND,
            required=True,
            last_request_at=_T0 - timedelta(hours=3),
            last_review_at=datetime(2026, 6, 9, 10, 0, tzinfo=UTC),
        )
    }
    historical_verdict = {
        "id": 42,
        "user": {"login": "copilot"},
        "state": "APPROVED",
        "body": "lgtm",
        "submitted_at": "2026-06-09T10:00:00Z",  # == prior last_review_at, not fresh
    }
    start = _state(phase=PRPhase.QUIESCED, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"], reviews=[historical_verdict]),
        deps=_deps(),
        config=_config(),
    )
    rv = state.reviewers["copilot"]
    assert rv.status is ReviewerStatus.REQUESTED
    assert rv.last_request_at == _T0
    assert rv.last_review_at is None
    assert reviewers_gate_satisfied(state) is False


def test_review_found_reviewer_rewindow_keeps_a_same_second_fresh_verdict_by_review_id() -> None:
    # Same-second collision: a genuinely fresh re-review submitted in the SAME GitHub
    # timestamp second as the prior verdict lands with `terminal_at == boundary`, so a
    # strict `>` would misfile it as historical, reset to REQUESTED, and let the next poll
    # read the post-review absence as a withdrawal — excluding the reviewer. Review id is
    # the tiebreaker: the fresh review's id (41) strictly exceeds the stored last_review_id
    # (40), so it is accepted as fresh → REVIEW_FOUND, gate satisfied.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.REVIEW_FOUND,
            required=True,
            last_request_at=_T0 - timedelta(hours=3),
            last_review_at=_T0,  # same second as the fresh verdict below
            last_review_id=40,
        )
    }
    fresh_verdict = {
        "id": 41,  # monotonic: a NEW submission, strictly greater than the stored 40
        "user": {"login": "copilot"},
        "state": "CHANGES_REQUESTED",
        "body": "needs work",
        "submitted_at": "2026-06-09T12:00:00Z",  # == prior last_review_at, distinct id
    }
    start = _state(phase=PRPhase.QUIESCED, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"], reviews=[fresh_verdict]),
        deps=_deps(),
        config=_config(),
    )
    rv = state.reviewers["copilot"]
    assert rv.status is ReviewerStatus.REVIEW_FOUND
    assert rv.last_review_at == _T0
    assert rv.last_request_at == _T0
    assert rv.last_review_id == 41
    assert reviewers_gate_satisfied(state) is True


def test_review_found_reviewer_rewindow_rejects_same_second_reobserved_verdict_by_id() -> None:
    # The bb92bde regression guard under second-precision: the SAME review (id 42)
    # re-observed at the SAME timestamp as the prior last_review_at is steady-state
    # noise, not a fresh re-review. Its id equals the stored last_review_id, so it does
    # NOT exceed the boundary → historical → reset to REQUESTED, gate unsatisfied.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.REVIEW_FOUND,
            required=True,
            last_request_at=_T0 - timedelta(hours=3),
            last_review_at=_T0,
            last_review_id=42,
        )
    }
    reobserved_verdict = {
        "id": 42,  # identical id — the same review seen again this poll
        "user": {"login": "copilot"},
        "state": "APPROVED",
        "body": "lgtm",
        "submitted_at": "2026-06-09T12:00:00Z",  # == prior last_review_at, same id
    }
    start = _state(phase=PRPhase.QUIESCED, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"], reviews=[reobserved_verdict]),
        deps=_deps(),
        config=_config(),
    )
    rv = state.reviewers["copilot"]
    assert rv.status is ReviewerStatus.REQUESTED
    assert rv.last_request_at == _T0
    assert rv.last_review_at is None
    assert rv.last_review_id is None
    assert reviewers_gate_satisfied(state) is False


def _same_second_review(
    review_id: object, state: str, *, ts: str = "2026-06-09T12:00:00Z"
) -> dict[str, object]:
    return {
        "id": review_id,
        "user": {"login": "copilot"},
        "state": state,
        "body": "review body",
        "submitted_at": ts,
    }


def test_terminal_verdict_reducer_breaks_equal_timestamp_tie_by_larger_review_id() -> None:
    # GitHub returns reviews oldest-first, so a timestamp-only reducer retains the OLDER id
    # (40) at an equal second and hands it to the reactivation freshness test, which then
    # rejects the fresh same-second re-review. The reducer must keep the numerically larger
    # id (41) — the genuinely newer submission — regardless of response order.
    old_to_new = [_same_second_review(40, "APPROVED"), _same_second_review(41, "CHANGES_REQUESTED")]
    assert _terminal_review_verdicts(old_to_new, now=_T0)["copilot"] == (_T0, 41)
    assert _terminal_review_verdicts(list(reversed(old_to_new)), now=_T0)["copilot"] == (_T0, 41)


def test_terminal_verdict_reducer_equal_timestamp_id_none_handling_is_fail_closed() -> None:
    known = _same_second_review(40, "APPROVED")
    missing = _same_second_review(None, "APPROVED")
    # A known id displaces a first-seen missing id; a missing id never displaces a known one.
    assert _terminal_review_verdicts([missing, known], now=_T0)["copilot"] == (_T0, 40)
    assert _terminal_review_verdicts([known, missing], now=_T0)["copilot"] == (_T0, 40)
    # Neither side carries an id: keep the first-seen entry (nothing to disambiguate).
    assert _terminal_review_verdicts([missing, missing], now=_T0)["copilot"] == (_T0, None)


def test_review_activity_reducer_breaks_equal_timestamp_tie_by_larger_review_id() -> None:
    old_to_new = [_same_second_review(40, "COMMENTED"), _same_second_review(41, "COMMENTED")]
    ts, _user, rid = _review_activity_by_login(old_to_new, now=_T0)["copilot"]
    assert (ts, rid) == (_T0, 41)
    ts_r, _user_r, rid_r = _review_activity_by_login(list(reversed(old_to_new)), now=_T0)["copilot"]
    assert (ts_r, rid_r) == (_T0, 41)


def test_review_activity_reducer_equal_timestamp_id_none_handling_is_fail_closed() -> None:
    known = _same_second_review(40, "COMMENTED")
    missing = _same_second_review(None, "COMMENTED")
    assert _review_activity_by_login([missing, known], now=_T0)["copilot"][2] == 40
    assert _review_activity_by_login([known, missing], now=_T0)["copilot"][2] == 40
    assert _review_activity_by_login([missing, missing], now=_T0)["copilot"][2] is None


def test_rewindow_keeps_same_second_fresh_verdict_when_response_also_carries_prior_verdict() -> (
    None
):
    # Full-path guard for the reducer tiebreaker: when the reviews response carries BOTH the
    # prior verdict (id 40) and a genuinely fresh terminal re-review (id 41) in the same
    # second, GitHub's old-to-new order makes a timestamp-only reducer hand the OLD id 40 to
    # _reactivation_engagement, which compares 40 vs the stored 40 and rejects the fresh
    # review — resetting the renewed request to REQUESTED. The reviewer must be promoted on
    # id 41 and the gate satisfied.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.REVIEW_FOUND,
            required=True,
            last_request_at=_T0 - timedelta(hours=3),
            last_review_at=_T0,  # same second as both reviews below
            last_review_id=40,
        )
    }
    prior_verdict = _same_second_review(40, "APPROVED")
    fresh_verdict = _same_second_review(41, "CHANGES_REQUESTED")
    start = _state(phase=PRPhase.QUIESCED, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(
            head_oid="same",
            requested_reviewers=["copilot"],
            reviews=[prior_verdict, fresh_verdict],  # old-to-new, the natural GitHub order
        ),
        deps=_deps(),
        config=_config(),
    )
    rv = state.reviewers["copilot"]
    assert rv.status is ReviewerStatus.REVIEW_FOUND
    assert rv.last_review_id == 41
    assert reviewers_gate_satisfied(state) is True


def test_rewindow_same_second_fresh_verdict_is_response_order_independent() -> None:
    # Control for the fix above: reversing the response (new-to-old) must yield the same
    # promotion — the reducer keeps the larger id either way, so the outcome does not depend
    # on which order GitHub happens to return the two same-second reviews in.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.REVIEW_FOUND,
            required=True,
            last_request_at=_T0 - timedelta(hours=3),
            last_review_at=_T0,
            last_review_id=40,
        )
    }
    start = _state(phase=PRPhase.QUIESCED, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(
            head_oid="same",
            requested_reviewers=["copilot"],
            reviews=[
                _same_second_review(41, "CHANGES_REQUESTED"),
                _same_second_review(40, "APPROVED"),
            ],  # new-to-old
        ),
        deps=_deps(),
        config=_config(),
    )
    rv = state.reviewers["copilot"]
    assert rv.status is ReviewerStatus.REVIEW_FOUND
    assert rv.last_review_id == 41
    assert reviewers_gate_satisfied(state) is True


def test_commented_review_advance_stamps_its_own_review_id() -> None:
    # A COMMENTED review (non-terminal) with a body is ingested as a REVIEW_SUMMARY item
    # and advances last_review_at to its own timestamp. last_review_id must advance to
    # THAT review's own id (50), not stay pinned to an older terminal verdict (40): a
    # stale id would later let the reactivation freshness test read a re-observed
    # historical comment as fresh engagement.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.IN_PROGRESS,
            required=True,
            last_request_at=_T0 - timedelta(hours=2),
            last_review_at=datetime(2026, 6, 9, 10, 0, tzinfo=UTC),  # an older verdict
            last_review_id=40,
        )
    }
    commented = _review(50, login="copilot")
    commented["state"] = "COMMENTED"
    commented["submitted_at"] = "2026-06-09T11:05:00Z"  # newer than the stored verdict
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", reviews=[commented]),
        deps=_deps(),
        config=_config(),
    )
    rv = state.reviewers["copilot"]
    assert rv.last_review_at == datetime(2026, 6, 9, 11, 5, tzinfo=UTC)
    assert rv.last_review_id == 50  # stamped to the COMMENTED review, not left at 40


def test_issue_comment_advance_preserves_stored_review_id() -> None:
    # Negative control: a plain issue comment is not a review. It advances last_review_at
    # (activity), but must leave last_review_id untouched — neither restamped to the
    # comment id nor cleared — so a prior review's id survives to anchor the reactivation
    # freshness test.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.IN_PROGRESS,
            required=True,
            last_request_at=_T0 - timedelta(hours=2),
            last_review_at=datetime(2026, 6, 9, 10, 0, tzinfo=UTC),
            last_review_id=40,
        )
    }
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", issue_comments=[_issue_comment(11)]),  # 11:00Z, newer
        deps=_deps(),
        config=_config(),
    )
    rv = state.reviewers["copilot"]
    assert rv.last_review_at == datetime(2026, 6, 9, 11, 0, tzinfo=UTC)  # advanced
    assert rv.last_review_id == 40  # untouched — a comment carries no review id


def test_commented_drive_by_id_blocks_false_fresh_reactivation() -> None:
    # Full harm chain. A withdrawn reviewer's COMMENTED drive-by advances last_review_at
    # to the comment's timestamp; last_review_id must advance to THAT review's id (200),
    # not stay pinned to an older terminal verdict (100). When GitHub later re-requests the
    # reviewer and the SAME comment is re-observed in the same second as the boundary, the
    # reactivation freshness test must read it as the historical review it is — id 200 does
    # not exceed the stored 200 — and reset to REQUESTED, not mistake it for fresh
    # post-request engagement that silently satisfies the new request.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.DECLINED,
            required=True,
            last_request_at=_T0 - timedelta(hours=3),
            last_review_at=datetime(2026, 6, 9, 10, 0, tzinfo=UTC),
            last_review_id=100,  # an older terminal verdict
            declined_at=datetime(2026, 6, 9, 10, 30, tzinfo=UTC),
            declined_reason="request-withdrawn",
        )
    }
    commented = _review(200, login="copilot")
    commented["state"] = "COMMENTED"
    commented["submitted_at"] = "2026-06-09T11:00:00Z"  # drive-by after the withdrawal
    start = _state(phase=PRPhase.QUIESCED, last_poll_sha="same", reviewers=reviewers)

    # Poll 1: the drive-by comment lands while the reviewer is still withdrawn.
    mid = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", reviews=[commented]),
        deps=_deps(),
        config=_config(),
    )
    rv_mid = mid.reviewers["copilot"]
    assert rv_mid.status is ReviewerStatus.DECLINED  # a drive-by does not reactivate
    assert rv_mid.last_review_at == datetime(2026, 6, 9, 11, 0, tzinfo=UTC)
    assert rv_mid.last_review_id == 200  # stamped to the comment, not left at 100

    # Poll 2: GitHub re-requests the reviewer and the SAME comment is re-observed.
    end = poll_pr(
        mid,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"], reviews=[commented]),
        deps=_deps(),
        config=_config(),
    )
    rv_end = end.reviewers["copilot"]
    assert rv_end.status is ReviewerStatus.REQUESTED  # historical comment, NOT fresh
    assert reviewers_gate_satisfied(end) is False


def test_not_requested_reviewer_rewindow_keeps_a_same_poll_fresh_verdict() -> None:
    # The NOT_REQUESTED post-push-flip flavor carries the same race. A reviewer flipped to
    # NOT_REQUESTED (last_review_at retained from the invalidated verdict) that GitHub
    # re-lists AND that submits a fresh verdict this same poll reactivates straight into
    # REVIEW_FOUND, not a restart-to-REQUESTED that would strand the verdict.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.NOT_REQUESTED,
            required=True,
            last_request_at=_T0 - timedelta(hours=3),
            last_review_at=_T0 - timedelta(hours=2),
        )
    }
    fresh_verdict = {
        "id": 43,
        "user": {"login": "copilot"},
        "state": "APPROVED",
        "body": "lgtm",
        "submitted_at": "2026-06-09T11:59:59Z",  # newer than the prior invalidated verdict
    }
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"], reviews=[fresh_verdict]),
        deps=_deps(),
        config=_config(),
    )
    rv = state.reviewers["copilot"]
    assert rv.status is ReviewerStatus.REVIEW_FOUND
    assert rv.last_review_at == datetime(2026, 6, 9, 11, 59, 59, tzinfo=UTC)
    assert rv.last_request_at == datetime(2026, 6, 9, 11, 59, 59, tzinfo=UTC)
    assert reviewers_gate_satisfied(state) is True


def test_drive_by_in_progress_promoted_without_window_restart_when_requested() -> None:
    # A drive-by mid-review (IN_PROGRESS, required=False) that GitHub formally requests
    # is promoted to required so it blocks the gate — but its in-flight review continues
    # and now counts, so the window is NOT restarted (last_review_at/last_request_at
    # preserved). Only REVIEW_FOUND / NOT_REQUESTED presence is a fresh-ask restart.
    review_at = datetime(2026, 6, 9, 11, 5, 0, tzinfo=UTC)
    reviewers = {
        "randomdev": ReviewerState(
            identity="randomdev",
            kind=ReviewerKind.HUMAN,
            status=ReviewerStatus.IN_PROGRESS,
            required=False,
            last_request_at=review_at,
            last_review_at=review_at,
        )
    }
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["randomdev"]),
        deps=_deps(_JUST_AFTER_ACTIVITY),  # 11:10Z — within the 15m finish timeout
        config=_config(),
    )
    rv = state.reviewers["randomdev"]
    assert rv.required is True
    assert rv.status is ReviewerStatus.IN_PROGRESS
    assert rv.last_review_at == review_at
    assert rv.last_request_at == review_at
    assert reviewers_gate_satisfied(state) is False


def test_withdrawn_request_declines_an_in_flight_reviewer() -> None:
    # Behavior 7: GitHub dropped a pending request and the reviewer produced nothing
    # this poll — the one shape that genuinely means "the ask was pulled".
    reviewers = _requested_at(at=_T0 - timedelta(hours=2))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[]),
        deps=_deps(),
        config=_config(),
    )
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.DECLINED
    assert copilot.declined_reason == "request-withdrawn"
    assert copilot.declined_at == _T0


def test_not_requested_reviewer_never_auto_declines() -> None:
    # Behavior 8 — Codex P1 regression guard. NOT_REQUESTED is produced ONLY by
    # flip_stale_required_reviews on a push: it means "awaiting rereview after
    # invalidation", never "withdrawn". Declining it here would strand the reviewer,
    # and (with change C) permanently exclude them from ever being re-requested.
    reviewers = _required_reviewer(ReviewerStatus.NOT_REQUESTED)
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[]),
        deps=_deps(),
        config=_config(),
    )
    assert state.reviewers["copilot"].status is ReviewerStatus.NOT_REQUESTED


def test_this_poll_activity_prevents_a_spurious_decline() -> None:
    # Behavior 9 — the other Codex P1 regression guard. Submitting a COMMENTED review
    # REMOVES the reviewer from requested_reviewers, so absence plus activity is the
    # ordinary "they just responded" shape, not a withdrawal.
    reviewers = _requested_at(at=_T0 - timedelta(hours=2))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    gh = _gh(
        head_oid="same",
        requested_reviewers=[],
        reviews=[
            {
                "id": 905,
                "state": "COMMENTED",
                "submitted_at": "2026-06-09T11:00:00Z",
                "user": {"login": "copilot"},
                "body": "a note",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(_JUST_AFTER_ACTIVITY), config=_config())
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.IN_PROGRESS  # engaged, not declined
    assert copilot.declined_reason is None


def test_issue_comment_activity_prevents_a_spurious_decline() -> None:
    # Same protection via the other activity channel: a reviewer commenting outside a
    # formal review is engagement too (it reaches new_items, not raw_reviews).
    reviewers = _requested_at(at=_T0 - timedelta(hours=2))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    gh = _gh(
        head_oid="same",
        requested_reviewers=[],
        issue_comments=[
            {
                "id": 906,
                "created_at": "2026-06-09T11:00:00Z",
                "user": {"login": "copilot"},
                "body": "still looking",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(_JUST_AFTER_ACTIVITY), config=_config())
    assert state.reviewers["copilot"].status is ReviewerStatus.IN_PROGRESS
    assert state.reviewers["copilot"].declined_reason is None


def test_timeout_no_start_decline_converts_to_withdrawn_on_observed_absence() -> None:
    # A timeout-no-start decline never engaged, so GitHub kept it in requested_reviewers
    # continuously. When it goes absent (operator pulled the request), that absence is a
    # genuine withdrawal: the retained timeout reason is restamped to request-withdrawn so
    # a later re-add can reopen the gate. Status stays DECLINED — the gate is unaffected.
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="same",
        reviewers=_declined("timeout-no-start"),
    )
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[]),
        deps=_deps(),
        config=_config(),
    )
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.DECLINED
    assert copilot.declined_reason == "request-withdrawn"
    assert copilot.declined_at == _T0


def test_timeout_no_start_decline_reactivates_after_absence_then_re_add() -> None:
    # The full cycle the fix restores: timeout-no-start decline → absence poll converts
    # the reason → a subsequent re-add poll reaches the reactivation branch and reopens
    # the reviewer as REQUESTED (so the gate no longer spuriously satisfies).
    start = _state(
        phase=PRPhase.QUIESCED,
        last_poll_sha="same",
        reviewers=_declined("timeout-no-start"),
    )
    after_absence = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[]),
        deps=_deps(),
        config=_config(),
    )
    after_readd = poll_pr(
        after_absence,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"]),
        deps=_deps(),
        config=_config(),
    )
    copilot = after_readd.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.REQUESTED
    assert copilot.declined_reason is None
    assert copilot.declined_at is None


def test_timeout_stalled_decline_is_not_converted_on_absence() -> None:
    # Negative control: a timeout-stalled decline engaged (last_review_at set), so GitHub
    # already dropped it and its absence is the ordinary post-review shape, NOT a
    # withdrawal. Converting it would mislabel the reason and silently strip its
    # push-driven re-ask (reviewer_needs_refresh). Its reason must survive untouched.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.DECLINED,
            required=True,
            last_request_at=_T0 - timedelta(hours=2),
            last_review_at=_T0 - timedelta(hours=1),
            declined_at=_T0 - timedelta(minutes=30),
            declined_reason="timeout-stalled",
        )
    }
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[]),
        deps=_deps(),
        config=_config(),
    )
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.DECLINED
    assert copilot.declined_reason == "timeout-stalled"


def test_user_declined_never_engaged_is_not_converted_on_absence() -> None:
    # Negative control: an explicit `user-declined` (never engaged, so last_review_at is
    # None) must NOT be restamped to request-withdrawn on observed absence. Its contract in
    # reviewer_needs_refresh keeps `user-declined` refreshable; converting it would flip
    # that to false and silently strip the push-driven re-ask. Only `timeout-no-start`
    # qualifies for the withdrawal restamp.
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="same",
        reviewers=_declined("user-declined"),
    )
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[]),
        deps=_deps(),
        config=_config(),
    )
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.DECLINED
    assert copilot.declined_reason == "user-declined"


def test_terminal_reviewer_is_not_withdrawn() -> None:
    # A reviewer who already delivered a verdict is not re-declared withdrawn just
    # because GitHub stopped listing their now-resolved request.
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[]),
        deps=_deps(),
        config=_config(),
    )
    assert state.reviewers["copilot"].status is ReviewerStatus.REVIEW_FOUND


def _ingested_review_item(gh_id: str, *, login: str, at: datetime) -> ReviewItem:
    # A REVIEW_SUMMARY already on file from an EARLIER poll, so this poll's ingest keys it
    # under (kind, gh_id) as `seen` and does NOT re-surface it in `new_items`. Lets a test
    # place a historical review in the reviews response without also making its author a
    # `new_items` author (which would suppress the withdrawal via the other channel).
    return ReviewItem(
        kind=ItemKind.REVIEW_SUMMARY,
        identity=Identity(gh_id=gh_id),
        author=login,
        body_excerpt="prior-ask note",
        seen_at=at,
    )


def test_stale_review_from_a_prior_window_does_not_block_withdrawal() -> None:
    # Codex P1 (PR #348 comment 3610923471). `reviewed` is derived from the FULL reviews
    # response, so a COMMENTED review that answered a PRIOR ask must not keep a reviewer
    # permanently `active`. Here the reviewer engaged the earlier ask (10:00Z) and was
    # then re-requested (window reopened to 11:00Z); GitHub now drops the pending request
    # with no in-window response — a genuine withdrawal. Guarding on bare `login in
    # reviewed` would wedge them IN_PROGRESS → timeout-stalled → refreshable, re-requesting
    # an ask the operator pulled. The stale 10:00Z review predates last_request_at, so it
    # no longer suppresses the withdrawal.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.IN_PROGRESS,
            required=True,
            last_request_at=_T0 - timedelta(hours=1),  # window reopened 11:00Z
            last_review_at=_T0 - timedelta(hours=2),  # engaged the PRIOR ask at 10:00Z
        )
    }
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    start.items.append(_ingested_review_item("42", login="copilot", at=_T0 - timedelta(hours=2)))
    gh = _gh(
        head_oid="same",
        requested_reviewers=[],
        reviews=[
            {
                "id": 42,
                "state": "COMMENTED",
                "submitted_at": "2026-06-09T10:00:00Z",  # BEFORE the 11:00Z window
                "user": {"login": "copilot"},
                "body": "note on the earlier ask",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.DECLINED
    assert copilot.declined_reason == "request-withdrawn"
    assert copilot.declined_at == _T0


def test_in_window_review_still_suppresses_withdrawal() -> None:
    # Negative control: a review whose timestamp is strictly AFTER last_request_at is
    # in-window engagement — the reviewer is legitimately mid-review, not withdrawn. The
    # 11:30Z review post-dates the 11:00Z window; even though it is not new THIS poll
    # (already ingested), the window check keeps the withdrawal suppressed.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.IN_PROGRESS,
            required=True,
            last_request_at=_T0 - timedelta(hours=1),  # window opened 11:00Z
            last_review_at=datetime(2026, 6, 9, 11, 30, tzinfo=UTC),
        )
    }
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    start.items.append(
        _ingested_review_item("43", login="copilot", at=datetime(2026, 6, 9, 11, 30, tzinfo=UTC))
    )
    gh = _gh(
        head_oid="same",
        requested_reviewers=[],
        reviews=[
            {
                "id": 43,
                "state": "COMMENTED",
                "submitted_at": "2026-06-09T11:30:00Z",  # AFTER the 11:00Z window
                "user": {"login": "copilot"},
                "body": "still reviewing",
            }
        ],
    )
    # Poll within the finish timeout of the 11:30Z review so no stall decline masks intent.
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(_JUST_AFTER_VERDICT), config=_config())
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.IN_PROGRESS
    assert copilot.declined_reason is None


def test_new_item_author_suppresses_withdrawal_regardless_of_window() -> None:
    # Negative control: a login among THIS poll's new_items authors is genuinely fresh
    # feedback (it is itself what cleared the pending request), so it suppresses the
    # withdrawal independent of the window check. The new COMMENTED review here predates
    # last_request_at (window check FALSE), proving the new-item channel is load-bearing.
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.IN_PROGRESS,
            required=True,
            last_request_at=_T0 - timedelta(hours=1),  # window opened 11:00Z
        )
    }
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    gh = _gh(
        head_oid="same",
        requested_reviewers=[],
        reviews=[
            {
                "id": 44,
                "state": "COMMENTED",
                "submitted_at": "2026-06-09T10:30:00Z",  # BEFORE the 11:00Z window
                "user": {"login": "copilot"},
                "body": "late-arriving note ingested this poll",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(_JUST_AFTER_ACTIVITY), config=_config())
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.IN_PROGRESS
    assert copilot.declined_reason is None


def test_external_push_with_stale_reviewer_advances_to_fixes_pending() -> None:
    # Behavior 12 — Codex P1 regression guard. flip_stale_required_reviews moves the
    # reviewer to NOT_REQUESTED, but `rereview` is a FIXES_PENDING pipeline step and
    # AWAITING_REVIEW only ever calls `wait` — so without this arm the reviewer is
    # never re-requested and the PR can quiesce with a stale review.
    #
    # requested_reviewers is empty because GitHub drops a login the instant it reviews:
    # a REVIEW_FOUND reviewer is NOT still listed there (see the collision variant
    # test_external_push_with_github_re_request_uses_the_pending_ask for when GitHub
    # itself re-requests on the push).
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="old",
        last_pushed_head_sha="mine",
        reviewers=reviewers,
    )
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="theirs", requested_reviewers=[]),
        deps=_deps(),
        config=_config(),
    )
    assert state.reviewers["copilot"].status is ReviewerStatus.NOT_REQUESTED
    assert state.phase is PRPhase.FIXES_PENDING


def test_external_push_with_github_re_request_uses_the_pending_ask() -> None:
    # Collision variant: an external push invalidates copilot's REVIEW_FOUND AND GitHub
    # re-requests copilot on that same push (a codeowner re-request). Reconciliation runs
    # before flip_stale_required_reviews, so the pending GitHub ask wins: copilot restarts
    # to REQUESTED (a fresh window at `now`), flip then no-ops on the non-REVIEW_FOUND
    # entry, and the gate stays unsatisfied without prgroom issuing a redundant re-request.
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    reviewers["copilot"].last_review_at = _T0 - timedelta(hours=1)
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="old",
        last_pushed_head_sha="mine",
        reviewers=reviewers,
    )
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="theirs", requested_reviewers=["copilot"]),
        deps=_deps(),
        config=_config(),
    )
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.REQUESTED
    assert copilot.last_request_at == _T0
    assert copilot.last_review_at is None
    assert reviewers_gate_satisfied(state) is False


def test_external_push_without_stale_reviewer_stays_awaiting_review() -> None:
    # The arm is conditional — nothing to refresh means no phase change, so a routine
    # push does not spuriously drive the pipeline.
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="old",
        last_pushed_head_sha="mine",
    )
    state = poll_pr(start, ref=_REF, gh=_gh(head_oid="theirs"), deps=_deps(), config=_config())
    assert state.phase is PRPhase.AWAITING_REVIEW


def test_quiesced_pr_reopens_when_a_reviewer_is_newly_requested() -> None:
    # Behavior 13 — GLM finding. A reviewer can be requested on a PR with no new
    # commits at all; the pre-existing QUIESCED arms fire only on external_push or
    # new_item, so neither covers an operator manually requesting review.
    start = _state(phase=PRPhase.QUIESCED, last_poll_sha="same")
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["alice"]),
        deps=_deps(),
        config=_config(),
    )
    assert state.reviewers["alice"].status is ReviewerStatus.REQUESTED
    assert state.phase is PRPhase.AWAITING_REVIEW


def test_quiesced_pr_with_satisfied_reviewers_stays_quiesced() -> None:
    # The no-noise half: a settled reviewer set does not reopen a resting PR.
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    start = _state(phase=PRPhase.QUIESCED, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[]),
        deps=_deps(),
        config=_config(),
    )
    assert state.phase is PRPhase.QUIESCED
