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
from executor.ports import (
    EVENT_WAS_WRITTEN,
    TRACKER_WRITE_LANDED,
    CommandResult,
    RuntimePort,
    StalenessVerdict,
    TrackerPort,
)
from executor.state import BudgetSpent, ItemView, RunState

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


class FlaggingRuntime(FakeRuntime):
    """A runtime that writes the event and then reports it did not apply.

    The accept-and-flag outcome, modelled faithfully: the append is recorded
    *and* the failure is raised, carrying the marker the real port sets. A fake
    that only raised would let a test pass while the report contradicted the
    event log.
    """

    def append(self, event_type: str, payload: Mapping[str, JsonValue]) -> None:
        self.appended.append((event_type, dict(payload)))
        raise ExecutorError(
            ErrorCode.USAGE,
            f"the runtime recorded {event_type} as an anomaly rather than a transition: scripted",
            {EVENT_WAS_WRITTEN: True},
        )


class FakeTracker:
    """Records every mutation as `(verb, *args)` and counts syncs.

    `fail_on` names verbs whose call raises before writing; `recover()` clears
    them, which is how a retry test models a facade that came back.
    `fail_after_write` names verbs that write and *then* fail -- a wrapper
    dying around a completed call, whose write is durable.
    """

    def __init__(
        self,
        *,
        fail_on: Sequence[str] = (),
        fail_after_write: Sequence[str] = (),
        parked_as: str | None = None,
    ) -> None:
        self.fail_on = set(fail_on)
        self.fail_after_write = set(fail_after_write)
        # What `work park` already has on record. The facade reports the
        # EXISTING stint on a replay and mints nothing, so a fake that always
        # echoed the request back could not model the divergence that costs.
        self.parked_as = parked_as
        self.mutations: list[tuple[str, ...]] = []
        self.syncs = 0
        LIVE_TRACKERS.append(self)

    def _record(self, verb: str, *args: str) -> None:
        if verb in self.fail_on:
            raise ExecutorError(ErrorCode.TRACKER_SUBPROCESS, f"scripted tracker failure on {verb}")
        self.mutations.append((verb, *args))
        if verb in self.fail_after_write:
            # The facade wrote and the process then failed -- the shape a
            # wrapper dying around a completed call leaves behind.
            raise ExecutorError(
                ErrorCode.TRACKER_SUBPROCESS,
                f"scripted post-write failure on {verb}",
                {TRACKER_WRITE_LANDED: True},
            )

    def claim(self, handle: str) -> None:
        self._record("claim", handle)

    def park(self, handle: str, *, reason: str, note: str) -> str:
        self._record("park", handle, reason, note)
        return self.parked_as if self.parked_as is not None else reason

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
    pr_closed: bool = False,
    parked: bool = False,
    park_reason: str | None = None,
    attempts: Mapping[str, int] | None = None,
) -> ItemView:
    """The boring case: a queued, laned, unparked item whose id is its own
    tracker handle. A test overrides only the field it is about.

    `park_reason` implies `parked`: an item carrying a reason is parked, and
    letting a test say otherwise would build a state the fold cannot produce.

    A `pr` is open unless the test says otherwise, mirroring the runtime: a
    reference appears when a PR opens and is marked closed later, so the
    boring case for an item holding one is a live cycle. `pr_closed` without a
    `pr` is not a state the fold produces and leaves the item simply without
    a reference.
    """
    return ItemView(
        id=item_id,
        status=status,
        lane=lane,
        work_id=work_id,
        pr_number=pr,
        parked=parked or park_reason is not None,
        park_reason=park_reason,
        pr_open=pr is not None and not pr_closed,
        attempts=dict(attempts or {}),
    )


# Synthetic timestamps for the builder below. Only their ordering matters:
# the rules read "is this ledger entry still the last thing that touched the
# item", never the wall-clock value.
_LEDGER_TS = "2026-07-26T00:00:00Z"
_LATER_TS = "2026-07-26T00:00:01Z"


def run_state(
    *items: ItemView,
    closures: Sequence[tuple[str, int]] = (),
    merged_shas: Mapping[str, str] | None = None,
    touched_since: Sequence[str] = (),
    spent: Sequence[tuple[str, str, int, int]] = (),
    config: Mapping[str, JsonValue] | None = None,
) -> RunState:
    """A folded run, plus the conditions the runtime reported over it.

    Each recorded closure is treated as the last thing that touched its item,
    which is the ordinary case a retry arrives in. Naming an item in
    `touched_since` models something having happened after -- a start, a
    reopen -- so a test can state that fact without inventing timestamps.

    `spent` is `(item, kind, attempts, budget)` per `attempt_budget_spent`
    condition the runtime reported. It is stated rather than derived on
    purpose: the executor's whole contract here is that the runtime decides
    exhaustion, so a fake that recomputed the condition would test the
    recomputation instead of the honoring.
    """
    last_item_ts = {item_id: _LEDGER_TS for item_id, _ in closures}
    last_item_ts.update({item_id: _LATER_TS for item_id in touched_since})
    return RunState(
        items={view.id: view for view in items},
        closures={(item_id, pr): _LEDGER_TS for item_id, pr in closures},
        merged_shas=dict(merged_shas or {}),
        last_item_ts=last_item_ts,
        budget_spent={
            (item_id, kind): BudgetSpent(item_id, kind, attempts, budget)
            for item_id, kind, attempts, budget in spent
        },
        config=dict(config or {}),
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
