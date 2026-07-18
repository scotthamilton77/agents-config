"""Tests for ``resolve_pr`` — the lock-held ``_resolve`` lifecycle internal (§3.2).

``_resolve`` resolves every ``review_thread`` item whose disposition is ``fixed`` or
``already_addressed`` and that is not yet resolved, via the GraphQL
``resolveReviewThread`` mutation keyed by the thread's node id (``Identity.thread_id``,
a ``PRRT_*``). It marks each ``resolved=True`` so a re-run is a no-op. The mocked
seam is the subprocess boundary (``GhCli`` + ``RecordedRunner``); the issued mutation
and the ``resolved`` flag are the observable behavior. Works on a deepcopy; no store
write (§3.3).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from prgroom.gh import GhCli
from prgroom.lifecycle.resolve import resolve_pr
from prgroom.proc import CommandResult
from prgroom.prsession.enums import DispositionKind, ItemKind, PRPhase
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Disposition,
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewItem,
)
from tests.fakes import RecordedRunner

_REF = PRRef(owner="octo", repo="demo", number=7)
_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _resolved_ok() -> CommandResult:
    payload = {"data": {"resolveReviewThread": {"thread": {"id": "PRRT_x", "isResolved": True}}}}
    return CommandResult(returncode=0, stdout=json.dumps(payload), stderr="")


def _disp(kind: DispositionKind) -> Disposition:
    return Disposition(kind=kind, decided_at=_T0, decided_by="claude opus[1m]")


def _item(
    *,
    gh_id: str = "1",
    thread_id: str = "PRRT_x",
    kind: ItemKind = ItemKind.REVIEW_THREAD,
    disposition: Disposition | None = None,
    resolved: bool = False,
) -> ReviewItem:
    return ReviewItem(
        kind=kind,
        identity=Identity(gh_id=gh_id, thread_id=thread_id),
        author="copilot",
        body_excerpt="fix this",
        seen_at=_T0,
        disposition=disposition,
        resolved=resolved,
    )


def _state(*items: ReviewItem) -> PRGroomingState:
    return PRGroomingState(
        pr=_REF,
        phase=PRPhase.FIXES_PENDING,
        pr_review_retries_used=2,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(),
        items=list(items),
    )


def test_resolve_resolves_a_fixed_unresolved_thread() -> None:
    runner = RecordedRunner([_resolved_ok()])
    out = resolve_pr(
        _state(_item(thread_id="PRRT_abc", disposition=_disp(DispositionKind.FIXED))),
        gh=GhCli(runner),
    )
    assert len(runner.calls) == 1
    argv = runner.calls[0]
    assert "graphql" in argv
    assert any("resolveReviewThread" in part for part in argv)
    assert "threadId=PRRT_abc" in argv
    assert out.items[0].resolved is True


def test_resolve_resolves_an_already_addressed_thread() -> None:
    runner = RecordedRunner([_resolved_ok()])
    out = resolve_pr(
        _state(_item(disposition=_disp(DispositionKind.ALREADY_ADDRESSED))),
        gh=GhCli(runner),
    )
    assert len(runner.calls) == 1
    assert out.items[0].resolved is True


def test_resolve_skips_an_already_resolved_thread() -> None:
    runner = RecordedRunner([])  # a second resolve call would raise "exhausted"
    out = resolve_pr(
        _state(_item(disposition=_disp(DispositionKind.FIXED), resolved=True)),
        gh=GhCli(runner),
    )
    assert runner.calls == []
    assert out.items[0].resolved is True


def test_resolve_rerun_reissues_idempotent_mutation_after_midloop_failure() -> None:
    # Verb-atomicity §3 audit / behavior 11: resolveReviewThread is idempotent
    # server-side, so resolve needs no markers — a mid-loop failure discards the
    # deepcopy, and the rerun harmlessly re-issues BOTH mutations. This pins the
    # reasoning resolve.py documents, which had zero retry-path coverage.
    import pytest

    from prgroom.errors import PrgroomError

    def fresh_state() -> PRGroomingState:
        return _state(
            _item(gh_id="1", thread_id="PRRT_a", disposition=_disp(DispositionKind.FIXED)),
            _item(gh_id="2", thread_id="PRRT_b", disposition=_disp(DispositionKind.FIXED)),
        )

    failing = CommandResult(
        returncode=1,
        stdout=json.dumps({"message": "boom", "status": "500"}),
        stderr="gh: boom (HTTP 500)",
    )
    state = fresh_state()
    run1 = RecordedRunner([_resolved_ok(), failing])
    with pytest.raises(PrgroomError):
        resolve_pr(state, gh=GhCli(run1))
    assert len(run1.calls) == 2  # first resolved, second raised
    assert [i.resolved for i in state.items] == [False, False]  # deepcopy discarded

    run2 = RecordedRunner([_resolved_ok(), _resolved_ok()])
    out = resolve_pr(state, gh=GhCli(run2))
    assert len(run2.calls) == 2  # both re-issued — server-side idempotency absorbs it
    assert [i.resolved for i in out.items] == [True, True]


def test_resolve_ignores_non_resolvable_dispositions() -> None:
    runner = RecordedRunner([])
    out = resolve_pr(
        _state(
            _item(gh_id="1", disposition=_disp(DispositionKind.SKIPPED)),
            _item(gh_id="2", disposition=_disp(DispositionKind.WONT_FIX)),
            _item(gh_id="3", disposition=None),
        ),
        gh=GhCli(runner),
    )
    assert runner.calls == []
    assert all(not it.resolved for it in out.items)


def test_resolve_skips_a_degraded_thread_without_a_node_id_and_warns() -> None:
    # A review_thread the poll couldn't map (thread_id == "") cannot be resolved;
    # it is skipped (left unresolved for a later poll to repair) with a warning,
    # never silently marked resolved.
    msgs: list[str] = []
    runner = RecordedRunner([])
    out = resolve_pr(
        _state(_item(thread_id="", disposition=_disp(DispositionKind.FIXED))),
        gh=GhCli(runner),
        warn=msgs.append,
    )
    assert runner.calls == []
    assert out.items[0].resolved is False
    assert msgs  # a warning was emitted


def test_resolve_is_a_noop_with_no_resolvable_items() -> None:
    runner = RecordedRunner([])
    out = resolve_pr(_state(), gh=GhCli(runner))
    assert runner.calls == []
    assert out.items == []
