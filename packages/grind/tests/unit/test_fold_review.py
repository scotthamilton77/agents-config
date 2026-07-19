"""review_round / review_verdict: typed review fields, derived counts."""

from __future__ import annotations

from grind.fold import fold
from tests.unit.builders import event, seed_event

_TO_PR_OPEN = [
    seed_event(),
    event("item_started", item="wgclw.1"),
    event("pr_opened", item="wgclw.1", pr=7),
]


def test_review_round_sets_typed_round_badge_and_moves_to_in_review() -> None:
    events = [
        *_TO_PR_OPEN,
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
    ]

    state = fold(events)

    item = state.items["wgclw.1"]
    assert item.status == "in-review"
    assert item.review.round == 1
    assert item.review.kind == "codex"
    assert item.review.head_sha == "a1"


def test_review_verdict_derives_open_threads_and_wont_fix_count() -> None:
    findings = [
        {"severity": "high", "summary": "bug", "disposition": "fixed"},
        {"severity": "low", "summary": "nit", "disposition": "wont-fix"},
        {"severity": "medium", "summary": "todo", "disposition": "deferred"},
        {"severity": "high", "summary": "escalate", "disposition": "escalated"},
    ]
    events = [
        *_TO_PR_OPEN,
        event(
            "review_verdict",
            item="wgclw.1",
            kind="codex",
            round=1,
            head_sha="a1",
            verdict="findings",
            findings=findings,
        ),
    ]

    state = fold(events)

    review = state.items["wgclw.1"].review
    assert review.open_threads == 2  # deferred + escalated
    assert review.wont_fix_count == 1
    assert review.stalemate is False


def test_review_verdict_stalemate_sets_stalemate_flag() -> None:
    events = [
        *_TO_PR_OPEN,
        event(
            "review_verdict",
            item="wgclw.1",
            kind="codex",
            round=3,
            head_sha="a1",
            verdict="stalemate",
            findings=[],
        ),
    ]

    state = fold(events)

    assert state.items["wgclw.1"].review.stalemate is True


def test_review_round_illegal_before_pr_opened() -> None:
    events = [
        seed_event(),
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
    ]

    state = fold(events)

    assert state.items["wgclw.1"].status == "queued"
    assert len(state.anomalies) == 1
    assert state.anomalies[0].type == "review_round"
