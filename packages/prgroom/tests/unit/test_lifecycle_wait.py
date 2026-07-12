"""Tests for ``wait_pr`` — the lock-held ``_wait`` blocking poll loop (§4.2).

``_wait`` sleeps ``poll_interval`` (interruptibly), polls, and returns on one of four
wake events: a signal-cancel (loop-top OR mid-sleep) raising ``RUNTIME_CANCELLED``; the
polled phase moving off ``{awaiting-review, idle}``; or the quiescence predicate
tripping (writes ``quiesced`` + ``quiesced_at``). A ``_poll`` error propagates. There is
no hard wait-timeout in MVP.

The seams are an injected ``poll`` callable (decoupled from gh — pure to drive) and a
``CancelToken`` fake whose ``is_set`` / ``wait`` are scripted so the loop-top and
mid-sleep cancel branches are exercised independently. ``poll_interval`` is zero so the
real ``threading.Event.wait`` (when used) does not sleep.
"""

from __future__ import annotations

import signal
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.lifecycle.wait import SignalCancelToken, cancelled_error, wait_pr
from prgroom.prsession.enums import PRPhase
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import PRGroomingState, QuiescenceState

_REF = PRRef(owner="octo", repo="demo", number=7)
_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_LATER = _T0 + timedelta(hours=1)  # past any idle threshold, so the idle gate is satisfied
_ZERO = timedelta(0)


class FakeCancel:
    """A scripted cancel token: ``is_set`` and ``wait`` return from queued booleans."""

    def __init__(
        self, *, is_set: bool = False, wait: bool = False, signum: int = signal.SIGINT
    ) -> None:
        self._is_set = is_set
        self._wait = wait
        self.signum = signum

    def is_set(self) -> bool:
        return self._is_set

    def wait(self, _seconds: float) -> bool:
        return self._wait


def _state(
    *,
    phase: PRPhase = PRPhase.AWAITING_REVIEW,
    ci_state: str = "success",
    last_activity_at: datetime = _T0,
) -> PRGroomingState:
    return PRGroomingState(
        pr=_REF,
        phase=phase,
        pr_review_retries_used=1,
        last_polled_at=_T0,
        last_activity_at=last_activity_at,
        quiescence=QuiescenceState(ci_state=ci_state),
    )


def _now(value: datetime = _LATER) -> Callable[[], datetime]:
    return lambda: value


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


# ── wake event 1 + the interruptible sleep: signal cancel ───────────────────


def test_cancel_at_loop_top_raises_runtime_cancelled(store: InMemoryStore) -> None:
    polled = []

    def poll(s: PRGroomingState) -> PRGroomingState:
        polled.append(s)
        return s

    with pytest.raises(PrgroomError) as excinfo:
        wait_pr(
            _state(),
            poll=poll,
            store=store,
            ref=_REF,
            cancel=FakeCancel(is_set=True, signum=signal.SIGINT),
            now=_now(),
            poll_interval=_ZERO,
            idle_threshold=timedelta(minutes=10),
        )
    assert excinfo.value.tier is Tier.RUNTIME_CANCELLED
    assert excinfo.value.code is ErrorCode.RUNTIME_CANCELLED_SIGINT
    assert polled == []  # never reached the poll — cancelled at loop top


def test_cancel_during_sleep_raises_before_polling(store: InMemoryStore) -> None:
    # is_set False at loop-top, but the interruptible sleep returns True (event set
    # mid-sleep). Must raise without polling — the mid-sleep branch (§4.2).
    polled = []

    def poll(s: PRGroomingState) -> PRGroomingState:
        polled.append(s)
        return s

    with pytest.raises(PrgroomError) as excinfo:
        wait_pr(
            _state(),
            poll=poll,
            store=store,
            ref=_REF,
            cancel=FakeCancel(is_set=False, wait=True, signum=signal.SIGTERM),
            now=_now(),
            poll_interval=_ZERO,
            idle_threshold=timedelta(minutes=10),
        )
    assert excinfo.value.code is ErrorCode.RUNTIME_CANCELLED_SIGTERM
    assert polled == []


# ── wake event 3: phase moved off awaiting/idle ─────────────────────────────


