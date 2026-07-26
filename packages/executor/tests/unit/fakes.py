"""Port fakes and state builders.

Both ports are faked here, so no test in this suite needs `grind` or `work` on
PATH. The fakes record rather than assert: a test states the one fact it is
about, and `conftest`'s suite-wide guard reads the recording.
"""

from __future__ import annotations

import io
import json
from collections.abc import Mapping, Sequence
from typing import Any

from executor.cli import main
from executor.envelope import ErrorCode, ExecutorError, JsonValue
from executor.ports import CommandResult, RuntimePort, StalenessVerdict, TrackerPort
from executor.state import ItemView, RunState

# Every FakeTracker built during a test, so conftest can inspect the whole
# suite's tracker traffic rather than each test remembering to.
LIVE_TRACKERS: list[FakeTracker] = []


class FakeRuntime:
    """Serves one fixed folded state and records every append.

    `fail_on` names event types whose append raises, modelling a runtime that
    is reachable for reads and failing for writes -- the shape the ordering
    tests need.
    """

    def __init__(self, state: RunState, *, fail_on: Sequence[str] = ()) -> None:
        self._state = state
        self.fail_on = set(fail_on)
        self.appended: list[tuple[str, dict[str, JsonValue]]] = []
        self.state_reads = 0

    def state(self) -> RunState:
        self.state_reads += 1
        return self._state

    def append(self, event_type: str, payload: Mapping[str, JsonValue]) -> None:
        if event_type in self.fail_on:
            raise ExecutorError(
                ErrorCode.RUNTIME_SUBPROCESS, f"scripted runtime failure appending {event_type}"
            )
        self.appended.append((event_type, dict(payload)))

    def staleness(self, max_age: str | None = None) -> StalenessVerdict:  # noqa: ARG002
        return StalenessVerdict(stale=False, age_s=0.0, last_event_ts=None)

    @property
    def event_types(self) -> list[str]:
        return [event_type for event_type, _ in self.appended]


class FakeTracker:
    """Records every mutation as `(verb, *args)` and counts syncs.

    `fail_on` names verbs whose call raises; `recover()` clears them, which is
    how a retry test models a facade that came back.
    """

    def __init__(self, *, fail_on: Sequence[str] = ()) -> None:
        self.fail_on = set(fail_on)
        self.mutations: list[tuple[str, ...]] = []
        self.syncs = 0
        LIVE_TRACKERS.append(self)

    def _record(self, verb: str, *args: str) -> None:
        if verb in self.fail_on:
            raise ExecutorError(ErrorCode.TRACKER_SUBPROCESS, f"scripted tracker failure on {verb}")
        self.mutations.append((verb, *args))

    def claim(self, handle: str) -> None:
        self._record("claim", handle)

    def park(self, handle: str, *, reason: str, note: str) -> None:
        self._record("park", handle, reason, note)

    def redispatch(self, handle: str) -> None:
        self._record("redispatch", handle)

    def abandon(self, handle: str) -> None:
        self._record("abandon", handle)

    def close(self, handle: str) -> None:
        self._record("close", handle)

    def sync(self) -> None:
        if "sync" in self.fail_on:
            raise ExecutorError(ErrorCode.SYNC_FAILED, "scripted sync failure")
        self.syncs += 1

    def recover(self) -> None:
        self.fail_on.clear()

    @property
    def verbs(self) -> list[str]:
        return [mutation[0] for mutation in self.mutations]

    @property
    def handles(self) -> list[str]:
        return [mutation[1] for mutation in self.mutations if len(mutation) > 1]


class ScriptedRunner:
    """Answers a subprocess call by argv prefix.

    An unmatched call raises naming the argv: a benign default would let a test
    pass while the port asks the outside world something the test never
    anticipated.
    """

    def __init__(self, answers: Mapping[tuple[str, ...], CommandResult]) -> None:
        self._answers = dict(answers)
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: Sequence[str]) -> CommandResult:
        call = tuple(argv)
        self.calls.append(call)
        for prefix, result in self._answers.items():
            if call[: len(prefix)] == prefix:
                return result
        raise AssertionError(f"ScriptedRunner has no answer for {list(call)}")


def item(
    item_id: str,
    *,
    status: str = "queued",
    lane: str | None = "lane-a",
    work_id: str | None = None,
    pr: int | None = None,
    parked: bool = False,
) -> ItemView:
    """The boring case: a queued, laned, unparked item whose id is its own
    tracker handle. A test overrides only the field it is about."""
    return ItemView(
        id=item_id, status=status, lane=lane, work_id=work_id, pr_number=pr, parked=parked
    )


def run_state(*items: ItemView, closed_prs: Sequence[tuple[str, int]] = ()) -> RunState:
    return RunState(
        items={view.id: view for view in items},
        closed_prs=frozenset(closed_prs),
    )


def invoke(
    argv: Sequence[str], runtime: RuntimePort, tracker: TrackerPort
) -> tuple[int, dict[str, Any]]:
    """Drive the real CLI with both ports faked, returning the exit code and
    the single decoded envelope. Asserting on the decoded envelope rather than
    on a return value keeps every command test on the actual stdout contract."""
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), out=out, err=err, runtime=runtime, tracker=tracker)
    decoded = json.loads(out.getvalue())
    assert isinstance(decoded, dict)
    return code, decoded
