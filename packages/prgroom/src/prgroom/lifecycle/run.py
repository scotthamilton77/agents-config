"""``run`` — the aggregate verb that threads the lifecycle under one lock (§3.3).

``run`` is the only verb that acquires the PR lock **once** and drives the lock-held
internals in sequence (the §3.3 exception to the per-verb locking rule). It is
long-running and blocking for non-terminal phases; when the phase reaches
``quiesced`` / ``human-gated`` / ``merged`` it flushes terminal signals and returns,
releasing the lock so external triggers can act.

The §3.3 pseudocode is an 8x-repeated try/except. This implementation collapses that
into a **single shared error site** — :func:`_execute_step` — through which every
verb invocation funnels: it runs the verb, persists state (the per-internal write
discipline, so a crash leaves the on-disk state at the last completed verb), and on a
tagged error applies :func:`~prgroom.lifecycle.verb_error.handle_verb_error` and either
proceeds (``CONTINUE``) or flushes the two terminal signals and re-raises
(``PROPAGATE``). The cycle is modelled as an ordered ``list`` of :class:`VerbStep`s.

The verbs are injected as a :class:`Verbs` bundle so the orchestration is unit-testable
without gh/git — production wires :meth:`Verbs.system`; tests pass fakes. The two
flush hooks (``escalate_if_needed`` + ``request_human_review_if_needed``) fire at
exactly two dedup-safe sites: the loop-top terminal-for-CLI check, and immediately
before each ``PROPAGATE`` re-raise.
"""

from __future__ import annotations

import dataclasses
import sys
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from prgroom.errors import ErrorCode, PreconditionError, PrgroomError, Tier, exit_code_for_tier
from prgroom.lifecycle import is_graph_terminal, is_terminal_for_cli
from prgroom.lifecycle.cluster import cluster_pr
from prgroom.lifecycle.escalation import escalate_if_needed, request_human_review_if_needed
from prgroom.lifecycle.fix import fix_pr
from prgroom.lifecycle.locking import run_locked, with_lock
from prgroom.lifecycle.poll import poll_pr
from prgroom.lifecycle.predicates import (
    has_required_reviewers_to_refresh,
    new_lifecycle_gate_this_cycle,
    push_uploaded_commits_this_cycle,
)
from prgroom.lifecycle.push import has_queued_fix_commits, push_pr
from prgroom.lifecycle.quiescence import quiescence_predicate
from prgroom.lifecycle.reply import reply_pr
from prgroom.lifecycle.rereview import rereview_pr
from prgroom.lifecycle.resolve import resolve_pr
from prgroom.lifecycle.resolver import resolve_end_of_cycle_phase
from prgroom.lifecycle.verb_error import VerbDisposition, handle_verb_error
from prgroom.lifecycle.wait import SignalCancelToken, wait_pr
from prgroom.prsession.enums import PRPhase
from prgroom.prsession.state import bootstrap_state
from prgroom.prsession.store import SchemaUnknownError, StateCorruptError, StateNotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from types import FrameType

    from prgroom.agent.contracts import ClusterContract, FixContract
    from prgroom.config import PrgroomConfig
    from prgroom.deps import Deps
    from prgroom.escalation import Sink
    from prgroom.gh.client import GhClient
    from prgroom.git.client import GitClient
    from prgroom.lifecycle.wait import CancelToken
    from prgroom.prsession.pr_ref import PRRef
    from prgroom.prsession.state import PRGroomingState
    from prgroom.prsession.store import Store

# Phases that drive into the §3.3 cycle (poll-first, then branch). Any other phase is
# terminal-for-CLI (handled at loop top) — there is no separate "active" enum.
_WAITING_PHASES: frozenset[PRPhase] = frozenset({PRPhase.IDLE, PRPhase.AWAITING_REVIEW})
_IDLE_ADVISORY = "prgroom: nothing to do — PR has no commits yet (phase=idle)"


class Mode(StrEnum):
    """Whether ``run`` blocks on ``_wait`` (autonomous) or hands the wait back (interactive)."""

    INTERACTIVE = "interactive"
    AUTONOMOUS = "autonomous"


