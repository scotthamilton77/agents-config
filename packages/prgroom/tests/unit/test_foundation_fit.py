"""Fit-test: the foundation pieces compose (§7.6 fit-test commitment).

Exercises the public surfaces together against the shared conftest fakes — a
deterministic clock, an in-memory Store — to prove the seams line up: a verb-
shaped lock-then-write-then-read cycle stamps state with the injected clock and
survives a round-trip through the Store. This is a behavior test of the wiring,
not of any single module's internals.
"""

from __future__ import annotations

from datetime import datetime

from prgroom.deps import Deps
from prgroom.prsession.enums import PRPhase
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import PRGroomingState, QuiescenceState


def test_locked_write_read_cycle_stamps_injected_clock(
    store: InMemoryStore, pr_ref: PRRef, deps: Deps, fixed_now: datetime
) -> None:
    # A verb-shaped transaction: acquire the per-ref lock, build state stamped
    # with the injected clock, write, release; then read it back.
    with store.lock(pr_ref):
        state = PRGroomingState(
            pr=pr_ref,
            phase=PRPhase.AWAITING_REVIEW,
            round=1,
            last_polled_at=deps.clock.now(),
            last_activity_at=deps.clock.now(),
            quiescence=QuiescenceState(),
        )
        store.write(pr_ref, state)

    read_back = store.read(pr_ref)
    assert read_back.phase == PRPhase.AWAITING_REVIEW
    assert read_back.last_polled_at == fixed_now


def test_store_round_trips_through_json_dict_form(
    store: InMemoryStore, pr_ref: PRRef, fixed_now: datetime
) -> None:
    state = PRGroomingState(
        pr=pr_ref,
        phase=PRPhase.IDLE,
        round=0,
        last_polled_at=fixed_now,
        last_activity_at=fixed_now,
        quiescence=QuiescenceState(),
    )
    store.write(pr_ref, state)
    # The serialized form of what we read is equal to the serialized original —
    # the Store preserves the full state, not just a subset.
    assert store.read(pr_ref).to_dict() == state.to_dict()
