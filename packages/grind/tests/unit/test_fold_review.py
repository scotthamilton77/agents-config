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


def test_review_verdict_conflicting_head_sha_flags_anomaly_and_keeps_latest() -> None:
    events = [
        *_TO_PR_OPEN,
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
        event(
            "review_verdict",
            item="wgclw.1",
            kind="codex",
            round=1,
            head_sha="b2",
            verdict="clean",
            findings=[],
        ),
    ]

    state = fold(events)

    review = state.items["wgclw.1"].review
    # Latest event's value is retained (accept-and-flag).
    assert review.head_sha == "b2"
    # The disagreement surfaces as an anomaly + ERROR observation + attention.
    assert any(a.type == "review_verdict" and "head_sha" in a.reason for a in state.anomalies)
    assert any(o.level == "ERROR" and "head_sha" in o.message for o in state.observations)
    assert any("head_sha" in a.text for a in state.attention)


def test_review_verdict_matching_head_sha_raises_no_anomaly() -> None:
    events = [
        *_TO_PR_OPEN,
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
        event(
            "review_verdict",
            item="wgclw.1",
            kind="codex",
            round=1,
            head_sha="a1",
            verdict="clean",
            findings=[],
        ),
    ]

    state = fold(events)

    assert state.items["wgclw.1"].review.head_sha == "a1"
    assert state.anomalies == []


def test_review_verdict_new_round_head_sha_is_not_a_conflict() -> None:
    # A changed head_sha in a *different* round is a new review run, not a
    # within-round disagreement -- it must not flag.
    events = [
        *_TO_PR_OPEN,
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
        event(
            "review_verdict",
            item="wgclw.1",
            kind="codex",
            round=2,
            head_sha="b2",
            verdict="clean",
            findings=[],
        ),
    ]

    state = fold(events)

    assert state.items["wgclw.1"].review.head_sha == "b2"
    assert state.anomalies == []


def test_review_round_illegal_before_pr_opened() -> None:
    events = [
        seed_event(),
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
    ]

    state = fold(events)

    assert state.items["wgclw.1"].status == "queued"
    assert len(state.anomalies) == 1
    assert state.anomalies[0].type == "review_round"


def test_record_round_updates_non_adjacent_earlier_round_in_place() -> None:
    # A late event for round 1 (arriving after round 3) overwrites round 1's
    # record where it sits -- last-event-wins per distinct round, ordering
    # preserved -- instead of appending a duplicate.
    events = [
        *_TO_PR_OPEN,
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
        event("review_round", item="wgclw.1", kind="codex", round=2, head_sha="a2"),
        event("review_round", item="wgclw.1", kind="codex", round=3, head_sha="a3"),
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="z9"),
    ]

    state = fold(events)

    assert state.items["wgclw.1"].round_history == ((1, "z9"), (2, "a2"), (3, "a3"))
