"""Reproduces the phantom-review-flood bug: two composing defects that turn each
of prgroom's own out-of-review inline replies into an ever-growing stream of
bookkeeping noise on the PR.

Defect 1 (poll-side, ``poll_pr`` / ``_ingest_items`` in ``lifecycle/poll.py``):
GitHub wraps every inline reply posted outside a formal review in a synthetic
``COMMENTED`` review carrying an **empty body**. The self-reply filter
(``own_replies``) only excludes a gh id already recorded on some item's
``own_reply_id`` -- but that ledger records the wrapped REPLY COMMENT's id, never
the id GitHub assigns to the synthetic wrapper REVIEW. Each such wrapper is a
brand-new, previously-unseen id, so it sails past the dedup key and is ingested
as a fresh ``REVIEW_SUMMARY`` feedback item with no real content.

Defect 2 (reply-side, ``reply_pr`` in ``lifecycle/reply.py``): the fix agent
dispositions these phantom (and other) items ``SKIPPED`` with its reasoning as
rationale. ``_REPLYABLE`` treats ``SKIPPED`` as postable, and ``_post_reply``
routes any non-``REVIEW_THREAD`` item to the issue-comments endpoint -- so a
``SKIPPED`` ``REVIEW_SUMMARY`` (which has no thread to reply on) posts its
rationale as a brand-new **top-level issue comment**. That comment is itself a
gh id no ledger recognizes, so the flood compounds every cycle.

Both tests below assert the DESIRED behavior and are expected to fail today.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from prgroom.config import PrgroomConfig
from prgroom.deps import Deps
from prgroom.gh import GhCli
from prgroom.lifecycle import poll_pr
from prgroom.lifecycle.reply import reply_pr
from prgroom.proc import CommandResult
from prgroom.prsession.enums import DispositionKind, ItemKind, PRPhase
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Disposition,
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewItem,
    bootstrap_state,
)
from tests.conftest import FixedRandomness, FrozenClock
from tests.fakes import RecordedRunner

_REF = PRRef(owner="octo", repo="demo", number=7)
_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


# ── defect 1: poll ingests a phantom empty-body COMMENTED review ──


def _ok(payload: object) -> CommandResult:
    return CommandResult(returncode=0, stdout=json.dumps(payload), stderr="")


def _gh_with_reviews(reviews: list[dict[str, object]]) -> GhCli:
    """The fixed poll_pr read sequence (head/PR/issue/reviews/review-comments/CI)
    with the caller-supplied ``reviews`` payload standing in for the reviews list.
    """
    results = [
        _ok({"headRefOid": "same"}),
        _ok({"state": "open", "merged_at": None}),
        _ok([]),  # issue comments
        _ok(reviews),  # reviews
        _ok([]),  # review comments (no thread-id GraphQL read needed)
        _ok({"total_count": 1, "check_runs": [{"status": "completed", "conclusion": "success"}]}),
    ]
    return GhCli(RecordedRunner(results))


def _deps() -> Deps:
    return Deps(clock=FrozenClock(_T0), randomness=FixedRandomness())


def _poll_state() -> PRGroomingState:
    state = PRGroomingState(
        pr=_REF,
        phase=PRPhase.AWAITING_REVIEW,
        pr_review_retries_used=0,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(),
        last_poll_sha="same",
        last_pushed_head_sha="",
        reviewers={},
    )
    # A prior cycle already replied to an inline thread; the ledger records the
    # wrapped REPLY COMMENT's own id (9001) -- NOT the id of any wrapper review
    # GitHub may have synthesized around it.
    state.items.append(
        ReviewItem(
            kind=ItemKind.REVIEW_THREAD,
            identity=Identity(gh_id="31"),
            author="octo-bot",
            body_excerpt="nit",
            seen_at=_T0,
            replied=True,
            own_reply_id=9001,
        )
    )
    return state


def test_phantom_empty_body_commented_review_not_ingested() -> None:
    # GitHub's synthetic wrapper review carries a brand-new id (5555) that no
    # ledger has ever seen, an empty body, and state COMMENTED -- the exact shape
    # GitHub produces when it wraps an inline reply posted outside a review.
    phantom_review = {
        "id": 5555,
        "user": {"login": "octo-bot"},
        "state": "COMMENTED",
        "body": "",
        "submitted_at": "2026-06-09T12:05:00Z",
    }
    state = poll_pr(
        _poll_state(),
        ref=_REF,
        gh=_gh_with_reviews([phantom_review]),
        deps=_deps(),
        config=PrgroomConfig(),
    )
    phantom_ids = {
        item.identity.gh_id
        for item in state.items
        if item.kind is ItemKind.REVIEW_SUMMARY and not item.body_excerpt
    }
    assert phantom_ids == set(), (
        f"empty-body COMMENTED review(s) {phantom_ids} were ingested as a "
        "review_summary feedback item; a phantom GitHub wrapper carries no "
        "reviewer content and must be dropped, not re-triaged"
    )


# ── defect 2: reply posts a top-level issue comment for a SKIPPED review_summary ──


class _RecordingGh:
    def __init__(self) -> None:
        self.rest_calls: list[tuple[str, str, dict]] = []
        self.graphql_calls: list[tuple[str, dict]] = []

    def rest(self, method: str, path: str, *, fields=None):
        self.rest_calls.append((method, path, dict(fields or {})))
        return {}

    def graphql(self, query: str, variables: dict):
        self.graphql_calls.append((query, dict(variables)))
        return {}


def _reply_ref() -> PRRef:
    return PRRef(owner="o", repo="r", number=7)


def _skipped_review_summary_state() -> PRGroomingState:
    state = bootstrap_state(_reply_ref(), now=_T0)
    state.phase = PRPhase.FIXES_PENDING
    state.items = [
        ReviewItem(
            kind=ItemKind.REVIEW_SUMMARY,
            identity=Identity(gh_id="5555"),
            author="octo-bot",
            body_excerpt="",
            seen_at=_T0,
            disposition=Disposition(
                kind=DispositionKind.SKIPPED,
                decided_at=_T0,
                decided_by="agent",
                rationale="empty-body synthetic review; nothing actionable",
            ),
        )
    ]
    return state


def test_skipped_review_summary_does_not_post_top_level_issue_comment() -> None:
    # REVIEW_SUMMARY carries no thread to reply on. Posting the SKIPPED rationale
    # as a top-level issue comment mints a brand-new gh id no ledger recognizes,
    # so it compounds into a fresh bookkeeping comment every subsequent cycle.
    gh = _RecordingGh()
    reply_pr(_skipped_review_summary_state(), gh=gh, ref=_reply_ref())
    assert gh.rest_calls == [], (
        "expected no top-level issue comment for a SKIPPED review_summary "
        f"disposition, got {gh.rest_calls}"
    )
