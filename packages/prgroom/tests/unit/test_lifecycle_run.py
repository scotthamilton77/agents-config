"""Tests for the ``run`` aggregate verb — the §3.3 keystone.

The orchestration is driven through the injectable :class:`Verbs` seam: fake verbs
record their invocation and apply deterministic state transforms, so the loop's
control flow (poll-first cycle, ordered FIXES_PENDING pipeline, the single
``handle_verb_error`` site, pre-push cap guard, ``_rereview`` guard, entry-probe +
cap re-arm, end-of-cycle resolution, both flush sites, per-step write discipline) is
exercised without any gh/git. Helper functions are unit-tested directly; full ``_run``
scenarios cover the assembled flow.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from prgroom.config import PrgroomConfig
from prgroom.deps import Deps
from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.escalation import Escalation
from prgroom.lifecycle.run import (
    Mode,
    RunContext,
    Verbs,
    VerbStep,
    _build_pipeline,
    _cap_guard_step,
    _entry_probe,
    _execute_step,
    _reply,
    _rereview_guard,
    _resolve_end_of_cycle,
    _run,
    run_lifecycle,
)
from prgroom.prsession.enums import DispositionKind, ItemKind, PRPhase, ReviewerKind, ReviewerStatus
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Disposition,
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewerState,
    ReviewItem,
)
from prgroom.prsession.store import SchemaUnknownError, StateCorruptError

_REF = PRRef(owner="octo", repo="demo", number=7)
_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_STALE = _NOW - timedelta(hours=1)  # past the idle threshold -> idle gate satisfied


class _Clock:
    def now(self) -> datetime:
        return _NOW


class _Rand:
    def token_hex(self, n: int = 8) -> str:
        return "0" * (2 * n)


_DEPS = Deps(clock=_Clock(), randomness=_Rand())


class RecordingSink:
    def __init__(self) -> None:
        self.emitted: list[Escalation] = []

    def emit(self, escalation: Escalation) -> None:
        self.emitted.append(escalation)


class FakeGh:
    def __init__(self) -> None:
        self.added: list[tuple[PRRef, str]] = []
        self.rest_calls: list[tuple[str, str, dict]] = []

    def add_label(self, ref: PRRef, label: str) -> None:
        self.added.append((ref, label))

    def rest(self, method: str, path: str, *, fields=None) -> dict:
        self.rest_calls.append((method, path, dict(fields or {})))
        return {}


class CountingStore:
    """Wraps InMemoryStore and counts writes — verifies the per-step write discipline."""

    def __init__(self) -> None:
        self._inner = InMemoryStore()
        self.writes = 0

    def read(self, ref: PRRef) -> PRGroomingState:
        return self._inner.read(ref)

    def write(self, ref: PRRef, state: PRGroomingState) -> None:
        self.writes += 1
        self._inner.write(ref, state)

    def lock(self, ref: PRRef):
        return self._inner.lock(ref)


def _quiescent_state(*, phase: PRPhase = PRPhase.FIXES_PENDING, **kw: object) -> PRGroomingState:
    """A state that satisfies every quiescence gate (no reviewers/items, green CI, idle)."""
    return PRGroomingState(
        pr=_REF,
        phase=phase,
        round=kw.get("round", 1),  # type: ignore[arg-type]
        last_polled_at=_NOW,
        last_activity_at=_STALE,
        quiescence=QuiescenceState(ci_state="success"),
        last_pushed_head_sha=kw.get("last_pushed_head_sha", ""),  # type: ignore[arg-type]
        reviewers=kw.get("reviewers", {}),  # type: ignore[arg-type]
        items=kw.get("items", []),  # type: ignore[arg-type]
        last_error=kw.get("last_error"),  # type: ignore[arg-type]
        lifecycle_escalation_filed=kw.get("lifecycle_filed", False),  # type: ignore[arg-type]
        human_review_label_added=kw.get("label_added", False),  # type: ignore[arg-type]
    )


def _ctx(
    state: PRGroomingState,
    *,
    store: object | None = None,
    gh: object | None = None,
    sink: object | None = None,
    mode: Mode = Mode.AUTONOMOUS,
    config: PrgroomConfig | None = None,
) -> RunContext:
    used_store = store if store is not None else InMemoryStore()
    if store is None:
        # `_run` reads the initial state from the store (ctx.state is a placeholder it
        # overwrites). Seed the default store so the store and ctx.state agree; tests
        # that pass an explicit store own their own seeding (e.g. the empty-store
        # bootstrap test, or the multi-cycle stores written before _ctx).
        used_store.write(_REF, state)
    return RunContext(
        store=used_store,  # type: ignore[arg-type]
        ref=_REF,
        gh=gh if gh is not None else FakeGh(),  # type: ignore[arg-type]
        git=object(),  # type: ignore[arg-type] - unused by fake verbs
        deps=_DEPS,
        config=config if config is not None else PrgroomConfig(),
        sink=sink if sink is not None else RecordingSink(),  # type: ignore[arg-type]
        mode=mode,
        cancel=object(),  # type: ignore[arg-type] - _wait is faked
        state=state,
    )


def _recorder(name: str, calls: list[str], transform=None):
    def step(ctx: RunContext) -> PRGroomingState:
        calls.append(name)
        if transform is not None:
            transform(ctx.state)
        return ctx.state

    return step


def _raiser(err: PrgroomError):
    def step(_ctx: RunContext) -> PRGroomingState:
        raise err

    return step


def _verbs(calls: list[str], *, has_queued: bool = False, **overrides):
    names = ("poll", "cluster", "fix", "push", "rereview", "reply", "resolve", "wait")
    built = {n: overrides.get(n, _recorder(n, calls)) for n in names}
    return Verbs(has_queued=overrides.get("has_queued_fn", lambda _ctx: has_queued), **built)


# ── _execute_step: the single handle_verb_error site ────────────────────────


def test_execute_step_writes_state_on_success() -> None:
    store = CountingStore()
    ctx = _ctx(_quiescent_state(), store=store)
    _execute_step(VerbStep("poll", _recorder("poll", [])), ctx)
    assert store.writes == 1  # per-internal write discipline


def test_execute_step_skips_when_guard_unmet() -> None:
    store = CountingStore()
    calls: list[str] = []
    ctx = _ctx(_quiescent_state(), store=store)
    _execute_step(VerbStep("x", _recorder("x", calls), guard=lambda _c: False), ctx)
    assert calls == []
    assert store.writes == 0


def test_execute_step_continue_on_contract_audit_failed() -> None:
    # CONTRACT_AUDIT_FAILED -> CONTINUE: no re-raise, state persisted, cycle proceeds.
    ctx = _ctx(_quiescent_state())
    err = PrgroomError(tier=Tier.CONTRACT_AUDIT_FAILED, code=ErrorCode.CONTRACT_FIX_AUDIT_FAILED)
    _execute_step(VerbStep("fix", _raiser(err)), ctx)  # must NOT raise
    assert ctx.state.last_error is None  # CONTRACT tier does not set last_error


def test_execute_step_propagate_flushes_then_raises() -> None:
    sink = RecordingSink()
    gh = FakeGh()
    ctx = _ctx(_quiescent_state(), sink=sink, gh=gh)
    err = PrgroomError(tier=Tier.RUNTIME_TERMINAL_USER, code=ErrorCode.RUNTIME_GH_TERMINAL)
    with pytest.raises(PrgroomError) as excinfo:
        _execute_step(VerbStep("poll", _raiser(err)), ctx)
    assert excinfo.value.code is ErrorCode.RUNTIME_GH_TERMINAL
    assert ctx.state.phase is PRPhase.HUMAN_GATED  # handle_verb_error gated it
    assert len(sink.emitted) == 1  # escalate fired before re-raise (last_error set)
    assert gh.added == []  # RUNTIME_GH_TERMINAL is a §4.7 non-trigger — no label


# ── _cap_guard_step + _rereview_guard ───────────────────────────────────────


def test_cap_guard_trips_when_queued_and_at_cap() -> None:
    ctx = _ctx(_quiescent_state(round=3), config=PrgroomConfig(max_rounds=3))
    guard = _cap_guard_step(_verbs([], has_queued=True))
    out = guard(ctx)
    assert out.phase is PRPhase.HUMAN_GATED
    assert out.last_error == ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED.value
    assert out.lifecycle_escalation_filed is False  # cleared so loop-top fires once


def test_cap_guard_no_trip_under_cap() -> None:
    ctx = _ctx(_quiescent_state(round=2), config=PrgroomConfig(max_rounds=3))
    guard = _cap_guard_step(_verbs([], has_queued=True))
    out = guard(ctx)
    assert out.phase is PRPhase.FIXES_PENDING  # unchanged


def test_cap_guard_no_trip_without_queued_commits() -> None:
    ctx = _ctx(_quiescent_state(round=5), config=PrgroomConfig(max_rounds=3))
    guard = _cap_guard_step(_verbs([], has_queued=False))
    assert guard(ctx).phase is PRPhase.FIXES_PENDING  # at cap but nothing queued


def test_rereview_guard_true_when_awaiting_and_reviewer_stale() -> None:
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.NOT_REQUESTED,
            required=True,
            last_request_at=_NOW,
        )
    }
    state = _quiescent_state(reviewers=reviewers)
    state.last_review_invalidated_sha = "h1"  # a push invalidated review at this HEAD
    state.last_rereviewed_sha = ""  # not yet rereviewed
    ctx = _ctx(state)
    assert _rereview_guard(ctx) is True


def test_rereview_guard_false_when_caught_up() -> None:
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.NOT_REQUESTED,
            required=True,
            last_request_at=_NOW,
        )
    }
    state = _quiescent_state(reviewers=reviewers)
    state.last_review_invalidated_sha = "h1"
    state.last_rereviewed_sha = "h1"  # already rereviewed this HEAD
    ctx = _ctx(state)
    assert _rereview_guard(ctx) is False


def test_rereview_guard_survives_cycle_that_pushed_then_aborted() -> None:
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.NOT_REQUESTED,
            required=True,
            last_request_at=_NOW,
        )
    }
    state = _quiescent_state(reviewers=reviewers)
    state.last_review_invalidated_sha = "h1"  # _push stamped it
    state.last_rereviewed_sha = ""  # rereview never ran (reply/resolve aborted)
    ctx = _ctx(state)
    ctx.cycle_start_pushed_sha = state.last_pushed_head_sha  # NO push this (resumed) cycle
    assert _rereview_guard(ctx) is True  # still armed — guard is persisted, not cycle-relative


# ── _entry_probe + cap re-arm ───────────────────────────────────────────────


def test_entry_probe_noop_on_non_terminal_phase() -> None:
    calls: list[str] = []
    ctx = _ctx(_quiescent_state(phase=PRPhase.FIXES_PENDING))
    _entry_probe(ctx, _verbs(calls))
    assert calls == []  # did not poll — entry probe only runs from terminal-for-CLI


def test_entry_probe_cap_rearm_after_raised_max_rounds() -> None:
    state = _quiescent_state(
        phase=PRPhase.HUMAN_GATED,
        round=3,
        last_error=ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED.value,
        lifecycle_filed=True,
        label_added=True,
    )
    ctx = _ctx(state, config=PrgroomConfig(max_rounds=6))  # operator raised the cap
    # round(3) < max(6) -> cap no longer trips -> re-arm to fixes-pending.
    _entry_probe(ctx, _verbs([], has_queued=True))
    assert ctx.state.phase is PRPhase.FIXES_PENDING
    assert ctx.state.last_error is None
    assert ctx.state.lifecycle_escalation_filed is False
    assert ctx.state.human_review_label_added is False


def test_entry_probe_no_rearm_on_bare_rerun() -> None:
    state = _quiescent_state(
        phase=PRPhase.HUMAN_GATED,
        round=3,
        last_error=ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED.value,
    )
    ctx = _ctx(state, config=PrgroomConfig(max_rounds=3))  # NOT raised
    _entry_probe(ctx, _verbs([], has_queued=True))  # round(3) >= max(3) AND queued -> stays gated
    assert ctx.state.phase is PRPhase.HUMAN_GATED
    assert ctx.state.last_error == ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED.value


def test_entry_probe_skips_has_queued_when_poll_exits_gate() -> None:
    # PR #165 review: a poll that moves the PR out of human-gated (external merge) must
    # NOT trigger the effectful has_queued read — a transient failure there would corrupt
    # an otherwise-clean terminal run. has_queued raises here; the probe must not call it.
    reads: list[int] = []

    def poll(ctx: RunContext) -> PRGroomingState:
        ctx.state.phase = PRPhase.MERGED  # operator merged externally
        return ctx.state

    def spy(_ctx: RunContext) -> bool:
        reads.append(1)
        return False

    state = _quiescent_state(
        phase=PRPhase.HUMAN_GATED,
        round=3,
        last_error=ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED.value,
    )
    ctx = _ctx(state, config=PrgroomConfig(max_rounds=3))
    _entry_probe(ctx, _verbs([], poll=poll, has_queued_fn=spy))
    assert ctx.state.phase is PRPhase.MERGED  # left terminal
    assert reads == []  # has_queued never read after the poll exits the gate


# ── _resolve_end_of_cycle ───────────────────────────────────────────────────


def test_resolve_end_of_cycle_quiesces_and_clears_error() -> None:
    state = _quiescent_state(last_error="STALE")
    ctx = _ctx(state)
    ctx.cycle_start_pushed_sha = state.last_pushed_head_sha
    ctx.cycle_start_error = "STALE"
    _resolve_end_of_cycle(ctx, _verbs([], has_queued=False))
    assert ctx.state.phase is PRPhase.QUIESCED
    assert ctx.state.quiescence.quiesced_at == _NOW
    assert ctx.state.last_error is None  # success clears the gating error


def test_resolve_end_of_cycle_gates_on_failed_item() -> None:
    item = ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="1"),
        author="copilot",
        body_excerpt="x",
        seen_at=_NOW,
        disposition=Disposition(kind=DispositionKind.FAILED, decided_at=_NOW, decided_by="claude"),
    )
    state = _quiescent_state(items=[item])
    ctx = _ctx(state)
    ctx.cycle_start_pushed_sha = ""
    ctx.cycle_start_error = None
    _resolve_end_of_cycle(ctx, _verbs([], has_queued=False))
    assert ctx.state.phase is PRPhase.HUMAN_GATED  # priority 2


def test_resolve_end_of_cycle_caps_when_queue_survives_at_cap() -> None:
    # H1 safety net: if a pipeline step ever leaves commits queued AT the cap (a future
    # commit-producing reply, a partial push), the honest has_queued read makes the
    # resolver's priority-1 gate here rather than silently pushing past the cap.
    state = _quiescent_state(round=3)
    ctx = _ctx(state, config=PrgroomConfig(max_rounds=3))
    ctx.cycle_start_pushed_sha = state.last_pushed_head_sha
    ctx.cycle_start_error = None
    _resolve_end_of_cycle(ctx, _verbs([], has_queued=True))  # queue survived
    assert ctx.state.phase is PRPhase.HUMAN_GATED
    assert ctx.state.last_error == ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED.value


def test_guarded_has_queued_routes_tagged_error_through_discipline() -> None:
    # PR #165: the cap re-arm + end-of-cycle reads call has_queued OUTSIDE the VerbStep
    # pipeline. A tagged failure must still go through handle_verb_error + persist +
    # flush + re-raise, never escape the lifecycle's error handling.
    from prgroom.lifecycle.run import _guarded_has_queued

    def boom(_ctx: RunContext) -> bool:
        raise PrgroomError(tier=Tier.RUNTIME_TERMINAL_USER, code=ErrorCode.RUNTIME_GH_TERMINAL)

    sink = RecordingSink()
    store = InMemoryStore()
    store.write(_REF, _quiescent_state(phase=PRPhase.FIXES_PENDING))
    ctx = _ctx(_quiescent_state(phase=PRPhase.FIXES_PENDING), store=store, sink=sink)
    with pytest.raises(PrgroomError) as excinfo:
        _guarded_has_queued(ctx, _verbs([], has_queued_fn=boom))
    assert excinfo.value.code is ErrorCode.RUNTIME_GH_TERMINAL
    assert ctx.state.phase is PRPhase.HUMAN_GATED  # handle_verb_error gated it
    assert len(sink.emitted) == 1  # flushed before the re-raise
    assert store.read(_REF).phase is PRPhase.HUMAN_GATED  # persisted


# ── full _run scenarios ─────────────────────────────────────────────────────


def test_run_full_cycle_to_quiesced() -> None:
    calls: list[str] = []
    store = CountingStore()
    store.write(_REF, _quiescent_state(phase=PRPhase.FIXES_PENDING))
    ctx = _ctx(_quiescent_state(phase=PRPhase.FIXES_PENDING), store=store)
    out = _run(ctx, _verbs(calls, has_queued=False))
    # poll-first, then the ordered pipeline; rereview skipped (no push this cycle).
    assert calls == ["poll", "cluster", "fix", "push", "reply", "resolve"]
    assert out.phase is PRPhase.QUIESCED


def test_run_cap_trip_gates_and_labels() -> None:
    calls: list[str] = []
    sink = RecordingSink()
    gh = FakeGh()
    store = InMemoryStore()
    store.write(_REF, _quiescent_state(phase=PRPhase.FIXES_PENDING, round=3))
    ctx = _ctx(
        _quiescent_state(phase=PRPhase.FIXES_PENDING, round=3),
        store=store,
        sink=sink,
        gh=gh,
        config=PrgroomConfig(max_rounds=3),
    )
    out = _run(ctx, _verbs(calls, has_queued=True))
    assert "push" not in calls  # cap guard refused the push
    assert out.phase is PRPhase.HUMAN_GATED
    assert out.last_error == ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED.value
    assert len(sink.emitted) == 1  # one lifecycle escalation
    assert gh.added == [(_REF, "human-review-required")]  # §4.7 label added


def test_run_rereview_runs_after_push_uploads() -> None:
    calls: list[str] = []
    reviewers = {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.NOT_REQUESTED,
            required=True,
            last_request_at=_NOW,
        )
    }
    store = InMemoryStore()
    store.write(_REF, _quiescent_state(phase=PRPhase.FIXES_PENDING, reviewers=reviewers))

    def push(ctx: RunContext) -> PRGroomingState:
        calls.append("push")
        ctx.state.last_pushed_head_sha = "newsha"  # uploaded a commit
        ctx.state.last_review_invalidated_sha = "newsha"  # push.py invalidates review at HEAD
        return ctx.state

    def wait(ctx: RunContext) -> PRGroomingState:
        # The push resolves the cycle to awaiting-review; end the loop on the next wait.
        calls.append("wait")
        ctx.state.phase = PRPhase.MERGED
        return ctx.state

    ctx = _ctx(_quiescent_state(phase=PRPhase.FIXES_PENDING, reviewers=reviewers), store=store)
    _run(ctx, _verbs(calls, has_queued=False, push=push, wait=wait))
    assert "rereview" in calls  # guard satisfied: pushed + required reviewer stale


def test_run_interactive_returns_at_awaiting_review_without_wait() -> None:
    calls: list[str] = []

    def poll(ctx: RunContext) -> PRGroomingState:
        calls.append("poll")
        ctx.state.phase = PRPhase.AWAITING_REVIEW
        return ctx.state

    ctx = _ctx(_quiescent_state(phase=PRPhase.AWAITING_REVIEW), mode=Mode.INTERACTIVE)
    out = _run(ctx, _verbs(calls, poll=poll))
    assert "wait" not in calls  # interactive never waits
    assert out.phase is PRPhase.AWAITING_REVIEW


def test_run_autonomous_waits_at_awaiting_review() -> None:
    calls: list[str] = []

    def poll(ctx: RunContext) -> PRGroomingState:
        calls.append("poll")
        ctx.state.phase = PRPhase.AWAITING_REVIEW
        return ctx.state

    def wait(ctx: RunContext) -> PRGroomingState:
        calls.append("wait")
        ctx.state.phase = PRPhase.MERGED  # end the loop
        return ctx.state

    ctx = _ctx(_quiescent_state(phase=PRPhase.AWAITING_REVIEW), mode=Mode.AUTONOMOUS)
    _run(ctx, _verbs(calls, poll=poll, wait=wait))
    assert calls.count("wait") == 1


def test_run_first_invocation_bootstraps() -> None:
    calls: list[str] = []
    store = InMemoryStore()  # empty — no state for _REF

    def poll(ctx: RunContext) -> PRGroomingState:
        calls.append("poll")
        ctx.state.phase = PRPhase.MERGED  # short-circuit after bootstrap
        return ctx.state

    ctx = _ctx(_quiescent_state(phase=PRPhase.IDLE), store=store)
    out = _run(ctx, _verbs(calls, poll=poll))
    assert out.phase is PRPhase.MERGED
    assert store.read(_REF).schema_version == 1  # bootstrapped + persisted


def test_run_terminal_user_error_gates_and_propagates() -> None:
    sink = RecordingSink()
    err = PrgroomError(tier=Tier.RUNTIME_TERMINAL_USER, code=ErrorCode.RUNTIME_GH_TERMINAL)
    ctx = _ctx(_quiescent_state(phase=PRPhase.FIXES_PENDING), sink=sink)
    with pytest.raises(PrgroomError) as excinfo:
        _run(ctx, _verbs([], poll=_raiser(err)))
    assert excinfo.value.tier is Tier.RUNTIME_TERMINAL_USER
    assert ctx.state.phase is PRPhase.HUMAN_GATED
    assert len(sink.emitted) == 1  # escalate flushed before propagating


def test_run_merged_is_absorbing() -> None:
    calls: list[str] = []
    ctx = _ctx(_quiescent_state(phase=PRPhase.MERGED))
    out = _run(ctx, _verbs(calls))
    assert calls == []  # terminal at loop top — no poll, no pipeline
    assert out.phase is PRPhase.MERGED


def test_run_interactive_idle_emits_advisory(capsys: pytest.CaptureFixture[str]) -> None:
    # Interactive at idle returns 0 without waiting and emits the one-line advisory so
    # the caller can tell "nothing to do" from "completed work" (§3.3).
    ctx = _ctx(_quiescent_state(phase=PRPhase.IDLE), mode=Mode.INTERACTIVE)
    out = _run(ctx, _verbs([]))  # default poll keeps the phase at idle
    assert out.phase is PRPhase.IDLE
    assert "phase=idle" in capsys.readouterr().err


class _CorruptStore:
    """A store whose read raises a parse/schema error — exercises _read_or_bootstrap."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def read(self, _ref: PRRef) -> PRGroomingState:
        raise self._exc

    def write(self, ref: PRRef, state: PRGroomingState) -> None:  # pragma: no cover - unused
        del ref, state


