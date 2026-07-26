"""Enacting a `Plan`: ordering, handle routing, and the trailing sync.

Three decisions meet here and nowhere else:

- **S9T1-D6 ordering.** An intent leads with the tracker, a world-fact leads
  with the runtime. The rule does not prevent divergence; it bounds every
  divergence to one failed call whose retry converges, and fixes which side
  leads so two call sites cannot disagree.
- **S9T1-D5 routing.** An item with no tracker handle makes every tracker
  column read "none". That is a success path: the item is reported under
  `unpromoted` and the command otherwise proceeds.
- **S9T1-D9 batching.** One invocation issues at most one `work sync`, after
  the last mutation. Zero mutations issue none, so a refusal never syncs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from executor.envelope import ExecutorError, JsonValue
from executor.pairing import Order, Plan, TrackerVerb
from executor.ports import RuntimePort, TrackerPort
from executor.state import tracker_handle

SYNC_REPAIR = "work sync"


@dataclass
class TrackerSession:
    """Every tracker write in one invocation, plus the single sync that follows.

    A mutation is recorded only once its call returned: a write that raised did
    not land, and counting it would make a later `flush` sync nothing.
    """

    port: TrackerPort
    mutations: list[str] = field(default_factory=list)

    def apply(
        self, verb: TrackerVerb, handle: str, *, reason: str | None = None, note: str | None = None
    ) -> None:
        if verb is TrackerVerb.CLAIM:
            self.port.claim(handle)
        elif verb is TrackerVerb.PARK:
            # A failure-axis reason crosses untranslated -- there is no mapping
            # table anywhere in this package, only the axis test that decided
            # this row belongs to the tracker at all.
            self.port.park(handle, reason=reason or "", note=note or "")
        elif verb is TrackerVerb.REDISPATCH:
            self.port.redispatch(handle)
        elif verb is TrackerVerb.ABANDON:
            self.port.abandon(handle)
        else:
            self.port.close(handle)
        self.mutations.append(f"{verb.value}:{handle}")

    def flush(self) -> bool:
        """One sync when anything was written, none when nothing was."""
        if not self.mutations:
            return False
        self.port.sync()
        return True


def _tracker_step(session: TrackerSession, plan: Plan, handle: str | None) -> None:
    verb = plan.row.tracker
    if verb is None or handle is None:
        return
    session.apply(verb, handle, reason=plan.park_reason, note=plan.park_note)


def _runtime_step(runtime: RuntimePort, plan: Plan) -> None:
    if plan.payload is None:
        return
    runtime.append(plan.row.event, plan.payload)


def _report(
    plan: Plan, handle: str | None, session: TrackerSession, *, synced: bool
) -> dict[str, JsonValue]:
    tracker_verb = plan.row.tracker
    return {
        "verb": plan.row.verb,
        "row": plan.row.key,
        "item": plan.item.id,
        "tracker_id": handle,
        "event": plan.row.event,
        "event_appended": plan.appends,
        "tracker_verb": tracker_verb.value if tracker_verb is not None else None,
        "tracker_called": bool(session.mutations),
        "synced": synced,
        # Always present, empty when the item has a handle: the absence of
        # unpromoted work is a reported fact, not a missing key.
        "unpromoted": [plan.item.id] if handle is None else [],
    }


def enact(plan: Plan, runtime: RuntimePort, tracker: TrackerPort) -> dict[str, JsonValue]:
    handle = tracker_handle(plan.item)
    session = TrackerSession(tracker)

    if plan.row.order is Order.TRACKER_FIRST:
        _tracker_step(session, plan, handle)
        _runtime_step(runtime, plan)
    else:
        _runtime_step(runtime, plan)
        _tracker_step(session, plan, handle)

    try:
        synced = session.flush()
    except ExecutorError as failure:
        # The mutations landed; only the sync did not. Re-running this command
        # would repeat them, so the report names the repair instead.
        raise ExecutorError(
            failure.code,
            f"{failure.message} -- the tracker mutations landed; "
            f"repair by running `{SYNC_REPAIR}`, not by re-running this command",
            {
                **_report(plan, handle, session, synced=False),
                "repair": SYNC_REPAIR,
            },
        ) from failure
    return _report(plan, handle, session, synced=synced)
