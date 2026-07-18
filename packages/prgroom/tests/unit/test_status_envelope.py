"""Tests for the §4.6 ``status --json`` envelope builder.

These pin the stable merge-gate handoff contract: the envelope shape, each of the
four ``merge_gates`` bools, the ``auto_merge_eligible`` AND truth table, the
per-disposition ``items_summary``, and the reviewer projection. The builder is pure
over an in-memory :class:`PRGroomingState` + a derived :class:`HumanReview`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from prgroom.lifecycle.human_review import HumanReview
from prgroom.lifecycle.status import build_status
from prgroom.prsession.enums import (
    DispositionKind,
    ItemKind,
    PRPhase,
    ReviewerKind,
    ReviewerStatus,
)
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Disposition,
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewerState,
    ReviewItem,
)

_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_REF = PRRef(owner="octo", repo="demo", number=42)

# A satisfied (unconstrained) and an unsatisfied (constrained, no approval) block.
_SATISFIED = HumanReview(required=False, satisfied_by=None)
_UNSATISFIED = HumanReview(required=True, satisfied_by=None)


def _state(**overrides: Any) -> PRGroomingState:
    base: dict[str, Any] = {
        "pr": _REF,
        "phase": PRPhase.QUIESCED,
        "pr_review_retries_used": 2,
        "last_polled_at": _NOW,
        "last_activity_at": _NOW,
        "quiescence": QuiescenceState(ci_state="success", quiesced_at=_NOW),
        "last_error": None,
        "reviewers": {},
        "items": [],
    }
    base.update(overrides)
    return PRGroomingState(**base)


def _item(kind: DispositionKind) -> ReviewItem:
    return ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="c1"),
        author="alice",
        body_excerpt="x",
        seen_at=_NOW,
        disposition=Disposition(kind=kind, decided_at=_NOW, decided_by="claude"),
    )


def test_envelope_top_level_keys() -> None:
    env = build_status(_state(), _SATISFIED)
    assert set(env) == {
        "pr",
        "phase",
        "last_error",
        "pr_review_retries_used",
        "reviewers",
        "ci_state",
        "items_summary",
        "items",
        "last_activity_at",
        "quiesced_at",
        "merge_gates",
        "human_review",
        "auto_merge_eligible",
    }
    assert env["pr"] == 42
    assert env["phase"] == "quiesced"
    assert env["pr_review_retries_used"] == 2
    assert env["ci_state"] == "success"
    assert env["last_activity_at"] == _NOW.isoformat()
    assert env["quiesced_at"] == _NOW.isoformat()


def test_all_gates_green_is_auto_merge_eligible() -> None:
    env = build_status(_state(), _SATISFIED)
    assert env["merge_gates"] == {
        "phase_is_quiesced": True,
        "last_error_clear": True,
        "no_blocker_items": True,
        "human_review_satisfied": True,
    }
    assert env["auto_merge_eligible"] is True


def test_two_simultaneously_false_gates_still_block_eligibility() -> None:
    # Completeness for the AND truth table: two gates false at once (non-quiesced
    # phase AND unsatisfied human review) must still yield auto_merge_eligible=False.
    env = build_status(_state(phase=PRPhase.AWAITING_REVIEW), _UNSATISFIED)
    assert env["merge_gates"]["phase_is_quiesced"] is False
    assert env["merge_gates"]["human_review_satisfied"] is False
    assert env["auto_merge_eligible"] is False


def test_non_quiesced_phase_blocks_eligibility() -> None:
    env = build_status(_state(phase=PRPhase.AWAITING_REVIEW), _SATISFIED)
    assert env["merge_gates"]["phase_is_quiesced"] is False
    assert env["auto_merge_eligible"] is False


def test_last_error_blocks_eligibility() -> None:
    env = build_status(_state(last_error="LIFECYCLE_PR_REVIEW_EXHAUSTED"), _SATISFIED)
    assert env["merge_gates"]["last_error_clear"] is False
    assert env["last_error"] == "LIFECYCLE_PR_REVIEW_EXHAUSTED"
    assert env["auto_merge_eligible"] is False


def test_empty_string_last_error_is_clear() -> None:
    env = build_status(_state(last_error=""), _SATISFIED)
    assert env["merge_gates"]["last_error_clear"] is True
    assert env["last_error"] == ""


def test_blocker_dispositions_block_eligibility() -> None:
    for kind in (DispositionKind.ESCALATED, DispositionKind.FAILED):
        env = build_status(_state(items=[_item(kind)]), _SATISFIED)
        assert env["merge_gates"]["no_blocker_items"] is False
        assert env["auto_merge_eligible"] is False


def test_non_blocker_disposition_does_not_block() -> None:
    env = build_status(_state(items=[_item(DispositionKind.FIXED)]), _SATISFIED)
    assert env["merge_gates"]["no_blocker_items"] is True


def test_undispositioned_item_does_not_count_as_blocker() -> None:
    # An item with disposition is None is not yet processed — it is not a blocker
    # (G_DISPOSITIONS owns that; no_blocker_items only screens escalated/failed).
    bare = ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="c2"),
        author="alice",
        body_excerpt="x",
        seen_at=_NOW,
    )
    env = build_status(_state(items=[bare]), _SATISFIED)
    assert env["merge_gates"]["no_blocker_items"] is True


def test_unsatisfied_human_review_blocks_eligibility() -> None:
    env = build_status(_state(), _UNSATISFIED)
    assert env["merge_gates"]["human_review_satisfied"] is False
    assert env["auto_merge_eligible"] is False


def test_items_summary_counts_all_kinds() -> None:
    items = [
        _item(DispositionKind.FIXED),
        _item(DispositionKind.FIXED),
        _item(DispositionKind.WONT_FIX),
    ]
    env = build_status(_state(items=items), _SATISFIED)
    assert env["items_summary"]["fixed"] == 2
    assert env["items_summary"]["wont_fix"] == 1
    assert env["items_summary"]["escalated"] == 0
    # Every disposition kind is present in the summary (zeroed when absent).
    assert set(env["items_summary"]) == {k.value for k in DispositionKind}


def test_reviewers_sorted_with_bot_and_decline_reason() -> None:
    reviewers = {
        "zoe": ReviewerState(
            identity="zoe",
            kind=ReviewerKind.HUMAN,
            status=ReviewerStatus.IN_PROGRESS,
            required=False,
            last_request_at=_NOW,
        ),
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.DECLINED,
            required=True,
            last_request_at=_NOW,
            declined_reason="timeout-no-start",
        ),
    }
    env = build_status(_state(reviewers=reviewers), _SATISFIED)
    assert [r["login"] for r in env["reviewers"]] == ["copilot", "zoe"]
    assert env["reviewers"][0]["is_bot"] is True
    assert env["reviewers"][0]["required"] is True
    assert env["reviewers"][0]["status"] == "declined"
    assert env["reviewers"][0]["declined_reason"] == "timeout-no-start"
    assert env["reviewers"][1]["is_bot"] is False
    assert env["reviewers"][1]["declined_reason"] == ""


def test_quiesced_at_empty_when_unset() -> None:
    env = build_status(_state(quiescence=QuiescenceState(ci_state="pending")), _SATISFIED)
    assert env["quiesced_at"] == ""
    assert env["ci_state"] == "pending"


def test_human_review_block_is_embedded() -> None:
    env = build_status(_state(), _UNSATISFIED)
    assert env["human_review"] == {
        "required": True,
        "satisfied_by": None,
        "candidates_seen": [],
    }


def test_items_projection_carries_identity_fields_per_kind() -> None:
    # Disposition-contract §3.1/§9.1 behavior 1: one item per kind, mixed
    # disposition states — each row carries kind/gh_id/thread_id/author/
    # replied/resolved exactly as persisted.
    items = [
        ReviewItem(
            kind=ItemKind.REVIEW_THREAD,
            identity=Identity(gh_id="3141592653", thread_id="PRRT_kwDOabc"),
            author="copilot-pull-request-reviewer[bot]",
            body_excerpt="inline nit",
            seen_at=_NOW,
            disposition=Disposition(
                kind=DispositionKind.FIXED, decided_at=_NOW, decided_by="claude sonnet"
            ),
            replied=True,
            resolved=True,
        ),
        ReviewItem(
            kind=ItemKind.REVIEW_SUMMARY,
            identity=Identity(gh_id="4728390343"),
            author="chatgpt-codex-connector[bot]",
            body_excerpt="overall LGTM",
            seen_at=_NOW,
            disposition=Disposition(
                kind=DispositionKind.SKIPPED, decided_at=_NOW, decided_by="claude sonnet"
            ),
            replied=True,
        ),
        ReviewItem(
            kind=ItemKind.ISSUE_COMMENT,
            identity=Identity(gh_id="2718281828"),
            author="reviewer-human",
            body_excerpt="question",
            seen_at=_NOW,
        ),
    ]
    env = build_status(_state(items=items), _SATISFIED)
    rows = env["items"]
    assert [
        (r["kind"], r["gh_id"], r["thread_id"], r["author"], r["replied"], r["resolved"])
        for r in rows
    ] == [
        (
            "review_thread",
            "3141592653",
            "PRRT_kwDOabc",
            "copilot-pull-request-reviewer[bot]",
            True,
            True,
        ),
        ("review_summary", "4728390343", "", "chatgpt-codex-connector[bot]", True, False),
        ("issue_comment", "2718281828", "", "reviewer-human", False, False),
    ]


def test_undispositioned_item_projects_disposition_null() -> None:
    # §9.1 behavior 2: not yet processed == disposition: null, never a sentinel object.
    bare = ReviewItem(
        kind=ItemKind.ISSUE_COMMENT,
        identity=Identity(gh_id="2718281828"),
        author="reviewer-human",
        body_excerpt="question",
        seen_at=_NOW,
    )
    env = build_status(_state(items=[bare]), _SATISFIED)
    assert env["items"][0]["disposition"] is None


def test_dispositioned_item_projects_only_the_contract_triple() -> None:
    # §9.1 behavior 3: disposition carries exactly {kind, decided_at, decided_by};
    # rationale/commits/body_excerpt (and the other private Disposition fields)
    # never leave the store.
    item = ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="3141592653", thread_id="PRRT_kwDOabc"),
        author="alice",
        body_excerpt="private excerpt",
        seen_at=_NOW,
        disposition=Disposition(
            kind=DispositionKind.SKIPPED,
            decided_at=_NOW,
            decided_by="claude sonnet",
            rationale="private rationale",
            commits=["abc123"],
        ),
    )
    env = build_status(_state(items=[item]), _SATISFIED)
    row = env["items"][0]
    assert row["disposition"] == {
        "kind": "skipped",
        "decided_at": _NOW.isoformat(),
        "decided_by": "claude sonnet",
    }
    flat = str(row)
    assert "private rationale" not in flat
    assert "private excerpt" not in flat
    assert "abc123" not in flat


def test_posted_reply_ids_surface_in_projection() -> None:
    # §9.1 behavior 4 (projection half): recorded reply ids surface as strings;
    # an item with none emits [] (fail-closed: fewer exclusions).
    with_ids = ReviewItem(
        kind=ItemKind.REVIEW_SUMMARY,
        identity=Identity(gh_id="4728390343"),
        author="copilot",
        body_excerpt="x",
        seen_at=_NOW,
        posted_reply_ids=["4875007359"],
    )
    without = ReviewItem(
        kind=ItemKind.ISSUE_COMMENT,
        identity=Identity(gh_id="2718281828"),
        author="alice",
        body_excerpt="x",
        seen_at=_NOW,
    )
    env = build_status(_state(items=[with_ids, without]), _SATISFIED)
    assert env["items"][0]["posted_reply_ids"] == ["4875007359"]
    assert env["items"][1]["posted_reply_ids"] == []