@dataclass(slots=True)
class RunContext:
    """The mutable per-invocation context threaded through the run-loop.

    ``state`` is reassigned by every step; ``cycle_start_pushed_sha`` / ``cycle_start_error``
    are the per-cycle snapshots the §3.4 cycle-relative predicates read (the spec keeps
    no stored "prior cycle" field — the loop captures them at cycle entry).
    """

    store: Store
    ref: PRRef
    gh: GhClient
    git: GitClient
    deps: Deps
    config: PrgroomConfig
    sink: Sink
    mode: Mode
    cancel: CancelToken
    state: PRGroomingState
    cycle_start_pushed_sha: str = ""
    cycle_start_error: str | None = None


@dataclass(frozen=True, slots=True)
class VerbStep:
    """One step in the run-loop pipeline: a named, optionally-guarded ctx→state call.

    ``run`` mutates and returns ``ctx.state``; ``guard`` (when present) decides whether
    the step runs at all this cycle (the post-push ``_rereview`` is the only guarded step).
    """

    name: str
    run: Callable[[RunContext], PRGroomingState]
    guard: Callable[[RunContext], bool] | None = None


@dataclass(frozen=True, slots=True)
class Verbs:
    """The injected lock-held internals the run-loop drives (§3.3).

    Each is a ``ctx → state`` adapter over a lifecycle verb, except ``has_queued`` (the
    effectful §3.5 cap read). Injected so the orchestration is testable with fakes;
    :meth:`system` wires the production verbs.
    """

    poll: Callable[[RunContext], PRGroomingState]
    cluster: Callable[[RunContext], PRGroomingState]
    fix: Callable[[RunContext], PRGroomingState]
    push: Callable[[RunContext], PRGroomingState]
    rereview: Callable[[RunContext], PRGroomingState]
    reply: Callable[[RunContext], PRGroomingState]
    resolve: Callable[[RunContext], PRGroomingState]
    wait: Callable[[RunContext], PRGroomingState]
    has_queued: Callable[[RunContext], bool]

    @classmethod
    def system(
        cls,
        *,
        cluster_dispatcher: ClusterContract,
        cluster_decided_by: str,
        fix_dispatcher: FixContract,
        fix_decided_by: str,
    ) -> Verbs:
        """Wire the production verbs; cluster/fix capture their dispatchers + decided_by."""

        def cluster(ctx: RunContext) -> PRGroomingState:
            with TemporaryDirectory(prefix="prgroom-cluster-") as scratch:
                return cluster_pr(
                    ctx.state,
                    ref=ctx.ref,
                    gh=ctx.gh,
                    git=ctx.git,
                    deps=ctx.deps,
                    config=ctx.config,
                    dispatcher=cluster_dispatcher,
                    decided_by=cluster_decided_by,
                    scratch_dir=Path(scratch),
                )

        def fix(ctx: RunContext) -> PRGroomingState:
            with TemporaryDirectory(prefix="prgroom-fix-") as scratch:
                return fix_pr(
                    ctx.state,
                    ref=ctx.ref,
                    gh=ctx.gh,
                    git=ctx.git,
                    deps=ctx.deps,
                    config=ctx.config,
                    dispatcher=fix_dispatcher,
                    sink=ctx.sink,
                    decided_by=fix_decided_by,
                    scratch_dir=Path(scratch),
                )

        return cls(
            poll=_poll,
            cluster=cluster,
            fix=fix,
            push=_push,
            rereview=_rereview,
            reply=_reply,
            resolve=_resolve,
            wait=_wait,
            has_queued=_has_queued,
        )


# ── production ctx → verb adapters (no dispatcher capture needed) ────────────


def _poll(ctx: RunContext) -> PRGroomingState:
    return poll_pr(ctx.state, ref=ctx.ref, gh=ctx.gh, deps=ctx.deps, config=ctx.config)


def _push(ctx: RunContext) -> PRGroomingState:
    return push_pr(ctx.state, ref=ctx.ref, gh=ctx.gh, git=ctx.git, config=ctx.config)


def _rereview(ctx: RunContext) -> PRGroomingState:
    return rereview_pr(ctx.state, ref=ctx.ref, gh=ctx.gh, deps=ctx.deps)


def _resolve(ctx: RunContext) -> PRGroomingState:
    return resolve_pr(ctx.state, gh=ctx.gh)


def _reply(ctx: RunContext) -> PRGroomingState:
    return reply_pr(ctx.state)


def _has_queued(ctx: RunContext) -> bool:
    return has_queued_fix_commits(ctx.gh, ctx.git, ctx.ref)