@pytest.mark.parametrize(
    ("exc", "tier"),
    [
        (StateCorruptError("bad json"), Tier.STATE_CORRUPT),
        (SchemaUnknownError("v999"), Tier.STATE_SCHEMA_UNKNOWN),
    ],
)
def test_run_maps_unreadable_state_to_state_tier(exc: Exception, tier: Tier) -> None:
    ctx = _ctx(_quiescent_state(), store=_CorruptStore(exc))
    with pytest.raises(PrgroomError) as excinfo:
        _run(ctx, _verbs([]))
    assert excinfo.value.tier is tier  # § 3.3 read-failure mapping (exit 78)


def test_run_drives_real_reply_posts_for_replyable_item() -> None:
    # The §3.3 pipeline-slotting pin: the loop wires the REAL `_reply` adapter. Drive a
    # FIXED REVIEW_THREAD item through a cycle and assert the real reply fired — a POST
    # to the thread-reply endpoint and `replied` flipped — while the cycle still quiesces.
    item = ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="1"),
        author="copilot",
        body_excerpt="x",
        seen_at=_NOW,
        disposition=Disposition(
            kind=DispositionKind.FIXED, decided_at=_NOW, decided_by="claude", commits=["abc1234"]
        ),
    )
    calls: list[str] = []
    gh = FakeGh()
    store = InMemoryStore()
    store.write(_REF, _quiescent_state(phase=PRPhase.FIXES_PENDING, items=[item]))
    ctx = _ctx(_quiescent_state(phase=PRPhase.FIXES_PENDING, items=[item]), store=store, gh=gh)
    out = _run(ctx, _verbs(calls, has_queued=False, reply=_reply))  # real reply adapter
    assert out.phase is PRPhase.QUIESCED
    assert out.items[0].replied is True
    assert gh.rest_calls == [
        ("POST", "repos/octo/demo/pulls/7/comments/1/replies", {"body": "Fixed in abc1234."})
    ]


