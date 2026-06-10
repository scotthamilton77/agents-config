"""Per-verb locking wrappers (§2 transactional model).

Every public verb (except ``status``, the unlocked-read carve-out) is a thin
locking wrapper: acquire ``store.lock(ref)``, delegate to the lock-assuming
``_``-prefixed internal, release on the context manager's ``finally`` even when the
internal raises. :func:`with_lock` is that shape, reused by every verb so the
acquire/delegate/release discipline lives in one place.

``run`` is the singular exception (§3.3): it acquires the lock **once** and threads
several internals in sequence without re-acquiring per step. :func:`run_locked`
captures that — the body it runs may call many ``_``-prefixed internals under the
single held lock.

Lock contention is the **store adapter's** signal: the production ``flock`` adapter
acquires non-blocking and raises ``PreconditionError(PRECONDITION_LOCK_HELD)`` (built
by :func:`prgroom.errors.lock_held_error`, exit 75, scheduler-retryable) when a live
holder owns the lock. These wrappers do not build or catch that error — they enter
``store.lock(ref)`` and let the store's contention error propagate unchanged.

This module is gh/git/clock-free — it only structures lock acquisition around an
opaque callable. Clock and randomness reach the internals via the injected
:class:`~prgroom.deps.Deps`, not through here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeVar

from prgroom.prsession.pr_ref import PRRef

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

T = TypeVar("T")


class _Lockable(Protocol):
    """The narrow slice of :class:`~prgroom.prsession.store.Store` the wrappers need."""

    def lock(self, ref: PRRef) -> AbstractContextManager[None]: ...  # pragma: no cover


def with_lock(store: _Lockable, ref: PRRef, internal: Callable[[], T]) -> T:
    """Acquire the PR lock, run ``internal`` under it, release on ``finally`` (§2).

    The per-verb wrapper shape: a public verb passes its lock-assuming ``_``-prefixed
    internal as ``internal``. Contention on acquire surfaces as the store's
    :class:`~prgroom.errors.PreconditionError` and propagates unchanged.
    """
    with store.lock(ref):
        return internal()


def run_locked(store: _Lockable, ref: PRRef, body: Callable[[], T]) -> T:
    """Acquire the PR lock **once** and run ``body`` (which threads many internals).

    The §3.3 ``run`` exception to the per-verb rule: ``body`` calls the ``_``-prefixed
    internals in sequence under the single held lock, so they never re-acquire.
    Release is guaranteed by the context manager's ``finally``.
    """
    with store.lock(ref):
        return body()