def _wait(ctx: RunContext) -> PRGroomingState:
    return wait_pr(
        ctx.state,
        poll=lambda s: poll_pr(s, ref=ctx.ref, gh=ctx.gh, deps=ctx.deps, config=ctx.config),
        store=ctx.store,
        ref=ctx.ref,
        cancel=ctx.cancel,
        now=ctx.deps.clock.now,
        poll_interval=ctx.config.poll_interval,
        idle_threshold=ctx.config.idle_threshold,
    )


# ── the run-loop ────────────────────────────────────────────────────────────


def run_lifecycle(
    *,
    store: Store,
    ref: PRRef,
    gh: GhClient,
    git: GitClient,
    deps: Deps,
    config: PrgroomConfig,
    sink: Sink,
    mode: Mode,
    cluster_dispatcher: ClusterContract,
    cluster_decided_by: str,
    fix_dispatcher: FixContract,
    fix_decided_by: str,
) -> int:
    """Run the lifecycle under one lock; return the §3.3 exit code (the CLI entry).

    Installs OS signal handlers (autonomous only — interactive leaves the default
    Ctrl-C) wiring SIGINT/SIGTERM into the cancel token ``_wait`` honors, acquires the
    PR lock once via ``run_locked``, and maps any tier-tagged error to its exit code.
    A ``PRECONDITION_LOCK_HELD`` on acquire (concurrent run) maps to 75.
    """
    cancel = SignalCancelToken()
    ctx = RunContext(
        store=store,
        ref=ref,
        gh=gh,
        git=git,
        deps=deps,
        config=config,
        sink=sink,
        mode=mode,
        cancel=cancel,
        state=bootstrap_state(ref, now=deps.clock.now()),  # placeholder; _run reads/bootstraps
    )
    verbs = Verbs.system(
        cluster_dispatcher=cluster_dispatcher,
        cluster_decided_by=cluster_decided_by,
        fix_dispatcher=fix_dispatcher,
        fix_decided_by=fix_decided_by,
    )
    handlers = _signal_handlers(cancel) if mode is Mode.AUTONOMOUS else nullcontext()
    with handlers:
        try:
            run_locked(store, ref, lambda: _run(ctx, verbs))
        except PrgroomError as err:
            return _report(err)
    return 0


def _report(err: PrgroomError) -> int:
    """Render the §1 what/why/how block to stderr and return the tier's exit code (§3.3).

    ``run`` / ``wait`` own their terminal reporting (they catch the propagated tagged
    error rather than letting it surface as a raw traceback), so the operator/agent
    sees the structured failure and the documented sysexits code.
    """
    sys.stderr.write(err.render() + "\n")
    return exit_code_for_tier(err)


def wait_lifecycle(
    *,
    store: Store,
    ref: PRRef,
    gh: GhClient,
    deps: Deps,
    config: PrgroomConfig,
) -> int:
    """Run the standalone ``wait`` verb under one lock; return its §3.3 exit code.

    Like ``run`` it installs SIGINT/SIGTERM handlers wiring the cancel token ``_wait``
    honors (a cancelled wait exits 130/143, never the scheduler-retry 75) and acquires
    the lock once. The §3.2 ``wait`` preconditions gate up front: ``fixes-pending`` has
    actionable work (→ ``PRECONDITION_WAIT_NOT_APPLICABLE``, exit 2); ``merged`` is a
    no-op; a never-polled PR → ``PRECONDITION_NO_STATE`` (exit 2).
    """
    cancel = SignalCancelToken()
    with _signal_handlers(cancel):
        try:
            with_lock(store, ref, lambda: _wait_verb(store, ref, gh, deps, config, cancel))
        except PrgroomError as err:
            return _report(err)
    return 0


def _wait_verb(
    store: Store,
    ref: PRRef,
    gh: GhClient,
    deps: Deps,
    config: PrgroomConfig,
    cancel: SignalCancelToken,
) -> PRGroomingState:
    """Lock-held body of the ``wait`` verb: precondition-gate, then block in ``wait_pr``."""
    try:
        state = store.read(ref)
    except StateNotFoundError as exc:
        raise PreconditionError(ErrorCode.PRECONDITION_NO_STATE, detail=ref.display()) from exc
    if state.phase is PRPhase.FIXES_PENDING:
        raise PreconditionError(ErrorCode.PRECONDITION_WAIT_NOT_APPLICABLE, detail=ref.display())
    if is_graph_terminal(state.phase):
        return state  # merged is absorbing — nothing to wait on
    return wait_pr(
        state,
        poll=lambda s: poll_pr(s, ref=ref, gh=gh, deps=deps, config=config),
        store=store,
        ref=ref,
        cancel=cancel,
        now=deps.clock.now,
        poll_interval=config.poll_interval,
        idle_threshold=config.idle_threshold,
    )


