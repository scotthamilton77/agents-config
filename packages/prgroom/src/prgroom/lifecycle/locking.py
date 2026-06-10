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

Lock contention is the store adapter's signal: the production ``flock`` adapter
detects a live holder and the wrapper lets the resulting
:class:`~prgroom.errors.PreconditionError` propagate (exit 75, scheduler-retryable).
:func:`lock_held_error` builds that error with the ``owner/repo#n (pid <pid>)``
detail the §2 concurrency posture mandates, so adapters and tests share one shape.

This module is gh/git/clock-free — it only structures lock acquisition around an
opaque callable. Clock and randomness reach the internals via the injected
:class:`~prgroom.deps.Deps`, not through here.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol, TypeVar

from prgroom.errors import ErrorCode, PreconditionError
from prgroom.prsession.pr_ref import PRRef

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

T = TypeVar("T")


class _Lockable(Protocol):
    """The narrow slice of :class:`~prgroom.prsession.store.Store` the wrappers need."""

    def lock(self, ref: PRRef) -> AbstractContextManager[None]: ...  # pragma: no cover


def lock_held_error(ref: PRRef, *, pid: int | None = None) -> PreconditionError:
    """Build the ``PRECONDITION_LOCK_HELD`` error naming the ref and holder pid (§2).

    The detail reads ``another invocation holds the lock for <owner>/<repo>#<n> (pid
    <pid>)`` per the §2 concurrency posture. ``pid`` defaults to the current process —
    adapters that read a foreign holder's pid from the lock file pass it explicitly.
    The tier (and thus exit 75) is derived from the code by :class:`PreconditionError`.
    """
    holder = pid if pid is not None else os.getpid()
    return PreconditionError(
        ErrorCode.PRECONDITION_LOCK_HELD,
        detail=f"another invocation holds the lock for {ref.display()} (pid {holder})",
    )


def with_lock(store: _Lockable, ref: PRRef, internal: Callable[[], T]) -> T:
    """Acquire the PR lock, run ``internal`` under it, release on ``finally`` (§2).

    The per-verb wrapper shape: a public verb passes its lock-assuming ``_``-prefixed
    internal as ``internal``. Contention on acquire surfaces as the store's
    :class:`PreconditionError` and propagates unchanged.
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
