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
        "round": 2,
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
        "round",
        "reviewers",
        "ci_state",
        "items_summary",
        "last_activity_at",
        "quiesced_at",
        "merge_gates",
        "human_review",
        "auto_merge_eligible",
    }
    assert env["pr"] == 42
    assert env["phase"] == "quiesced"
    assert env["round"] == 2
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
    env = build_status(_state(last_error="LIFECYCLE_HARD_CAP_EXCEEDED"), _SATISFIED)
    assert env["merge_gates"]["last_error_clear"] is False
    assert env["last_error"] == "LIFECYCLE_HARD_CAP_EXCEEDED"
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
