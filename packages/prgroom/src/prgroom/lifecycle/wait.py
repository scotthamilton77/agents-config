"""``wait_pr`` — the lock-held ``_wait`` blocking poll loop (§4.2).

``_wait`` is the ``wait`` verb's lock-assuming internal: it sleeps ``poll_interval``,
polls, and returns when one of four wake events fires (§4.2 registry):

1. **Signal-cancel** — SIGINT/SIGTERM sets the cancel token; ``_wait`` raises
   ``RUNTIME_CANCELLED`` (exit 128+signum) at the loop top OR mid-sleep, so the
   scheduler does NOT resurrect a cancelled wait (distinct from ``RUNTIME_TRANSIENT``).
2. **Poll error** — an internal poll past its retry budget propagates unchanged.
3. **Phase moved** — the polled phase left ``{awaiting-review, idle}`` (fix commits
   arrived, PR merged externally, …); return so the run-loop re-enters the cycle.
4. **Quiescence trips** — the §4.1 predicate is satisfied; write ``quiesced`` +
   ``quiesced_at`` and return.

The lock is held continuously (no mid-sleep release): the public ``wait`` wrapper's
``lock()`` context manager spans the whole call. The sleep is interruptible — the
cancel token's ``wait`` returns early when a signal arrives — so a Ctrl-C does not
wait out the full ``poll_interval``. Each poll's state is persisted (resumability: a
crash mid-wait leaves the last poll on disk; the next ``run`` resumes from it). There
is no hard wait-timeout in MVP.

The ``poll`` seam is injected (the run-loop binds ``poll_pr`` with its gh/deps/config),
keeping this loop pure to test, and ``now`` is the injected clock reading.
"""

from __future__ import annotations

import dataclasses
import signal
import threading
from typing import TYPE_CHECKING, Protocol

from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.lifecycle.quiescence import quiescence_predicate
from prgroom.prsession.enums import PRPhase

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime, timedelta

    from prgroom.prsession.pr_ref import PRRef
    from prgroom.prsession.state import PRGroomingState
    from prgroom.prsession.store import Store

# Phases that keep _wait blocking; observing any other phase is wake event 3 (§4.2).
_WAITING_PHASES: frozenset[PRPhase] = frozenset({PRPhase.AWAITING_REVIEW, PRPhase.IDLE})


class CancelToken(Protocol):
    """The cancellation seam ``_wait`` honors (§4.2).

    ``signum`` is the captured signal number (2/15) read at error-construction time
    for the exit-code mapping; ``is_set`` is the loop-top check and ``wait`` is the
    interruptible sleep (returns ``True`` if cancelled during the wait).
    """

    signum: int

    def is_set(self) -> bool: ...  # pragma: no cover

    def wait(self, seconds: float) -> bool: ...  # pragma: no cover


class SignalCancelToken:
    """Production cancel token wrapping a :class:`threading.Event`.

    ``trip`` is called from ``run``'s OS signal handler: it records the observed
    ``signum`` BEFORE setting the event, so a thread waking on the event reads the
    correct signal number for the §3.7 exit-code mapping. Structurally satisfies
    :class:`CancelToken`.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self.signum = 0

    def trip(self, signum: int) -> None:
        self.signum = signum
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, seconds: float) -> bool:
        return self._event.wait(timeout=seconds)


def cancelled_error(signum: int) -> PrgroomError:
    """Build the ``RUNTIME_CANCELLED`` error for ``signum`` (SIGINT→130, SIGTERM→143; §3.7).

    SIGINT (2) maps to ``RUNTIME_CANCELLED_SIGINT``; any other signal (SIGTERM=15 in
    practice) maps to ``RUNTIME_CANCELLED_SIGTERM``. ``exit_code_for_tier`` reads
    ``signum`` to produce ``128 + signum``.
    """
    code = (
        ErrorCode.RUNTIME_CANCELLED_SIGINT
        if signum == signal.SIGINT
        else ErrorCode.RUNTIME_CANCELLED_SIGTERM
    )
    return PrgroomError(tier=Tier.RUNTIME_CANCELLED, code=code, signum=signum)


def wait_pr(
    state: PRGroomingState,
    *,
    poll: Callable[[PRGroomingState], PRGroomingState],
    store: Store,
    ref: PRRef,
    cancel: CancelToken,
    now: Callable[[], datetime],
    poll_interval: timedelta,
    idle_threshold: timedelta,
) -> PRGroomingState:
    """Sleep+poll until phase moves, quiescence trips, or a signal cancels (§4.2).

    Caller must hold the per-ref lock (see ``lock()``); the lock is NOT released during
    the sleep. Sleeps first (interruptibly), then polls — the run-loop already polled at
    cycle top, so this avoids hammering gh. Honors the cancel token at the loop top AND
    inside the sleep. Persists each poll. Returns the state to re-enter the cycle (phase
    moved) or to rest at ``quiesced``.
    """
    while True:
        if cancel.is_set():  # wake event 1 — loop-top cancel
            raise cancelled_error(cancel.signum)
        if cancel.wait(poll_interval.total_seconds()):  # interruptible sleep; mid-sleep cancel
            raise cancelled_error(cancel.signum)

        state = poll(state)  # wake event 2 — poll may raise (propagates via the run-loop)
        store.write(ref, state)

        if state.phase not in _WAITING_PHASES:  # wake event 3 — phase moved off waiting
            return state

        current = now()
        if quiescence_predicate(state, now=current, idle_threshold=idle_threshold):  # event 4
            state.phase = PRPhase.QUIESCED
            state.quiescence = dataclasses.replace(state.quiescence, quiesced_at=current)
            store.write(ref, state)
            return state