def test_returns_when_poll_moves_phase_off_waiting(store: InMemoryStore) -> None:
    def poll(s: PRGroomingState) -> PRGroomingState:
        s.phase = PRPhase.FIXES_PENDING  # fix commits arrived
        return s

    out = wait_pr(
        _state(),
        poll=poll,
        store=store,
        ref=_REF,
        cancel=FakeCancel(),
        now=_now(),
        poll_interval=_ZERO,
        idle_threshold=timedelta(minutes=10),
    )
    assert out.phase is PRPhase.FIXES_PENDING
    assert store.read(_REF).phase is PRPhase.FIXES_PENDING  # each poll persisted


# ── wake event 4: quiescence trips ──────────────────────────────────────────


def test_trips_to_quiesced_when_predicate_satisfied(store: InMemoryStore) -> None:
    # An idle, green-CI, reviewer-free, item-free state satisfies every gate; the idle
    # timer is satisfied because now() is an hour past last_activity_at.
    def poll(s: PRGroomingState) -> PRGroomingState:
        return s  # poll observes no change

    out = wait_pr(
        _state(ci_state="success", last_activity_at=_T0),
        poll=poll,
        store=store,
        ref=_REF,
        cancel=FakeCancel(),
        now=_now(_LATER),
        poll_interval=_ZERO,
        idle_threshold=timedelta(minutes=10),
    )
    assert out.phase is PRPhase.QUIESCED
    assert out.quiescence.quiesced_at == _LATER
    assert store.read(_REF).phase is PRPhase.QUIESCED


def test_loops_until_quiescent(store: InMemoryStore) -> None:
    # First poll leaves CI pending (G_CI fails -> not quiescent -> sleep again); second
    # poll flips CI to success -> quiescence trips. Exercises the loop-continue path.
    calls = {"n": 0}

    def poll(s: PRGroomingState) -> PRGroomingState:
        calls["n"] += 1
        s.quiescence = QuiescenceState(ci_state="success" if calls["n"] >= 2 else "pending")
        return s

    out = wait_pr(
        _state(ci_state="pending"),
        poll=poll,
        store=store,
        ref=_REF,
        cancel=FakeCancel(),
        now=_now(_LATER),
        poll_interval=_ZERO,
        idle_threshold=timedelta(minutes=10),
    )
    assert calls["n"] == 2
    assert out.phase is PRPhase.QUIESCED


# ── wake event 2: a poll error propagates (not swallowed) ───────────────────


def test_poll_transient_error_propagates(store: InMemoryStore) -> None:
    def poll(_s: PRGroomingState) -> PRGroomingState:
        raise PrgroomError(tier=Tier.RUNTIME_TRANSIENT, code=ErrorCode.RUNTIME_GH_TRANSIENT)

    with pytest.raises(PrgroomError) as excinfo:
        wait_pr(
            _state(),
            poll=poll,
            store=store,
            ref=_REF,
            cancel=FakeCancel(),
            now=_now(),
            poll_interval=_ZERO,
            idle_threshold=timedelta(minutes=10),
        )
    assert excinfo.value.tier is Tier.RUNTIME_TRANSIENT


# ── cancelled_error mapping + the real token ────────────────────────────────


@pytest.mark.parametrize(
    ("signum", "code"),
    [
        (signal.SIGINT, ErrorCode.RUNTIME_CANCELLED_SIGINT),
        (signal.SIGTERM, ErrorCode.RUNTIME_CANCELLED_SIGTERM),
    ],
)
def test_cancelled_error_maps_signum_to_code(signum: int, code: ErrorCode) -> None:
    err = cancelled_error(signum)
    assert err.tier is Tier.RUNTIME_CANCELLED
    assert err.code is code
    assert err.signum == signum  # exit_code_for_tier -> 128 + signum (130 / 143)


def test_signal_cancel_token_trip_records_signum_and_sets() -> None:
    token = SignalCancelToken()
    assert token.is_set() is False
    assert token.wait(0.0) is False
    token.trip(signal.SIGTERM)
    assert token.is_set() is True
    assert token.signum == signal.SIGTERM
    assert token.wait(0.0) is True
