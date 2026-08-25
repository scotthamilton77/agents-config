"""The harness's own safety property, asserted rather than asserted about.

Every other file here tests grillui. This one tests the thing that makes those
tests honest: that a scenario's seats are scripted and cannot become real ones.
The property has already failed once in this harness's short life -- the
environment was restored while a turn was still able to spawn, and a real
`codex exec` ran and read as a passing scripted seat -- so it is pinned here
rather than left to a docstring.

Both checks fail if their guard is removed, which is the whole point of them.
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING

import harness
import pytest
from conftest import decision, handoff
from harness import GUARDED

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session

PLAN = [decision("d1", "Which storage?")]


@pytest.mark.parametrize("key", GUARDED)
def test_a_scenario_cannot_configure_its_way_out_of_the_guard(
    launcher: Callable[..., Session], key: str
) -> None:
    """
    Given a scenario asking for one of the settings that keep its seats scripted
    When it starts a backend
    Then it is refused by name, rather than being handed an environment where a
         turn can resolve a real binary or reach the network.

    A guard that holds only for callers who did not ask otherwise is not one.
    """
    with pytest.raises(AssertionError, match=f"may not set {key}"):
        launcher(handoff=handoff(PLAN), config={key: "anything at all"})


def test_the_guard_stays_on_while_anything_can_still_spawn_a_seat(
    launcher: Callable[..., Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a backend being closed while a turn worker is still on its feet
    When the session is closed
    Then it fails rather than restoring the environment, and `PATH` still holds
         the shims -- because a worker between "about to spawn its seat" and
         "has spawned it" would otherwise find the machine's own binaries.

    Stopping the server is not stopping the work: a turn outlives both the
    request that scheduled it and the server that answered it.
    """
    session = launcher(handoff=handoff(PLAN))
    guarded = os.environ["PATH"]
    assert str(harness.SHIM_DIR) in guarded, guarded

    # A worker wearing the name the lane gives its turn threads, held open until
    # this test lets it go. Nothing simulates the subprocess: what is under test
    # is whether close() waits for a worker at all.
    monkeypatch.setattr(harness, "TURN_TIMEOUT", 0.3)
    release = threading.Event()
    worker = threading.Thread(target=release.wait, name="turn-map", daemon=True)
    worker.start()
    try:
        with pytest.raises(AssertionError, match="the guard stays on"):
            session.close()
        assert os.environ["PATH"] == guarded, "the guard came off with a worker still running"
    finally:
        release.set()
        worker.join(timeout=5)

    # Once nothing can spawn, the same call restores as it always did.
    session.close()
    assert os.environ["PATH"] != guarded, "the guard never came off"
