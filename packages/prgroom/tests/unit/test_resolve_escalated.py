from datetime import UTC, datetime

import pytest

from prgroom.errors import ErrorCode, PrgroomError
from prgroom.lifecycle.resolve_escalated import resolve_escalated_pr
from prgroom.prsession.enums import DispositionKind, ItemKind, PRPhase
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import Disposition, Identity, ReviewItem, bootstrap_state

_NOW = datetime(2026, 6, 19, tzinfo=UTC)


def _ref() -> PRRef:
    return PRRef(owner="o", repo="r", number=1)


def _esc_item(gh_id="100", kind=ItemKind.REVIEW_THREAD) -> ReviewItem:
    return ReviewItem(
        kind=kind,
        identity=Identity(gh_id=gh_id),
        author="a",
        body_excerpt="b",
        seen_at=_NOW,
        disposition=Disposition(
            kind=DispositionKind.ESCALATED, decided_at=_NOW, decided_by="agent"
        ),
    )


def _state(items, phase=PRPhase.HUMAN_GATED):
    s = bootstrap_state(_ref(), now=_NOW)
    s.phase = phase
    s.items = items
    return s


def test_flip_to_skipped_and_advance_phase() -> None:
    s = _state([_esc_item()])
    out = resolve_escalated_pr(
        s,
        item_id="100",
        as_disposition=DispositionKind.SKIPPED,
        rationale="not needed",
        commits=[],
        decided_by="human:scott",
        now=_NOW,
    )
    assert out.items[0].disposition.kind is DispositionKind.SKIPPED
    assert out.items[0].disposition.decided_by == "human:scott"  # provenance pinned
    assert out.phase is PRPhase.FIXES_PENDING
    assert out.round == s.round


def test_fixed_without_commits_raises() -> None:
    s = _state([_esc_item()])
    with pytest.raises(PrgroomError) as ei:
        resolve_escalated_pr(
            s,
            item_id="100",
            as_disposition=DispositionKind.FIXED,
            rationale="",
            commits=[],
            decided_by="human:s",
            now=_NOW,
        )
    assert ei.value.code is ErrorCode.PRECONDITION_FIXED_NEEDS_COMMITS


def test_no_escalations_raises() -> None:
    s = _state([])
    with pytest.raises(PrgroomError) as ei:
        resolve_escalated_pr(
            s,
            item_id="x",
            as_disposition=DispositionKind.SKIPPED,
            rationale="",
            commits=[],
            decided_by="h",
            now=_NOW,
        )
    assert ei.value.code is ErrorCode.PRECONDITION_NO_ESCALATIONS


def test_absent_item_raises_item_not_escalated() -> None:
    s = _state([_esc_item("100")])
    with pytest.raises(PrgroomError) as ei:
        resolve_escalated_pr(
            s,
            item_id="999",
            as_disposition=DispositionKind.SKIPPED,
            rationale="",
            commits=[],
            decided_by="h",
            now=_NOW,
        )
    assert ei.value.code is ErrorCode.PRECONDITION_ITEM_NOT_ESCALATED


def test_ambiguous_bare_gh_id_rejected_compound_resolves() -> None:
    a = _esc_item("100", kind=ItemKind.REVIEW_THREAD)
    b = _esc_item("100", kind=ItemKind.ISSUE_COMMENT)
    with pytest.raises(PrgroomError) as ei:
        resolve_escalated_pr(
            _state([a, b]),
            item_id="100",
            as_disposition=DispositionKind.SKIPPED,
            rationale="",
            commits=[],
            decided_by="h",
            now=_NOW,
        )
    assert ei.value.code is ErrorCode.PRECONDITION_ITEM_NOT_ESCALATED
    out = resolve_escalated_pr(
        _state([a, b]),
        item_id="issue_comment:100",
        as_disposition=DispositionKind.SKIPPED,
        rationale="",
        commits=[],
        decided_by="h",
        now=_NOW,
    )
    flipped = next(i for i in out.items if i.kind is ItemKind.ISSUE_COMMENT)
    assert flipped.disposition.kind is DispositionKind.SKIPPED


def test_matched_item_that_is_not_escalated_raises() -> None:
    # Exactly one item matches the id, but it is NOT escalated — while a DIFFERENT item
    # is (so the NO_ESCALATIONS gate passes and we reach the per-item escalated check).
    target = ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="100"),
        author="a",
        body_excerpt="b",
        seen_at=_NOW,
        disposition=Disposition(kind=DispositionKind.SKIPPED, decided_at=_NOW, decided_by="agent"),
    )
    with pytest.raises(PrgroomError) as ei:
        resolve_escalated_pr(
            _state([target, _esc_item("200")]),
            item_id="100",
            as_disposition=DispositionKind.SKIPPED,
            rationale="",
            commits=[],
            decided_by="h",
            now=_NOW,
        )
    assert ei.value.code is ErrorCode.PRECONDITION_ITEM_NOT_ESCALATED


def test_no_phase_advance_while_escalations_remain() -> None:
    s = _state([_esc_item("100"), _esc_item("200")])
    out = resolve_escalated_pr(
        s,
        item_id="100",
        as_disposition=DispositionKind.SKIPPED,
        rationale="",
        commits=[],
        decided_by="h",
        now=_NOW,
    )
    assert out.phase is PRPhase.HUMAN_GATED