def _run(ctx: RunContext, verbs: Verbs) -> PRGroomingState:
    """Drive the §3.3 cycle under the held lock. Caller must hold the per-ref lock."""
    ctx.state = _read_or_bootstrap(ctx)
    _entry_probe(ctx, verbs)
    pipeline = _build_pipeline(verbs)

    while True:
        if is_terminal_for_cli(ctx.state.phase):  # loop-top flush site
            _flush_terminal_signals(ctx)
            return ctx.state

        _execute_step(VerbStep("poll", verbs.poll), ctx)
        if is_terminal_for_cli(ctx.state.phase):
            continue  # loop top flushes + returns

        if ctx.state.phase in _WAITING_PHASES:
            if ctx.mode is Mode.INTERACTIVE:
                if ctx.state.phase is PRPhase.IDLE:
                    sys.stderr.write(_IDLE_ADVISORY + "\n")
                return ctx.state  # interactive: the caller owns the wait
            # Termination guarantee: the loop has no iteration cap (per §4.2 "no hard
            # wait-timeout in MVP"); it relies on `_wait` BLOCKING and only returning on
            # a phase move off `_WAITING_PHASES` or a quiescence trip (→ QUIESCED). A
            # `_wait` that returned while still in a waiting phase would hot-loop — that
            # is a `_wait` contract violation, not a condition the loop can recover from.
            _execute_step(VerbStep("wait", verbs.wait), ctx)
            continue

        # === FIXES_PENDING: the ordered pipeline ===
        ctx.cycle_start_pushed_sha = ctx.state.last_pushed_head_sha
        ctx.cycle_start_error = ctx.state.last_error
        pipeline_terminated = False
        for step in pipeline:
            _execute_step(step, ctx)
            if is_terminal_for_cli(ctx.state.phase):
                # A step set a terminal-for-CLI phase on a clean return (today only the
                # pre-push cap guard does — verb errors gate via PROPAGATE, which
                # re-raises out of the loop). Skip end-of-cycle resolution.
                pipeline_terminated = True
                break
        if not pipeline_terminated:
            _resolve_end_of_cycle(ctx, verbs)
        # loop continues; the loop top handles the terminal phase + flush


def _build_pipeline(verbs: Verbs) -> list[VerbStep]:
    """The ordered FIXES_PENDING pipeline (§3.3): cluster→fix→cap→push→[rereview]→reply→resolve."""
    return [
        VerbStep("cluster", verbs.cluster),
        VerbStep("fix", verbs.fix),
        VerbStep("cap-guard", _cap_guard_step(verbs)),
        VerbStep("push", verbs.push),
        VerbStep("rereview", verbs.rereview, guard=_rereview_guard),
        VerbStep("reply", verbs.reply),
        VerbStep("resolve", verbs.resolve),
    ]


def _cap_guard_step(verbs: Verbs) -> Callable[[RunContext], PRGroomingState]:
    """Build the pre-push hard-cap guard (§3.5): refuse the cap-tripping push.

    When commits are queued AND ``round >= max_rounds``, set ``human-gated`` +
    ``LIFECYCLE_HARD_CAP_EXCEEDED`` and clear ``lifecycle_escalation_filed`` so the
    loop-top flush fires exactly one Sink event; the push is then never reached. The
    effectful ``has_queued`` read can raise (gh transient) — routed through the single
    error site like any verb.
    """

    def cap_guard(ctx: RunContext) -> PRGroomingState:
        if verbs.has_queued(ctx) and ctx.state.round >= ctx.config.max_rounds:
            ctx.state.phase = PRPhase.HUMAN_GATED
            ctx.state.last_error = ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED.value
            ctx.state.lifecycle_escalation_filed = False
        return ctx.state

    return cap_guard


def _rereview_guard(ctx: RunContext) -> bool:
    """True iff this cycle's push uploaded commits AND a required reviewer needs refresh (§3.3)."""
    return push_uploaded_commits_this_cycle(
        ctx.state, cycle_start_pushed_sha=ctx.cycle_start_pushed_sha
    ) and has_required_reviewers_to_refresh(ctx.state)


