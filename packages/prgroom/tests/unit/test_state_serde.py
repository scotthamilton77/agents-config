"""Tests for the PRGroomingState serialization contract (§2, schema_version 1).

The state file is the sole survivor of process exit, so its JSON shape is a hard
contract. These tests pin the *coded decisions* in §2:

* ``SCHEMA_VERSION`` is written into every serialized state (wire contract).
* Falsy / None optional fields are **omitted** from JSON (§2 "omitted when falsy").
* A full round-trip (``to_dict`` -> ``from_dict``) reconstructs an equal object,
  including nested items, reviewers, dispositions, and tz-aware datetimes.

Enum *values* (PRPhase, DispositionKind, ...) are pinned here, at the
serialization boundary, because they travel on the wire.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prgroom.prsession.enums import (
    DispositionKind,
    GateStrength,
    ItemKind,
    PRPhase,
    ReviewerKind,
    ReviewerStatus,
)
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    SCHEMA_VERSION,
    Disposition,
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewerState,
    ReviewItem,
)

_T = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_NAIVE = datetime(2026, 6, 9, 12, 0, 0)  # no tzinfo
_REF = PRRef(owner="octo", repo="demo", number=7)


def _minimal_state() -> PRGroomingState:
    return PRGroomingState(
        pr=_REF,
        phase=PRPhase.IDLE,
        pr_review_retries_used=0,
        last_polled_at=_T,
        last_activity_at=_T,
        quiescence=QuiescenceState(),
    )


def test_schema_version_is_one_on_the_wire() -> None:
    assert SCHEMA_VERSION == 1
    assert _minimal_state().to_dict()["schema_version"] == 1


def test_minimal_state_omits_falsy_optionals() -> None:
    d = _minimal_state().to_dict()
    # §2: these are omitted from JSON when falsy / None / empty.
    for omitted in (
        "last_poll_sha",
        "last_pushed_head_sha",
        "human_review_label_added",
        "last_error",
        "lifecycle_escalation_filed",
    ):
        assert omitted not in d
    # Empty collections are still omitted (no empty `items` / `reviewers` keys).
    assert "items" not in d
    assert "reviewers" not in d


def test_phase_serializes_as_its_hyphenated_wire_value() -> None:
    state = _minimal_state()
    state.phase = PRPhase.AWAITING_REVIEW
    assert state.to_dict()["phase"] == "awaiting-review"


def test_round_trip_preserves_minimal_state() -> None:
    state = _minimal_state()
    assert PRGroomingState.from_dict(state.to_dict()) == state


def test_round_trip_preserves_fully_populated_state() -> None:
    disposition = Disposition(
        kind=DispositionKind.FIXED,
        decided_at=_T,
        decided_by="claude -p opus[1m]",
        rationale="addressed the off-by-one",
        commits=["abc123", "def456"],
        response_path="/tmp/resp.md",  # noqa: S108  # test fixture path, not a real temp write
        gate=GateStrength.FULL,
    )
    item = ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="C_1", thread_id="PRT_1", reply_to_comment_id=99),
        author="copilot",
        body_excerpt="consider extracting this helper",
        seen_at=_T,
        cluster_id="c-abc123",
        disposition=disposition,
        replied=True,
        resolved=True,
    )
    reviewer = ReviewerState(
        identity="copilot",
        kind=ReviewerKind.BOT,
        status=ReviewerStatus.REVIEW_FOUND,
        required=True,
        last_request_at=_T,
        last_review_at=_T,
    )
    state = PRGroomingState(
        pr=_REF,
        phase=PRPhase.FIXES_PENDING,
        pr_review_retries_used=2,
        last_polled_at=_T,
        last_activity_at=_T,
        quiescence=QuiescenceState(ci_state="success", quiesced_at=None),
        last_poll_sha="head1",
        last_pushed_head_sha="head0",
        human_review_label_added=True,
        reviewers={"copilot": reviewer},
        items=[item],
        last_error="LIFECYCLE_PR_REVIEW_EXHAUSTED",
        lifecycle_escalation_filed=True,
    )
    assert PRGroomingState.from_dict(state.to_dict()) == state


def test_fixed_disposition_omits_empty_rationale_from_json() -> None:
    # §2: rationale is omitted when falsy. A `fixed` disposition carries commits,
    # not a rationale, so the key must be absent from the wire form.
    d = Disposition(
        kind=DispositionKind.FIXED, decided_at=_T, decided_by="claude", commits=["sha"]
    ).to_dict()
    assert "rationale" not in d
    assert d["commits"] == ["sha"]


def test_reviewer_before_first_engagement_omits_review_and_decline_fields() -> None:
    # §2: last_review_at / declined_* are omitted until set. A freshly-requested
    # reviewer has none of them.
    d = ReviewerState(
        identity="copilot",
        kind=ReviewerKind.BOT,
        status=ReviewerStatus.REQUESTED,
        required=True,
        last_request_at=_T,
    ).to_dict()
    for omitted in ("last_review_at", "declined_at", "declined_reason"):
        assert omitted not in d


def test_item_without_disposition_omits_the_key() -> None:
    item = ReviewItem(
        kind=ItemKind.ISSUE_COMMENT,
        identity=Identity(gh_id="IC_1", issue_comment_id=5),
        author="alice",
        body_excerpt="nit: typo",
        seen_at=_T,
    )
    d = item.to_dict()
    assert "disposition" not in d
    assert "cluster_id" not in d
    # An issue_comment carries no thread fields, so they are omitted from identity.
    assert "thread_id" not in d["identity"]


def test_every_optional_field_round_trips_when_populated() -> None:
    # Each optional field has an "omit when falsy" serialize branch (§2); this
    # pins the truthy branch of every one so the round-trip covers both sides.
    disposition = Disposition(
        kind=DispositionKind.ESCALATED,
        decided_at=_T,
        decided_by="claude",
        rationale="needs a human",
        commits=["sha"],
        response_path="/r.md",
        gate=GateStrength.LITE,
        escalation_filed=True,
    )
    item = ReviewItem(
        kind=ItemKind.REVIEW_SUMMARY,
        identity=Identity(gh_id="RS_1"),
        author="copilot",
        body_excerpt="overall LGTM with nits",
        seen_at=_T,
        cluster_id="c-1",
        disposition=disposition,
        replied=True,
        resolved=True,
        duplicate_of_gh_id="RS_0",
    )
    reviewer = ReviewerState(
        identity="copilot",
        kind=ReviewerKind.BOT,
        status=ReviewerStatus.DECLINED,
        required=True,
        last_request_at=_T,
        last_review_at=_T,
        declined_at=_T,
        declined_reason="timeout-stalled",
    )
    state = PRGroomingState(
        pr=_REF,
        phase=PRPhase.HUMAN_GATED,
        pr_review_retries_used=3,
        last_polled_at=_T,
        last_activity_at=_T,
        quiescence=QuiescenceState(ci_state="failure", quiesced_at=_T),
        last_poll_sha="h1",
        last_pushed_head_sha="h0",
        human_review_label_added=True,
        reviewers={"copilot": reviewer},
        items=[item],
        last_error="STATE_CORRUPT",
        lifecycle_escalation_filed=True,
    )
    assert PRGroomingState.from_dict(state.to_dict()) == state


def test_serializing_a_naive_datetime_raises() -> None:
    # §4 resumability compares against stored UTC values, so the wire form must be
    # tz-aware. A naive datetime would serialize without an offset and silently
    # break that invariant — reject it at the serialization boundary.
    state = _minimal_state()
    state.last_polled_at = _NAIVE
    with pytest.raises(ValueError, match="timezone-aware"):
        state.to_dict()


def test_parsing_a_tz_naive_datetime_string_raises() -> None:
    # Mirror guard on the read side: a stored datetime lacking a UTC offset is
    # unusable for the resumability comparison and must not reconstruct as naive.
    d = _minimal_state().to_dict()
    d["last_polled_at"] = "2026-06-09T12:00:00"  # no offset
    with pytest.raises(ValueError, match="timezone-aware"):
        PRGroomingState.from_dict(d)


def test_disposition_gate_roundtrips_as_enum() -> None:
    d = Disposition(
        kind=DispositionKind.FIXED,
        decided_at=_T,
        decided_by="agent",
        gate=GateStrength.FULL,
    )
    encoded = d.to_dict()
    assert encoded["gate"] == "full"
    decoded = Disposition.from_dict(encoded)
    assert decoded.gate is GateStrength.FULL


def test_disposition_gate_none_is_omitted_and_loads_none() -> None:
    d = Disposition(kind=DispositionKind.SKIPPED, decided_at=_T, decided_by="agent")
    encoded = d.to_dict()
    assert "gate" not in encoded
    assert Disposition.from_dict(encoded).gate is None


def test_disposition_legacy_empty_gate_loads_none() -> None:
    # Pre-enum writers omitted falsy gates, but a hand-edited "" must not raise.
    raw = {"kind": "skipped", "decided_at": _T.isoformat(), "decided_by": "agent", "gate": ""}
    assert Disposition.from_dict(raw).gate is None


def test_disposition_invalid_gate_raises() -> None:
    # Same strictness as kind: an unknown non-empty enum value is a corrupt state file.
    raw = {"kind": "fixed", "decided_at": _T.isoformat(), "decided_by": "agent", "gate": "banana"}
    with pytest.raises(ValueError, match="banana"):
        Disposition.from_dict(raw)


def test_disposition_falsy_zero_gate_raises() -> None:
    # 0 is falsy but not an absent-form (None/""); a truthiness guard would hide it.
    raw = {"kind": "fixed", "decided_at": _T.isoformat(), "decided_by": "agent", "gate": 0}
    with pytest.raises(ValueError):
        Disposition.from_dict(raw)


def test_disposition_falsy_false_gate_raises() -> None:
    # False is falsy but not an absent-form (None/""); it must parse-or-raise, not vanish.
    raw = {"kind": "fixed", "decided_at": _T.isoformat(), "decided_by": "agent", "gate": False}
    with pytest.raises(ValueError):
        Disposition.from_dict(raw)


def test_disposition_round_trips_through_item() -> None:
    item = ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="C_2", thread_id="PRT_2"),
        author="copilot",
        body_excerpt="x",
        seen_at=_T,
        disposition=Disposition(
            kind=DispositionKind.WONT_FIX,
            decided_at=_T,
            decided_by="human:scott",
            rationale="intentional design choice",
        ),
    )
    assert ReviewItem.from_dict(item.to_dict()) == item
