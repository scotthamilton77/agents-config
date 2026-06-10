"""Tests for the §2 locking wrappers.

Pins the wrapper contract the public verbs share: acquire ``store.lock(ref)``,
delegate to the lock-assuming internal, release in ``finally`` even when the
internal raises. ``run`` is the carve-out that acquires once and threads several
internals. Lock contention surfaces as ``PreconditionError(PRECONDITION_LOCK_HELD)``
(exit 75) naming ``owner/repo#n`` + the holder pid — modeled here with a fake store
whose ``lock`` raises that error on entry.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from prgroom.errors import ErrorCode, PreconditionError, Tier, exit_code_for_tier
from prgroom.lifecycle.locking import lock_held_error, run_locked, with_lock
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.pr_ref import PRRef

_PR = PRRef(owner="octo", repo="demo", number=7)


class _ContendedStore:
    """A Store-shaped fake whose ``lock`` always reports contention on entry."""

    def __init__(self, ref: PRRef, *, pid: int = 4321) -> None:
        self._ref = ref
        self._pid = pid

    @contextmanager
    def lock(self, ref: PRRef) -> Iterator[None]:
        raise lock_held_error(ref, pid=self._pid)
        yield  # pragma: no cover - unreachable; documents the contextmanager shape


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


def test_with_lock_propagates_contention_error() -> None:
    store = _ContendedStore(_PR)
    with pytest.raises(PreconditionError) as exc_info:
        with_lock(store, _PR, lambda: "never runs")
    assert exc_info.value.code == ErrorCode.PRECONDITION_LOCK_HELD


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


# -- lock_held_error shape -------------------------------------------------


def test_lock_held_error_names_ref_and_pid_and_maps_to_exit_75() -> None:
    err = lock_held_error(_PR, pid=9999)
    assert err.code == ErrorCode.PRECONDITION_LOCK_HELD
    assert err.tier == Tier.PRECONDITION_LOCK_HELD
    assert exit_code_for_tier(err) == 75
    assert _PR.display() in err.detail
    assert "9999" in err.detail


def test_lock_held_error_defaults_pid_to_current_process() -> None:
    err = lock_held_error(_PR)
    assert str(os.getpid()) in err.detail