def _execute_step(step: VerbStep, ctx: RunContext) -> None:
    """Run one step through the single shared error site (§3.3).

    Skips the step when its guard is unmet. On success, persists state (the
    per-internal write discipline). On a tagged error, applies ``handle_verb_error``
    (which mutates state in place — the verb's own work is discarded because it
    raised), persists, then either proceeds (``CONTINUE``) or flushes the two terminal
    signals and re-raises (``PROPAGATE``).
    """
    if step.guard is not None and not step.guard(ctx):
        return
    try:
        ctx.state = step.run(ctx)
        ctx.store.write(ctx.ref, ctx.state)
    except PrgroomError as err:
        disposition = handle_verb_error(err, ctx.state)
        ctx.store.write(ctx.ref, ctx.state)
        if disposition is VerbDisposition.PROPAGATE:
            _flush_terminal_signals(ctx)  # pre-PROPAGATE flush site
            raise


def _flush_terminal_signals(ctx: RunContext) -> None:
    """Fire both terminal-signal hooks (§3.3, §4.7); each is idempotent + best-effort."""
    escalate_if_needed(ctx.state, sink=ctx.sink, store=ctx.store, ref=ctx.ref)
    request_human_review_if_needed(
        ctx.state,
        gh=ctx.gh,
        store=ctx.store,
        ref=ctx.ref,
        auto_request=ctx.config.auto_request_human_review,
    )


def _guarded_has_queued(ctx: RunContext, verbs: Verbs) -> bool:
    """Read ``has_queued`` (an effectful gh/git read) under the §3.3 error discipline.

    The §3.5 cap re-arm (entry probe) and the end-of-cycle resolver read the queue
    OUTSIDE the VerbStep pipeline, so they cannot rely on ``_execute_step``. A tagged
    failure here gets the same treatment a verb error would: ``handle_verb_error``
    applies its per-tier mutation, the state is persisted, the two terminal signals
    flush, and the error re-raises to ``run``/``wait``'s reporting wrapper — so a
    vanished PR (404 → ``RUNTIME_GH_TERMINAL``) or a gh blip never escapes the
    lifecycle's tagged-error handling. (A gh read only ever yields ``PROPAGATE`` tiers;
    ``CONTINUE`` is reserved for ``CONTRACT_AUDIT_FAILED``, which this read cannot
    raise.)
    """
    try:
        return verbs.has_queued(ctx)
    except PrgroomError as err:
        handle_verb_error(err, ctx.state)
        ctx.store.write(ctx.ref, ctx.state)
        _flush_terminal_signals(ctx)
        raise


def _read_or_bootstrap(ctx: RunContext) -> PRGroomingState:
    """Read the PR's state, bootstrapping a zero-value state on first contact (§3.3).

    Auto-bootstrap is unconditional (absence is a discovery condition, not a
    precondition failure). A corrupt/unknown-schema read maps to its STATE_* tier so
    the run exits 78 rather than crashing with a raw ``ValueError``.
    """
    try:
        return ctx.store.read(ctx.ref)
    except StateNotFoundError:
        state = bootstrap_state(ctx.ref, now=ctx.deps.clock.now())
        ctx.store.write(ctx.ref, state)
        return state
    except SchemaUnknownError as exc:
        raise PrgroomError(
            tier=Tier.STATE_SCHEMA_UNKNOWN, code=ErrorCode.STATE_SCHEMA_UNKNOWN, detail=str(exc)
        ) from exc
    except StateCorruptError as exc:
        raise PrgroomError(
            tier=Tier.STATE_CORRUPT, code=ErrorCode.STATE_CORRUPT, detail=str(exc)
        ) from exc


