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

from executor.envelope import ErrorCode, ExecutorError, JsonValue
from executor.pairing import Order, Plan, TrackerVerb
from executor.ports import (
    EVENT_WAS_WRITTEN,
    INTERNAL_MARKERS,
    TRACKER_WRITE_LANDED,
    RuntimePort,
    TrackerPort,
)
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
        try:
            recorded = self._dispatch(verb, handle, reason, note)
        except ExecutorError as failure:
            if failure.data.get(TRACKER_WRITE_LANDED) is True:
                # The write landed and the process then failed. Recording it
                # is what makes `_with_owed_sync` flush rather than strand it.
                self.mutations.append(f"{verb.value}:{handle}")
            raise
        if verb is TrackerVerb.PARK and recorded != reason:
            # Only the facade's idempotent-replay branch can return a
            # different reason, and that branch mints nothing -- so this
            # refusal owes no sync, and the mutation is deliberately not
            # recorded.
            raise ExecutorError(
                ErrorCode.ITEM_PARKED,
                f"the tracker already has {handle!r} parked as {recorded!r}, "
                f"not {reason!r}; redispatch or abandon it before parking it again",
            )
        self.mutations.append(f"{verb.value}:{handle}")

    def _dispatch(
        self, verb: TrackerVerb, handle: str, reason: str | None, note: str | None
    ) -> str | None:
        if verb is TrackerVerb.CLAIM:
            self.port.claim(handle)
        elif verb is TrackerVerb.PARK:
            # A failure-axis reason crosses untranslated -- there is no mapping
            # table anywhere in this package, only the axis test that decided
            # this row belongs to the tracker at all. The facade's reply is
            # read, not discarded; `apply` compares it.
            return self.port.park(handle, reason=reason or "", note=note or "")
        elif verb is TrackerVerb.REDISPATCH:
            self.port.redispatch(handle)
        elif verb is TrackerVerb.ABANDON:
            self.port.abandon(handle)
        else:
            self.port.close(handle)
        return None

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


def _runtime_step(runtime: RuntimePort, plan: Plan) -> bool:
    """Whether an event was actually appended -- not whether the plan intended
    one. The two differ on the failure path, and the report must say which."""
    if plan.payload is None:
        return False
    runtime.append(plan.row.event, plan.payload)
    return True


def _report(
    plan: Plan, handle: str | None, session: TrackerSession, *, appended: bool, synced: bool
) -> dict[str, JsonValue]:
    tracker_verb = plan.row.tracker
    return {
        # The verb-specific block first, so the enactment's own fields win a
        # name collision -- what the command did is not a row's to restate.
        **(plan.report or {}),
        "verb": plan.row.verb,
        "row": plan.row.key,
        "item": plan.item.id,
        "tracker_id": handle,
        "event": plan.row.event,
        "event_appended": appended,
        "tracker_verb": tracker_verb.value if tracker_verb is not None else None,
        "tracker_called": bool(session.mutations),
        "synced": synced,
        # Always present, empty when the item has a handle: the absence of
        # unpromoted work is a reported fact, not a missing key.
        "unpromoted": [plan.item.id] if handle is None else [],
    }


def _sync_failure(
    plan: Plan,
    handle: str | None,
    session: TrackerSession,
    failure: ExecutorError,
    *,
    appended: bool,
) -> ExecutorError:
    """The mutations landed; only the sync did not. Re-running the command
    would repeat them, so the report names the standalone repair instead."""
    return ExecutorError(
        failure.code,
        f"{failure.message} -- the tracker mutations landed; "
        f"repair by running `{SYNC_REPAIR}`, not by re-running this command",
        {
            **_report(plan, handle, session, appended=appended, synced=False),
            "repair": SYNC_REPAIR,
        },
    )


def _with_owed_sync(
    plan: Plan,
    handle: str | None,
    session: TrackerSession,
    failure: ExecutorError,
    *,
    appended: bool,
) -> ExecutorError:
    """A step failed partway. Any tracker write that already landed still owes
    this invocation its single sync, so it is issued before the failure is
    reported -- otherwise a failed append would strand a landed mutation on the
    local plane until someone happened to retry. A refusal that mutated nothing
    still syncs nothing.

    The step failure stays the reported cause; a sync that fails on top of it
    is additional detail, not a replacement for the reason the command failed.
    """
    # The markers are the port/enact seam's, never the envelope's, so they are
    # stripped on every path out of here -- including the ones that owe no
    # sync, which the tracker-free rows always take.
    detail = {key: value for key, value in failure.data.items() if key not in INTERNAL_MARKERS}
    if not session.mutations:
        if not appended:
            # Neither plane moved: the reason is the whole story.
            return ExecutorError(failure.code, failure.message, detail)
        # A tracker-free row whose event was written and then flagged. Nothing
        # is owed a sync, but the report still has to say the log holds it.
        return ExecutorError(
            failure.code,
            failure.message,
            {**_report(plan, handle, session, appended=True, synced=False), **detail},
        )
    synced = True
    sync_error: str | None = None
    try:
        session.flush()
    except ExecutorError as sync_failure:
        synced = False
        sync_error = sync_failure.message
    data: dict[str, JsonValue] = {
        **_report(plan, handle, session, appended=appended, synced=synced),
        **detail,
    }
    if sync_error is not None:
        data["sync_error"] = sync_error
        data["repair"] = SYNC_REPAIR
    return ExecutorError(failure.code, failure.message, data)


def enact(plan: Plan, runtime: RuntimePort, tracker: TrackerPort) -> dict[str, JsonValue]:
    handle = tracker_handle(plan.item)
    session = TrackerSession(tracker)
    appended = False

    try:
        if plan.row.order is Order.TRACKER_FIRST:
            _tracker_step(session, plan, handle)
            appended = _runtime_step(runtime, plan)
        else:
            appended = _runtime_step(runtime, plan)
            _tracker_step(session, plan, handle)
    except ExecutorError as failure:
        # The runtime writes the event before it reports that the event did not
        # apply, so a failure can still mean "appended". Whether the append
        # happened and whether it transitioned anything are separate facts.
        raise _with_owed_sync(
            plan,
            handle,
            session,
            failure,
            appended=appended or failure.data.get(EVENT_WAS_WRITTEN) is True,
        ) from failure

    # Flushed outside the block above so a sync failure is never mistaken for a
    # step failure and re-flushed.
    try:
        synced = session.flush()
    except ExecutorError as failure:
        raise _sync_failure(plan, handle, session, failure, appended=appended) from failure
    report = _report(plan, handle, session, appended=appended, synced=synced)
    if plan.refusal is not None:
        # A refusal the plan carries through its enactment rather than instead
        # of it (S9T1-C2): the exhaustion row parks the item on both planes and
        # only then refuses the attempt. It is raised here, not at the CLI, so
        # a dispatcher calling `enact` directly cannot enact the park and read
        # the result as a proceed. The full report rides the error because a
        # refusal that mutated has to say what landed and whether it synced.
        raise ExecutorError(plan.refusal.code, plan.refusal.message, report)
    return report
