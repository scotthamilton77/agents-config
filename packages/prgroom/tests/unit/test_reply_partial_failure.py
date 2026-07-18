"""Partial-failure crash-idempotency for ``reply_pr`` (verb-atomicity spec §5/§10.1).

The single-persist contract discards a raising verb's progress; these tests pin the
marker + pre-flight-adoption mechanism that makes every remote reply effect safe to
re-issue from the pre-call state. The gh seam is :class:`tests.fakes.RecordingGh`
(protocol fake, never a live call); a "run" is one ``reply_pr`` invocation whose
raise discards its return value exactly as ``_execute_step`` would.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prgroom.errors import PrgroomError
from prgroom.lifecycle.idempotency import (
    memory_marker,
    reply_marker,
    scan_markers,
    with_marker,
)
from prgroom.lifecycle.reply import reply_pr
from prgroom.prsession.enums import DispositionKind, ItemKind, PRPhase
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Disposition,
    Identity,
    ReviewItem,
    RoutedMemory,
    bootstrap_state,
)
from tests.fakes import RecordingGh

_NOW = datetime(2026, 6, 19, tzinfo=UTC)
_REF = PRRef(owner="o", repo="r", number=7)
_ISSUE_COMMENTS = "repos/o/r/issues/7/comments"
_REVIEW_COMMENTS = "repos/o/r/pulls/7/comments"


def _item(kind: ItemKind, gh_id: str, disp: DispositionKind, **disp_kw: object) -> ReviewItem:
    return ReviewItem(
        kind=kind,
        identity=Identity(gh_id=gh_id),
        author="rev",
        body_excerpt="b",
        seen_at=_NOW,
        disposition=Disposition(kind=disp, decided_at=_NOW, decided_by="agent", **disp_kw),  # type: ignore[arg-type]
    )


def _state(items: list[ReviewItem], pending: list[RoutedMemory] | None = None):
    s = bootstrap_state(_REF, now=_NOW)
    s.phase = PRPhase.FIXES_PENDING
    s.items = items
    s.pending_memory = pending or []
    return s


def test_partial_failure_rerun_does_not_duplicate_posted_reply() -> None:
    # §10.1 behavior 1 — THE bead's required partial-failure regression test (the
    # PR #211 duplicate-reply shape). Run 1: item A's POST succeeds (id 91), item
    # B's POST raises transient → reply_pr raises; its return value is discarded
    # exactly as _execute_step discards a raising verb's deepcopy. Run 2 from the
    # UNCHANGED pre-call state: the pre-flight scan finds A's marker on GitHub and
    # adopts it — exactly one POST for A across both runs, B posts on run 2.
    def fresh_items() -> list[ReviewItem]:
        return [
            _item(ItemKind.ISSUE_COMMENT, "12", DispositionKind.FIXED, commits=["abc1234"]),
            _item(ItemKind.ISSUE_COMMENT, "13", DispositionKind.FIXED, commits=["def5678"]),
        ]

    state = _state(fresh_items())
    gh1 = RecordingGh(post_reply_id=91, fail_at=("post", 2))
    with pytest.raises(PrgroomError):
        reply_pr(state, gh=gh1, ref=_REF)
    # The raise discarded the deepcopy; the caller's state is byte-unchanged.
    assert [i.replied for i in state.items] == [False, False]

    marker_a = reply_marker(state.items[0])
    gh2 = RecordingGh(
        post_reply_id=92,
        listed={_ISSUE_COMMENTS: [{"id": 91, "body": with_marker("Fixed in abc1234.", marker_a)}]},
    )
    out = reply_pr(state, gh=gh2, ref=_REF)

    posts_run1 = [(m, p) for m, p, _ in gh1.rest_calls if m == "POST"]
    posts_run2 = [(m, p) for m, p, _ in gh2.rest_calls if m == "POST"]
    # Run 1 attempted two POSTs (A succeeded, B raised); run 2 posts ONLY B.
    assert len(posts_run1) == 2
    assert len(posts_run2) == 1
    assert [i.replied for i in out.items] == [True, True]
    assert out.items[0].own_reply_id == 91  # adopted from the listing, not re-posted
    assert out.items[1].own_reply_id == 92


def test_posted_reply_body_carries_item_marker() -> None:
    # §10.1 behavior 2: the wire contract the scan and the poll backstop both
    # depend on — every posted reply body ends with the full-grammar marker.
    # Contract-pinning, not tautology.
    thread = ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="55", reply_to_comment_id=55),
        author="rev",
        body_excerpt="b",
        seen_at=_NOW,
        disposition=Disposition(
            kind=DispositionKind.FIXED, decided_at=_NOW, decided_by="agent", commits=["abc1234"]
        ),
    )
    issue = _item(ItemKind.ISSUE_COMMENT, "12", DispositionKind.ALREADY_ADDRESSED)
    gh = RecordingGh(post_reply_id=1)
    reply_pr(_state([thread, issue]), gh=gh, ref=_REF)
    bodies = [f["body"] for m, _, f in gh.rest_calls if m == "POST"]
    assert bodies[0].endswith("\n\n<!-- prgroom:reply:review_thread:55 -->")
    assert bodies[1].endswith("\n\n<!-- prgroom:reply:issue_comment:12 -->")


def test_adoption_recovers_reply_id_lost_to_malformed_post_response() -> None:
    # §10.1 behavior 3: run 1's POST response had no usable id (own_reply_id
    # degraded to 0, the ledger blind spot); run 2's listing carries the marker
    # with the real id → adoption records it without a POST.
    state = _state([_item(ItemKind.ISSUE_COMMENT, "12", DispositionKind.FIXED)])
    marker = reply_marker(state.items[0])
    gh = RecordingGh(listed={_ISSUE_COMMENTS: [{"id": 77, "body": with_marker("Fixed.", marker)}]})
    out = reply_pr(state, gh=gh, ref=_REF)
    assert [(m, p) for m, p, _ in gh.rest_calls if m == "POST"] == []
    assert out.items[0].own_reply_id == 77
    assert out.items[0].replied is True


def test_noop_reply_makes_zero_gh_calls() -> None:
    # §10.1 behavior 4 (cost pin): all items replied, no pending memory → no GET,
    # no POST, no GraphQL — the no-op contract survives the pre-flight scan.
    item = _item(ItemKind.ISSUE_COMMENT, "12", DispositionKind.FIXED)
    item.replied = True
    gh = RecordingGh()
    reply_pr(_state([item]), gh=gh, ref=_REF)
    assert gh.rest_calls == []
    assert gh.graphql_calls == []


def test_scan_fetches_only_needed_surfaces() -> None:
    # §10.1 behavior 5: the scan reads exactly the surfaces this invocation posts to.
    issue_only = RecordingGh(post_reply_id=1)
    reply_pr(
        _state([_item(ItemKind.ISSUE_COMMENT, "12", DispositionKind.FIXED)]),
        gh=issue_only,
        ref=_REF,
    )
    gets = [p for m, p, _ in issue_only.rest_calls if m == "GET"]
    assert gets == [_ISSUE_COMMENTS]

    thread_only = RecordingGh(post_reply_id=1)
    thread = ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="55", reply_to_comment_id=55),
        author="rev",
        body_excerpt="b",
        seen_at=_NOW,
        disposition=Disposition(kind=DispositionKind.FIXED, decided_at=_NOW, decided_by="agent"),
    )
    reply_pr(_state([thread]), gh=thread_only, ref=_REF)
    gets = [p for m, p, _ in thread_only.rest_calls if m == "GET"]
    assert gets == [_REVIEW_COMMENTS]


def test_partial_failure_rerun_does_not_duplicate_memory_thread_reply() -> None:
    # §10.1 behavior 6: two target-hinted entries; run 1's second GraphQL mutation
    # raises → pending_memory survives on the pre-call state; run 2 with the first
    # entry's marker visible fires GraphQL only for the second entry.
    def fresh_pending() -> list[RoutedMemory]:
        return [
            RoutedMemory(
                content="A", retry=1, source_item="c1#0", decided_by="x", target_hint="T1"
            ),
            RoutedMemory(
                content="B", retry=1, source_item="c1#1", decided_by="x", target_hint="T2"
            ),
        ]

    state = _state([], pending=fresh_pending())
    gh1 = RecordingGh(fail_at=("graphql", 2))
    with pytest.raises(PrgroomError):
        reply_pr(state, gh=gh1, ref=_REF)
    assert len(state.pending_memory) == 2  # pre-call state untouched by the raise

    marker_a = memory_marker(state.pending_memory[0])
    gh2 = RecordingGh(listed={_REVIEW_COMMENTS: [{"id": 41, "body": with_marker("A", marker_a)}]})
    out = reply_pr(state, gh=gh2, ref=_REF)
    assert len(gh1.graphql_calls) == 2  # first ok, second raised
    assert len(gh2.graphql_calls) == 1  # only the never-posted entry fires
    assert gh2.graphql_calls[0][1]["threadId"] == "T2"
    assert out.pending_memory == []


def test_memory_thread_reply_body_carries_memory_marker() -> None:
    # §10.1 behavior 7: the GraphQL body is with_marker(content, memory_marker(rm))
    # and round-trips through the scanner grammar.
    from prgroom.lifecycle.idempotency import carries_own_marker

    rm = RoutedMemory(content="why", retry=1, source_item="c1#0", decided_by="x", target_hint="T")
    gh = RecordingGh()
    reply_pr(_state([], pending=[rm]), gh=gh, ref=_REF)
    body = gh.graphql_calls[0][1]["body"]
    assert body == with_marker("why", memory_marker(rm))
    assert carries_own_marker(body)


def test_colliding_batch_keys_with_distinct_content_both_post() -> None:
    # §10.1 behavior 13: two entries sharing (retry, source_item) — the §4 batch-key
    # collision (ordinal restart + LLM-reused cluster id) — but distinct content.
    # The first already posted → the second must still fire. Regression guard
    # against silent adopt-skip of a never-posted reply.
    first = RoutedMemory(content="A", retry=1, source_item="c1#0", decided_by="x", target_hint="T")
    second = RoutedMemory(content="B", retry=1, source_item="c1#0", decided_by="x", target_hint="T")
    gh = RecordingGh(
        listed={_REVIEW_COMMENTS: [{"id": 41, "body": with_marker("A", memory_marker(first))}]}
    )
    out = reply_pr(_state([], pending=[first, second]), gh=gh, ref=_REF)
    assert len(gh.graphql_calls) == 1
    assert gh.graphql_calls[0][1]["body"] == with_marker("B", memory_marker(second))
    assert out.pending_memory == []


def test_scan_markers_maps_first_occurrence_and_ignores_non_grammar() -> None:
    # §10.1 behavior 12: earliest comment claims the marker (the original — listing
    # order is ascending); non-grammar marker-like prose never matches; entries with
    # a missing or zero id are skipped.
    marker = "<!-- prgroom:reply:issue_comment:12 -->"
    listing = [
        {"id": 3, "body": "prose mentioning prgroom:reply:issue_comment:12 without grammar"},
        {"id": 5, "body": with_marker("Fixed.", marker)},
        {"id": 9, "body": with_marker("Fixed again (duplicate).", marker)},
        {"id": 0, "body": with_marker("zero id", "<!-- prgroom:mem:r1:c9#0:aaaaaaaaaaaa -->")},
        {"body": with_marker("no id", "<!-- prgroom:mem:r1:c9#1:bbbbbbbbbbbb -->")},
    ]
    assert scan_markers(listing) == {marker: 5}


def test_scan_markers_merges_multiple_listings() -> None:
    # The pre-flight scan merges the issue-comment and review-comment surfaces into
    # one map; a marker found in either listing is adopted.
    issue_marker = "<!-- prgroom:reply:issue_comment:12 -->"
    review_marker = "<!-- prgroom:reply:review_thread:55 -->"
    issue = [{"id": 91, "body": with_marker("a", issue_marker)}]
    review = [{"id": 77, "body": with_marker("b", review_marker)}]
    assert scan_markers(issue, review) == {issue_marker: 91, review_marker: 77}


def test_memory_marker_digest_distinguishes_content() -> None:
    # §4: (retry, source_item) is only batch-unique — two distinct entries can share
    # the batch key; the content digest restores global uniqueness, and identical
    # entries collide by construction (correct dedup).
    a = RoutedMemory(content="A", retry=1, source_item="c1#0", decided_by="x", target_hint="T")
    b = RoutedMemory(content="B", retry=1, source_item="c1#0", decided_by="x", target_hint="T")
    a2 = RoutedMemory(content="A", retry=1, source_item="c1#0", decided_by="y", target_hint="T")
    assert memory_marker(a) != memory_marker(b)
    assert memory_marker(a) == memory_marker(a2)  # decided_by is not part of the effect