def _entry_probe(ctx: RunContext, verbs: Verbs) -> None:
    """Probe external transitions + re-arm the cap when entering at a terminal phase (§3.3/§3.5).

    From ``quiesced`` / ``human-gated`` run ``_poll`` once to detect an external merge
    or a manual fix-push that cleared the gate; then, if still hard-cap-gated and the
    cap no longer trips, clear the gate and advance to ``fixes-pending`` for the refused
    commits to push. The cap stays gated only while it still trips — ``round >=
    max_rounds`` AND commits are still queued (the exact inverse of the §3.5 cap-trip).
    So a bare re-run with the refused commits still queued stays gated, whereas raising
    ``--max-rounds`` (round now below the cap) OR an emptied queue re-arms.
    """
    if ctx.state.phase not in {PRPhase.QUIESCED, PRPhase.HUMAN_GATED}:
        return
    _execute_step(VerbStep("poll", verbs.poll), ctx)
    # Probe the cap ONLY when the poll left us still hard-cap-gated. A poll that moved
    # the PR out of human-gated (external merge, operator fix-push) must NOT trigger the
    # effectful has_queued gh/git read — it is wasted there and a transient failure would
    # turn an otherwise-clean terminal run into an error. The phase + cap-error checks
    # short-circuit before the read; within them, `round >= max_rounds` is checked first
    # so a raised --max-rounds also short-circuits the read.
    if (
        ctx.state.phase is PRPhase.HUMAN_GATED
        and ctx.state.last_error == ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED.value
        and not (ctx.state.round >= ctx.config.max_rounds and _guarded_has_queued(ctx, verbs))
    ):
        ctx.state.phase = PRPhase.FIXES_PENDING
        ctx.state.last_error = None
        ctx.state.lifecycle_escalation_filed = False
        ctx.state.human_review_label_added = False
        ctx.store.write(ctx.ref, ctx.state)


def _resolve_end_of_cycle(ctx: RunContext, verbs: Verbs) -> None:
    """Apply the §3.2 end-of-cycle phase cascade + the §3.3 reset-on-success (writes state).

    Reads ``has_queued_commits`` honestly (``verbs.has_queued``) rather than assuming it
    is false. In the normal path the pre-push cap guard already refused any cap-tripping
    push and a non-capped push consumed the queue, so this is false — but reading it for
    real keeps the resolver's priority-1 a LIVE safety net: if any pipeline step ever
    leaves commits queued at the cap (a future commit-producing ``reply``, a partial
    push), the cap still gates here rather than silently pushing past it. On a
    non-``human-gated`` resolution the gating error + both dedup flags clear (success); a
    fresh ``human-gated`` gate clears ``lifecycle_escalation_filed`` once so the loop-top
    emits a single event.
    """
    now = ctx.deps.clock.now()
    resolved = resolve_end_of_cycle_phase(
        ctx.state,
        now=now,
        max_rounds=ctx.config.max_rounds,
        has_queued_commits=_guarded_has_queued(ctx, verbs),
        pushed_this_cycle=push_uploaded_commits_this_cycle(
            ctx.state, cycle_start_pushed_sha=ctx.cycle_start_pushed_sha
        ),
        quiescent=quiescence_predicate(
            ctx.state, now=now, idle_threshold=ctx.config.idle_threshold
        ),
    )
    ctx.state.phase = resolved.phase
    if resolved.last_error is not None:
        ctx.state.last_error = resolved.last_error
    if resolved.quiesced_at is not None:
        ctx.state.quiescence = dataclasses.replace(
            ctx.state.quiescence, quiesced_at=resolved.quiesced_at
        )

    if resolved.phase is PRPhase.HUMAN_GATED:
        if new_lifecycle_gate_this_cycle(ctx.state, previous_error=ctx.cycle_start_error):
            ctx.state.lifecycle_escalation_filed = False
    else:
        # Successful cycle completion clears any prior gating error + dedup flags (§3.3).
        ctx.state.last_error = None
        ctx.state.lifecycle_escalation_filed = False
        ctx.state.human_review_label_added = False
    ctx.store.write(ctx.ref, ctx.state)


@contextmanager
def _signal_handlers(cancel: SignalCancelToken) -> Iterator[None]:
    """Route SIGINT/SIGTERM into ``cancel`` for the duration, restoring prior handlers.

    Installed for autonomous runs only (the blocking ``_wait`` honors the token);
    interactive runs keep the default Ctrl-C. ``signal.signal`` requires the main
    thread — the CLI entry point satisfies this.
    """
    import signal

    def handler(signum: int, _frame: FrameType | None) -> None:
        cancel.trip(signum)

    signals = (signal.SIGINT, signal.SIGTERM)
    previous = {sig: signal.getsignal(sig) for sig in signals}
    for sig in signals:
        signal.signal(sig, handler)
    try:
        yield
    finally:
        for sig, prev in previous.items():
            signal.signal(sig, prev)
