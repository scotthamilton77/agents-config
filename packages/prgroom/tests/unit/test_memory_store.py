"""Tests for InMemoryStore — the test-only Store adapter (§2, §7.6).

These pin the adapter's *behavior* as a Store: read-after-write, the
StateNotFoundError contract on a missing read, lock exclusivity + guaranteed
release, ref enumeration for `sweep`, and delete-as-tombstone. The adapter
structurally satisfies the Store Protocol — that fit is mypy's job, not a test's.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest

from prgroom.prsession.enums import ItemKind, PRPhase
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewItem,
)
from prgroom.prsession.store import StateNotFoundError

_T = datetime(2026, 6, 9, tzinfo=UTC)


def _state(ref: PRRef, phase: PRPhase = PRPhase.IDLE) -> PRGroomingState:
    return PRGroomingState(
        pr=ref,
        phase=phase,
        round=0,
        last_polled_at=_T,
        last_activity_at=_T,
        quiescence=QuiescenceState(),
    )


def test_read_after_write_returns_the_stored_state() -> None:
    store = InMemoryStore()
    ref = PRRef("octo", "demo", 1)
    store.write(ref, _state(ref, PRPhase.FIXES_PENDING))
    assert store.read(ref).phase == PRPhase.FIXES_PENDING


def test_read_missing_raises_state_not_found() -> None:
    store = InMemoryStore()
    with pytest.raises(StateNotFoundError):
        store.read(PRRef("octo", "demo", 999))


def test_write_overwrites_prior_state() -> None:
    store = InMemoryStore()
    ref = PRRef("octo", "demo", 1)
    store.write(ref, _state(ref, PRPhase.IDLE))
    store.write(ref, _state(ref, PRPhase.QUIESCED))
    assert store.read(ref).phase == PRPhase.QUIESCED


def test_read_returns_a_deep_copy_callers_cannot_corrupt_the_store() -> None:
    # Isolation is the substrate every lifecycle test relies on: a caller mutating
    # a returned state must not leak back into storage. Mutating a scalar catches a
    # dropped copy entirely; mutating a nested list catches a downgrade to a shallow
    # copy. Both must leave the stored snapshot untouched.
    store = InMemoryStore()
    ref = PRRef("octo", "demo", 1)
    store.write(ref, _state(ref, PRPhase.IDLE))

    borrowed = store.read(ref)
    borrowed.phase = PRPhase.MERGED
    borrowed.items.append(
        ReviewItem(
            kind=ItemKind.REVIEW_THREAD,
            identity=Identity(gh_id="c1"),
            author="bot",
            body_excerpt="x",
            seen_at=_T,
        )
    )

    fresh = store.read(ref)
    assert fresh.phase == PRPhase.IDLE
    assert fresh.items == []


def test_write_snapshots_so_later_caller_mutation_does_not_leak_in() -> None:
    # The deep-copy on write means a caller holding the object it passed to write()
    # cannot mutate the stored copy after the fact.
    store = InMemoryStore()
    ref = PRRef("octo", "demo", 1)
    original = _state(ref, PRPhase.IDLE)
    store.write(ref, original)
    original.phase = PRPhase.MERGED
    assert store.read(ref).phase == PRPhase.IDLE


def test_lock_releases_on_context_exit_allowing_reacquire() -> None:
    store = InMemoryStore()
    ref = PRRef("octo", "demo", 1)
    with store.lock(ref):
        pass
    # A second acquisition must succeed (the first released on __exit__).
    with store.lock(ref):
        pass


def test_lock_releases_even_when_body_raises() -> None:
    store = InMemoryStore()
    ref = PRRef("octo", "demo", 1)
    with pytest.raises(RuntimeError), store.lock(ref):
        raise RuntimeError("boom")
    # The finally in the context manager must have released the lock.
    with store.lock(ref):
        pass


def test_lock_is_exclusive_per_ref_across_threads() -> None:
    store = InMemoryStore()
    ref = PRRef("octo", "demo", 1)
    entered = threading.Event()
    second_acquired = threading.Event()

    def hold_then_release() -> None:
        with store.lock(ref):
            entered.set()
            # Hold until the main thread has confirmed it could NOT acquire.
            second_acquired.wait(timeout=1.0)

    holder = threading.Thread(target=hold_then_release)
    holder.start()
    assert entered.wait(timeout=1.0)
    # The per-ref lock is held; a non-blocking acquire from here must fail.
    assert store.try_acquire(ref) is False
    second_acquired.set()
    holder.join(timeout=1.0)
    # After the holder releases, acquisition succeeds again.
    assert store.try_acquire(ref) is True
    store.release(ref)


def test_locks_on_distinct_refs_do_not_interfere() -> None:
    store = InMemoryStore()
    ref_a = PRRef("octo", "demo", 1)
    ref_b = PRRef("octo", "demo", 2)
    with store.lock(ref_a), store.lock(ref_b):
        pass  # two distinct refs lock independently


def test_list_refs_enumerates_written_prs() -> None:
    store = InMemoryStore()
    refs = [PRRef("octo", "demo", n) for n in (1, 2, 3)]
    for ref in refs:
        store.write(ref, _state(ref))
    assert sorted(store.list_refs(), key=lambda r: r.number) == refs


def test_list_refs_empty_when_nothing_written() -> None:
    assert InMemoryStore().list_refs() == []


def test_delete_tombstones_state() -> None:
    store = InMemoryStore()
    ref = PRRef("octo", "demo", 1)
    store.write(ref, _state(ref))
    store.delete(ref)
    with pytest.raises(StateNotFoundError):
        store.read(ref)
    assert ref not in store.list_refs()


def test_delete_is_idempotent_on_unknown_ref() -> None:
    # delete tolerates a never-seen ref (tombstone of nothing is a no-op).
    InMemoryStore().delete(PRRef("octo", "demo", 404))
