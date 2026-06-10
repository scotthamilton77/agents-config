"""InMemoryStore — the test-only Store adapter (§2).

**Test-scoped by convention.** Production code must never import this module;
it exists so unit tests can exercise lifecycle code against a fast, real (not
mocked) Store. It structurally satisfies the :class:`~prgroom.prsession.store.Store`
Protocol. Visibility is enforced by discipline, not a compile-time gate (Python
has no build tags) — the file adapter is the production default.

State is held in an in-process ``dict`` keyed by :class:`PRRef`; ``lock`` is a
per-ref :class:`threading.Lock`. State is deep-copied on the way in and out so a
caller mutating a returned object cannot corrupt the store (mirrors the
file adapter's snapshot-on-read semantics).
"""

from __future__ import annotations

import copy
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from prgroom.errors import lock_held_error
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import PRGroomingState
from prgroom.prsession.store import StateNotFoundError


class InMemoryStore:
    """Reference test adapter. Structurally satisfies ``Store``."""

    def __init__(self) -> None:
        self._states: dict[PRRef, PRGroomingState] = {}
        self._locks: dict[PRRef, threading.Lock] = {}
        # Guards lazy creation of per-ref locks.
        self._registry_lock = threading.Lock()

    def _lock_for(self, ref: PRRef) -> threading.Lock:
        with self._registry_lock:
            lock = self._locks.get(ref)
            if lock is None:
                lock = threading.Lock()
                self._locks[ref] = lock
            return lock

    # -- Store protocol --

    def read(self, ref: PRRef) -> PRGroomingState:
        try:
            return copy.deepcopy(self._states[ref])
        except KeyError as exc:
            raise StateNotFoundError(ref.display()) from exc

    def write(self, ref: PRRef, state: PRGroomingState) -> None:
        self._states[ref] = copy.deepcopy(state)

    @contextmanager
    def lock(self, ref: PRRef) -> Iterator[None]:
        """Acquire the per-ref lock non-blocking; raise on a live holder (§2).

        ``acquire(blocking=False)`` returning ``False`` means another holder owns the
        lock, so this raises ``PreconditionError(PRECONDITION_LOCK_HELD)`` (exit 75)
        instead of blocking — mirroring the file adapter's contention contract. In-
        memory contention is same-process, so the holder pid is this process.
        """
        lock = self._lock_for(ref)
        if not lock.acquire(blocking=False):
            raise lock_held_error(ref, pid=os.getpid())
        try:
            yield
        finally:
            lock.release()

    def list_refs(self) -> list[PRRef]:
        return list(self._states)

    def delete(self, ref: PRRef) -> None:
        self._states.pop(ref, None)

    # -- test helpers (non-Protocol; exercised by the lock-exclusivity test) --

    def try_acquire(self, ref: PRRef) -> bool:
        """Non-blocking acquire of the per-ref lock. Returns whether it succeeded."""
        return self._lock_for(ref).acquire(blocking=False)

    def release(self, ref: PRRef) -> None:
        """Release a lock acquired via :meth:`try_acquire`."""
        self._lock_for(ref).release()
