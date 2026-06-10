"""Tests for the §2 locking wrappers.

Pins the wrapper contract the public verbs share: acquire ``store.lock(ref)``,
delegate to the lock-assuming internal, release in ``finally`` even when the
internal raises. ``run`` is the carve-out that acquires once and threads several
internals. Contention is exercised against the **real** non-blocking
``InMemoryStore`` (not a fake): the wrappers do not build the contention error —
they let the store's ``PreconditionError(PRECONDITION_LOCK_HELD)`` propagate.
"""

from __future__ import annotations

import pytest

from prgroom.errors import ErrorCode, PreconditionError, exit_code_for_tier
from prgroom.lifecycle.locking import run_locked, with_lock
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.pr_ref import PRRef

_PR = PRRef(owner="octo", repo="demo", number=7)


# -- with_lock structural contract -----------------------------------------


def test_with_lock_runs_internal_inside_the_lock() -> None:
    store = InMemoryStore()
    observed: list[bool] = []

    def internal() -> str:
        # While we run, the lock is held: a non-blocking re-acquire must fail.
        observed.append(store.try_acquire(_PR))
        return "done"

    result = with_lock(store, _PR, internal)

    assert result == "done"
    assert observed == [False]  # the lock was held during the internal


def test_with_lock_releases_after_success() -> None:
    store = InMemoryStore()
    with_lock(store, _PR, lambda: None)
    # Released → a fresh non-blocking acquire succeeds.
    assert store.try_acquire(_PR) is True
    store.release(_PR)


def test_with_lock_releases_even_when_internal_raises() -> None:
    store = InMemoryStore()

    def boom() -> None:
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError, match="kaboom"):
        with_lock(store, _PR, boom)
    # The finally in the wrapper released the lock despite the raise.
    assert store.try_acquire(_PR) is True
    store.release(_PR)


def test_with_lock_propagates_store_contention_error() -> None:
    # The wrapper does not build the error; the real store raises it when a holder
    # already owns the lock, and with_lock lets it propagate unchanged.
    store = InMemoryStore()
    with store.lock(_PR), pytest.raises(PreconditionError) as exc_info:
        with_lock(store, _PR, lambda: "never runs")
    err = exc_info.value
    assert err.code == ErrorCode.PRECONDITION_LOCK_HELD
    assert exit_code_for_tier(err) == 75


# -- run_locked acquires once ----------------------------------------------


def test_run_locked_acquires_once_and_threads_internals_in_order() -> None:
    store = InMemoryStore()
    calls: list[str] = []

    def step(name: str) -> None:
        # Each internal runs while the single outer lock is held.
        assert store.try_acquire(_PR) is False
        calls.append(name)

    run_locked(store, _PR, lambda: (step("a"), step("b"), step("c")))

    assert calls == ["a", "b", "c"]
    assert store.try_acquire(_PR) is True  # released after the sequence
    store.release(_PR)


def test_run_locked_releases_on_internal_raise() -> None:
    store = InMemoryStore()

    def body() -> None:
        raise ValueError("mid-cycle")

    with pytest.raises(ValueError, match="mid-cycle"):
        run_locked(store, _PR, body)
    assert store.try_acquire(_PR) is True
    store.release(_PR)