# ── run_lifecycle wrapper ───────────────────────────────────────────────────


def test_run_lifecycle_lock_held_returns_75() -> None:
    store = InMemoryStore()
    store.write(_REF, _quiescent_state())
    assert store.try_acquire(_REF) is True  # a live holder owns the lock
    try:
        code = run_lifecycle(
            store=store,
            ref=_REF,
            gh=FakeGh(),  # type: ignore[arg-type]
            git=object(),  # type: ignore[arg-type]
            deps=_DEPS,
            config=PrgroomConfig(),
            sink=RecordingSink(),  # type: ignore[arg-type]
            mode=Mode.INTERACTIVE,
            cluster_dispatcher=object(),  # type: ignore[arg-type] - never reached
            cluster_decided_by="x",
            fix_dispatcher=object(),  # type: ignore[arg-type]
            fix_decided_by="x",
        )
    finally:
        store.release(_REF)
    assert code == 75  # PRECONDITION_LOCK_HELD -> EX_TEMPFAIL


def test_verbs_system_adapters_delegate_to_real_verbs(monkeypatch: pytest.MonkeyPatch) -> None:
    # The production ctx→verb adapters are thin delegations; assert Verbs.system binds
    # each to the right lifecycle verb (with the dispatchers/sink/scratch threaded)
    # without needing real gh/git — the underlying verbs are monkeypatched recorders.
    from prgroom.lifecycle import run as run_mod

    calls: list[str] = []

    def rec(name: str):
        def fn(state: PRGroomingState, **_kw: object) -> PRGroomingState:
            calls.append(name)
            return state

        return fn

    monkeypatch.setattr(run_mod, "poll_pr", rec("poll"))
    monkeypatch.setattr(run_mod, "cluster_pr", rec("cluster"))
    monkeypatch.setattr(run_mod, "fix_pr", rec("fix"))
    monkeypatch.setattr(run_mod, "push_pr", rec("push"))
    monkeypatch.setattr(run_mod, "rereview_pr", rec("rereview"))
    monkeypatch.setattr(run_mod, "resolve_pr", rec("resolve"))
    monkeypatch.setattr(run_mod, "reply_pr", rec("reply"))
    monkeypatch.setattr(run_mod, "wait_pr", rec("wait"))
    monkeypatch.setattr(
        run_mod, "has_queued_fix_commits", lambda *_a: calls.append("has_queued") or True
    )

    verbs = Verbs.system(
        cluster_dispatcher=object(),  # type: ignore[arg-type]
        cluster_decided_by="claude",
        fix_dispatcher=object(),  # type: ignore[arg-type]
        fix_decided_by="claude",
    )
    ctx = _ctx(_quiescent_state())
    for adapter in (
        verbs.poll,
        verbs.cluster,
        verbs.fix,
        verbs.push,
        verbs.rereview,
        verbs.reply,
        verbs.resolve,
        verbs.wait,
    ):
        adapter(ctx)
    assert verbs.has_queued(ctx) is True
    assert calls == [
        "poll",
        "cluster",
        "fix",
        "push",
        "rereview",
        "reply",
        "resolve",
        "wait",
        "has_queued",
    ]


def test_build_pipeline_order() -> None:
    pipeline = _build_pipeline(_verbs([]))
    assert [s.name for s in pipeline] == [
        "cluster",
        "fix",
        "cap-guard",
        "push",
        "reply",
        "resolve",
        "rereview",
    ]
    assert pipeline[6].guard is _rereview_guard  # only rereview is guarded, and it runs last
