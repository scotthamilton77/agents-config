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
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import harness
import pytest
from conftest import decision, handoff
from harness import GUARDED
from httpx._utils import get_environment_proxies

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session

PLAN = [decision("d1", "Which storage?")]


# The guarded settings, and two of the open-ended family the allow-list is for:
# a proxy turns a request at a loopback address into one that leaves the machine,
# and a certificate bundle would do as much to what it trusts on the way.
@pytest.mark.parametrize("key", [*GUARDED, "HTTPS_PROXY", "SSL_CERT_FILE"])
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


def test_a_scenario_reaches_no_proxy_however_the_machine_is_configured(
    launcher: Callable[..., Session],
) -> None:
    """
    Given a developer's machine exporting a proxy
    When a scenario runs
    Then its environment bypasses proxies entirely, so a request to the stub's
         loopback address goes to the stub rather than out through the proxy.

    `trust_env` is on by default in httpx, so the transport under test and this
    harness's own reads would both honour one. The ambient environment is not a
    scenario's doing, which is why refusing the setting is not enough by itself.
    """
    launcher(handoff=handoff(PLAN))

    assert os.environ["NO_PROXY"] == "*", os.environ["NO_PROXY"]
    assert not get_environment_proxies(), "a proxy survived into a scenario"


def test_a_startup_that_fails_any_other_way_still_closes_its_session(
    launcher: Callable[..., Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a startup that fails with something other than an assertion
    When the session is opened
    Then the session is closed on the way out and the original failure is what
         surfaces, rather than the backend being left running with nothing
         holding it and no fixture able to close it.

    The check is on `close` having been called rather than on `PATH` having come
    back, because `PATH` comes back either way: the environment is held open by a
    generator, and its `finally` runs when the frame that owned it is collected.
    That is precisely why this must not be left to collection -- it is not a
    cleanup path, and it does not honour the rule about refusing to restore while
    a turn worker could still spawn a seat.
    """
    closed: list[int] = []
    closing = harness.Session.close
    monkeypatch.setattr(harness.Session, "close", lambda self: (closed.append(1), closing(self))[1])
    fell_over = "the backend fell over in some other way"

    def refuse(_url: str, _served: threading.Thread) -> None:
        raise RuntimeError(fell_over)

    monkeypatch.setattr(harness, "_wait_until_serving", refuse)
    monkeypatch.setattr(harness, "TURN_TIMEOUT", 0.3)
    with pytest.raises(RuntimeError, match="some other way"):
        launcher(handoff=handoff(PLAN))

    assert closed, "a failed startup left its session open"


def _entry(seq: int, kind: str, payload: dict[str, str]) -> Any:
    return SimpleNamespace(seq=seq, kind=kind, channel="map", payload=payload)


# The three appends the lane makes under one hold of the append lock: the
# gesture, its `accepted`, and then its `composing`. A reader polling twice
# across the middle of that batch sees the log move with no turn open, twice --
# which is quiet twice over, and a turn about to start.
_SEEN = [_entry(1, "session-start", {}), _entry(2, "answer", {})]
MID_BATCH = [
    _SEEN[:1],
    _SEEN,
    [*_SEEN, _entry(3, "status", {"phase": "accepted"})],
    [
        *_SEEN,
        _entry(3, "status", {"phase": "accepted"}),
        _entry(4, "status", {"phase": "composing"}),
    ],
]


def test_settling_is_not_fooled_by_the_middle_of_one_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given a log read in the middle of the lane's three appends
    When a scenario waits for its gesture to settle
    Then it keeps waiting: what has to repeat is the sequence number, which only
         holds still once the whole batch has landed. Two readings of "the log
         moved and nothing is composing" are two different states, not one state
         seen twice.

    Read off a scripted log rather than a running backend, because the window is
    microseconds wide and a real one would only ever show it by flaking.
    """
    reads = iter(MID_BATCH)
    last = MID_BATCH[-1]

    class Scripted(harness.Session):
        def __init__(self) -> None:
            self._settled_at = 1

        def entries(self) -> Any:
            return next(reads, last)

    monkeypatch.setattr(harness, "TURN_TIMEOUT", 0.5)
    monkeypatch.setattr(harness, "POLL", 0.0)

    with pytest.raises(AssertionError, match="a turn never closed"):
        Scripted().settled()
