"""The S9T1-D12 pairing table and the plan one executor verb produces.

The table is the executor's whole *mutation* universe: which grind event a verb
appends, which tracker verb it enacts (or the explicit none), and which side
leads. Port reads appear in no row and are unrestricted -- reading the fold to
find an item's lane or PR is not a mutation.

This module is pure. It reads a `RunState` and produces a `Plan`; it never
touches a port, which is what makes every row's pairing assertable without
faking anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from executor.envelope import ErrorCode, ExecutorError, JsonValue
from executor.state import ItemView, RunState

# The park vocabulary, both axes.
#
# The failure axis is THE shared contract in `packages/contracts/
# park-reasons.toml`; this package is its third reader, after the runtime and
# the facade. A failure reason crosses to `work park --reason` byte-identical,
# so there is deliberately no mapping table here -- only membership.
FAILURE_REASONS: tuple[str, ...] = (
    "ci-failure",
    "merge-conflict",
    "approval-required",
    "bot-declined",
    "budget-exhausted",
)
# The scheduling axis is runtime-native: sequencing decisions about work that
# never had a PR to fail. The facade carries no vocabulary for it, which is why
# these rows issue zero tracker writes rather than a translated one.
SCHEDULING_REASONS: tuple[str, ...] = ("discovered-work", "later-wave", "deferred")


class Axis(StrEnum):
    FAILURE = "failure"
    SCHEDULING = "scheduling"


class Order(StrEnum):
    """Which side leads (S9T1-D6).

    An intent the executor is about to enact goes tracker-first: a tracker
    failure then leaves the runtime un-advanced and the command retryable. A
    fact about the outside world that already happened goes runtime-first: the
    fact stays recorded even when the tracker call fails.
    """

    TRACKER_FIRST = "tracker-first"
    RUNTIME_FIRST = "runtime-first"


class TrackerVerb(StrEnum):
    CLAIM = "claim"
    PARK = "park"
    REDISPATCH = "redispatch"
    ABANDON = "abandon"
    CLOSE = "close"


@dataclass(frozen=True)
class PairingRow:
    """One S9T1-D12 row. `tracker is None` is the table's explicit "none", not
    a missing entry: two rows (`park` on the scheduling axis, and every
    world-fact row but `merged`) deliberately issue no tracker write."""

    key: str
    verb: str
    event: str
    tracker: TrackerVerb | None
    order: Order


PAIRING_TABLE: tuple[PairingRow, ...] = (
    PairingRow("start", "start", "item_started", TrackerVerb.CLAIM, Order.TRACKER_FIRST),
    PairingRow("park:failure", "park", "item_parked", TrackerVerb.PARK, Order.TRACKER_FIRST),
    PairingRow("park:scheduling", "park", "item_parked", None, Order.TRACKER_FIRST),
    PairingRow(
        "redispatch",
        "redispatch",
        "item_enqueued",
        TrackerVerb.REDISPATCH,
        Order.TRACKER_FIRST,
    ),
    PairingRow("abandon", "abandon", "item_enqueued", TrackerVerb.ABANDON, Order.TRACKER_FIRST),
    PairingRow("pr-opened", "pr-opened", "pr_opened", None, Order.RUNTIME_FIRST),
    PairingRow("pr-closed", "pr-closed", "pr_closed", None, Order.RUNTIME_FIRST),
    PairingRow("merged", "merged", "item_merged", TrackerVerb.CLOSE, Order.RUNTIME_FIRST),
    PairingRow("done", "done", "item_done", None, Order.RUNTIME_FIRST),
)

ROWS: dict[str, PairingRow] = {row.key: row for row in PAIRING_TABLE}

# The closed executor CLI surface: the S9T1-D12 verbs plus `next` (S9T1-D10).
# A verb outside this tuple is not part of the contract.
EXECUTOR_VERBS: tuple[str, ...] = (
    "start",
    "park",
    "redispatch",
    "abandon",
    "pr-opened",
    "pr-closed",
    "merged",
    "done",
    "attempt",
    "next",
)

# Verbs inside the closed universe that this slice does not wire: `attempt` is
# the budget-enforcement decision surface and `next` the open-new-work one.
# Each lands by deleting its name from here and adding its rows/parser, so the
# totality test measures the gap instead of ignoring it.
PENDING_VERBS: frozenset[str] = frozenset({"attempt", "next"})

# The table closes the executor's *mutation* surface, so a verb that only
# reads has no row in it and must not be looked for there. `next` composes two
# facade reads and writes nothing.
READ_ONLY_VERBS: frozenset[str] = frozenset({"next"})

WIRED_VERBS: tuple[str, ...] = tuple(v for v in EXECUTOR_VERBS if v not in PENDING_VERBS)


def park_axis(reason: str) -> Axis:
    """The axis a park reason sits on. An unrecognized reason is a refusal, not
    a default: guessing an axis would either invent a tracker write or swallow
    one that was owed."""
    if reason in FAILURE_REASONS:
        return Axis.FAILURE
    if reason in SCHEDULING_REASONS:
        return Axis.SCHEDULING
    legal = "|".join((*FAILURE_REASONS, *SCHEDULING_REASONS))
    raise ExecutorError(ErrorCode.USAGE, f"unknown park reason {reason!r}; expected one of {legal}")


@dataclass(frozen=True)
class VerbArgs:
    """The union of the S9T1-D12 rows' arguments. Which ones are required is
    the row's business, enforced in `build_plan`, so the CLI parser stays a
    transcription of the table's argument list."""

    item: str
    reason: str | None = None
    note: str | None = None
    pr: int | None = None
    sha: str | None = None
    next_status: str | None = None


@dataclass(frozen=True)
class Plan:
    """What one executor verb will do: at most one runtime append, at most one
    tracker write.

    `payload is None` is the state-checked idempotent skip (S9T1-D6): the
    runtime already records this transition, so re-running appends no duplicate
    and still reports success. The tracker side is re-issued regardless -- the
    facade verbs are idempotent, and a response-lost retry has to be able to
    converge the side that did not land.
    """

    row: PairingRow
    item: ItemView
    payload: dict[str, JsonValue] | None
    park_reason: str | None = None
    park_note: str | None = None

    @property
    def appends(self) -> bool:
        return self.payload is not None


def _require_pr(args: VerbArgs, verb: str) -> int:
    if args.pr is None:
        raise ExecutorError(ErrorCode.USAGE, f"{verb} requires --pr")
    return args.pr


def _lane(item: ItemView, verb: str) -> str:
    """`item_enqueued` names the lane the item re-enters. Discovered work parked
    before it was ever laned has none, and this slice mints no lane of its own:
    an item with nowhere to return to is a refusal a human resolves."""
    if item.lane is None:
        raise ExecutorError(
            ErrorCode.USAGE,
            f"{verb} needs the item's lane, and {item.id!r} is not on one",
        )
    return item.lane


# The fold's source-status preconditions, mirrored per row.
#
# The executor is the runtime's single writer, so an event it can prove illegal
# is a caller's mistake, not something that happened: refusing keeps the log a
# record of transitions instead of a record of the executor's errors. For the
# tracker-first rows it is also correctness — they write to the tracker before
# appending, so an append the fold would flag leaves the two planes disagreeing
# with no retry that converges.
#
# Duplicating the fold's tables is the cost. `GrindRuntime.append` refusing an
# `applied: false` reply is the backstop that catches this table drifting from
# the runtime's, and it names the fold's own reason when it fires.
_STARTABLE = frozenset({"queued"})
_PARKABLE = frozenset({"queued", "in-progress", "pr-open", "in-review", "waiting-human", "blocked"})
_PR_OPENABLE = frozenset({"in-progress", "waiting-human"})
# `pr_closed` and `item_merged` share a source set: both end a live PR.
_REVIEWABLE = frozenset({"pr-open", "in-review", "waiting-human"})
_DONEABLE = frozenset({"merged"})


def _require_status(item: ItemView, legal: frozenset[str], verb: str) -> None:
    if item.status not in legal:
        raise ExecutorError(
            ErrorCode.USAGE,
            f"{verb} is not legal from status {item.status!r}; "
            f"the runtime accepts it from {'|'.join(sorted(legal))}",
        )


def _require_unparked(item: ItemView, verb: str) -> None:
    """Parked is not a status -- it is a flag the fold carries alongside one.

    A parked item keeps whatever status it held, so a status check alone waves
    a parked item straight through. The fold treats a parked item as absent for
    every handler but `item_enqueued`, so this is a precondition of every other
    row in its own right.
    """
    if item.parked:
        raise ExecutorError(
            ErrorCode.ITEM_PARKED,
            f"{verb} is not legal on parked item {item.id!r}; "
            f"the parking lot's only exit is a redispatch or an abandon",
        )


def _require_appendable(item: ItemView, legal: frozenset[str], verb: str) -> None:
    _require_unparked(item, verb)
    _require_status(item, legal, verb)


def _plan_start(item: ItemView) -> Plan:
    if item.status == "in-progress" and not item.parked:
        return Plan(ROWS["start"], item, None)
    _require_appendable(item, _STARTABLE, "start")
    return Plan(ROWS["start"], item, {"item": item.id})


def _plan_park(args: VerbArgs, item: ItemView) -> Plan:
    if args.reason is None:
        raise ExecutorError(ErrorCode.USAGE, "park requires --reason")
    axis = park_axis(args.reason)
    # A failure reason is a statement that this item's PR did not merge, so the
    # runtime's fold refuses one on an item holding no PR -- keyed on the PR
    # reference, not on status. Mirroring that refusal here is what keeps the
    # two planes convergent: without it the tracker park lands, the runtime
    # records the append as an anomaly and leaves the item unparked, and every
    # retry repeats the same one-sided result.
    if axis is Axis.FAILURE and item.pr_number is None:
        raise ExecutorError(
            ErrorCode.NO_OPEN_PR,
            f"failure-axis reason {args.reason!r} says item {item.id!r}'s PR did not merge, "
            f"and it holds no PR reference",
        )
    # The reason code is the default note: `item_parked.note` is required, and
    # a park whose note only repeats its typed reason says exactly as much as
    # the reason does.
    note = args.note if args.note is not None else args.reason
    row = ROWS["park:failure" if axis is Axis.FAILURE else "park:scheduling"]
    if item.parked:
        # An already-parked item is a retry only when it is parked for the same
        # reason. There is no re-park transition -- the parking lot's one exit
        # is an enqueue -- so a park naming a different reason cannot be
        # enacted on either plane: the append would flag, and the facade's park
        # is a no-op that keeps the reason it already has. Reporting success
        # for it would claim a transition neither plane made.
        #
        # The reason is compared and the note is not: the reason is the typed
        # fact both planes record, while the note is free text a retry may
        # legitimately word differently.
        if item.park_reason != args.reason:
            raise ExecutorError(
                ErrorCode.ITEM_PARKED,
                f"item {item.id!r} is already parked as {item.park_reason or 'untyped'!r}; "
                f"re-parking as {args.reason!r} is not a transition the runtime has -- "
                f"redispatch or abandon it first",
            )
        return Plan(row, item, None, park_reason=args.reason, park_note=note)
    # A terminal item is not parkable: finished work has nothing left to park.
    # Reachable through a legitimately one-sided state — a merge whose tracker
    # close failed leaves the runtime terminal while the tracker item is still
    # open — so the check has to sit here, ahead of the tracker write.
    _require_status(item, _PARKABLE, "park")
    payload: dict[str, JsonValue] = {"item": item.id, "reason": args.reason, "note": note}
    return Plan(row, item, payload, park_reason=args.reason, park_note=note)


def _plan_redispatch(item: ItemView) -> Plan:
    payload: dict[str, JsonValue] | None = None
    if item.parked:
        payload = {"item": item.id, "lane": _lane(item, "redispatch")}
    return Plan(ROWS["redispatch"], item, payload)


def _require_matching_pr(item: ItemView, pr: int) -> None:
    """The PR named must be the one the item is on, whenever the item still
    says which that is.

    The fold compares an event's PR against nothing, so a typo or a delayed
    notification for a superseded PR is taken as fact -- and for `pr-closed` it
    also tears down the live review cycle. The item's reference is the only
    thing that says which cycle a closure belongs to, and it is worth
    consulting on the retry path too: skipping the append does not make
    "success" true of a PR the item was never on.

    Absence is the one reading that is not a mismatch. The closure an abandon
    records clears the item's reference, so a retry arriving after that has
    nothing left to compare and must not be refused for it.
    """
    if item.pr_number is not None and item.pr_number != pr:
        raise ExecutorError(
            ErrorCode.USAGE,
            f"item {item.id!r} is on PR {item.pr_number}, not {pr}; "
            f"recording a closure for a PR the item is not on would name the wrong cycle",
        )


def _require_current_pr(item: ItemView, pr: int, verb: str) -> None:
    """As above, and the reference has to be there: a path that writes a
    closure needs a PR to name."""
    if item.pr_number is None:
        raise ExecutorError(
            ErrorCode.NO_OPEN_PR,
            f"{verb} records a PR's closure, and item {item.id!r} holds no PR reference",
        )
    _require_matching_pr(item, pr)


def _abandon_applied(item: ItemView, state: RunState, pr: int) -> bool:
    """Whether this abandon's own postcondition is on record.

    The two halves that identify it are a *cleared* PR reference and a closure
    for that PR. Only an abandon produces both: S9T1-B7 has the fold clear the
    reference when it interprets the closure an `item_enqueued` carries, while
    an ordinary `pr_closed` records its closure and leaves the reference in
    place. Nothing else clears a reference at all.

    Until B7 lands this is unreachable -- today's fold records the closure
    payload without interpreting it, so the reference survives an abandon and
    the item falls through to the refusal below. That is the interim gap
    S9T1-A7 asks about, and it closes on B7 with no change here.

    Every weaker proxy was tried in review and each matched a state some other
    command produced: being out of the parking lot (also true of an item never
    in it), the surviving PR reference, and ledger membership alone (an
    ordinary `pr-closed --next queued` leaves exactly that). Accepting one of
    those claims a closure that exists nowhere *and* issues a tracker write
    for a transition that never happened.
    """
    return item.pr_number is None and (item.id, pr) in state.closures


def _plan_abandon(args: VerbArgs, item: ItemView, state: RunState) -> Plan:
    pr = _require_pr(args, "abandon")
    if not item.parked:
        if _abandon_applied(item, state, pr):
            # The retry path: the enqueue is recorded, so only the facade call
            # is re-issued.
            return Plan(ROWS["abandon"], item, None)
        # Refusing costs little. The row is tracker-first, so a failed append
        # leaves the item parked and the ordinary appending path handles that
        # retry; the case reaching here has both sides landed and the response
        # lost, where nothing needs converging and this names the true state.
        raise ExecutorError(
            ErrorCode.USAGE,
            f"item {item.id!r} is not parked and records no abandoned PR {pr}; "
            f"there is nothing to abandon",
        )
    # The appending path writes the closure into the log, where it is the
    # record, so the PR it names has to be the item's own.
    _require_current_pr(item, pr, "abandon")
    payload: dict[str, JsonValue] = {
        "item": item.id,
        "lane": _lane(item, "abandon"),
        # The single park exit carries the closure, so an abandoned PR is
        # recorded without granting `pr_closed` a new source state.
        "closure": {"pr": pr, "reason": args.reason or "abandoned"},
    }
    return Plan(ROWS["abandon"], item, payload)


# Where a closure leaves an item: `pr_closed` sets `in-progress` or `queued`,
# or parks it. An item holding a PR reference while sitting in one of these has
# had that PR closed and not reopened since.
_POST_CLOSURE = frozenset({"in-progress", "queued"})


def _closed_out(item: ItemView) -> bool:
    return item.parked or item.status in _POST_CLOSURE


def _plan_pr_opened(args: VerbArgs, item: ItemView) -> Plan:
    pr = _require_pr(args, "pr-opened")
    # "This PR's opening is already recorded" is not "the item is still sitting
    # at pr-open". An opened PR outlives that status -- review, a human wait, a
    # blocker, a merge -- and re-appending from any of them is wrong in a
    # different way each time: from `waiting-human` the fold ACCEPTS it and
    # silently drags the item back to `pr-open`, discarding a wait that only
    # `item_resumed` should end; from `in-review` it flags.
    #
    # The closed-PR ledger cannot answer this. It is a set of closures with no
    # counterpart for openings, so a PR closed once and reopened looks the same
    # as one still closed, forever. The item's own position does answer it: a
    # closure puts the item somewhere a live PR never leaves it, so the
    # evidence is this PR reference plus the item not sitting post-closure.
    #
    # Residual, and deliberately chosen: an item closed to `in-progress` that
    # then goes `waiting-human` sits in a status reachable both ways, and a
    # genuine reopen there is read as a retry and not recorded. The runtime's
    # snapshot carries nothing that separates the two, so this is a limit of
    # the substrate rather than a rule that could be written more sharply. The
    # direction is picked for its failure mode: a skipped append is visible in
    # the envelope as `event_appended: false` and is recoverable, where the
    # other direction silently ends a human wait.
    applied = item.pr_number == pr and not _closed_out(item)
    if applied:
        return Plan(ROWS["pr-opened"], item, None)
    _require_appendable(item, _PR_OPENABLE, "pr-opened")
    return Plan(ROWS["pr-opened"], item, {"item": item.id, "pr": pr})


def _park_typing(reason: str) -> str | None:
    """How the runtime types the park a closure produces.

    `pr_closed.reason` is free text that shares a field name with the park
    vocabulary and not its contract: on the `parked` path the runtime runs it
    through the same lookup, typing the park when the text names a member and
    leaving it untyped otherwise. Mirrored so a retry can be compared against
    the park it would produce.
    """
    return reason if reason in FAILURE_REASONS or reason in SCHEDULING_REASONS else None


def _closure_applied(
    item: ItemView, state: RunState, *, pr: int, next_status: str, reason: str
) -> bool:
    """Whether this exact closure is already recorded.

    Two facts, each covering the other's blind spot. The ledger alone
    deduplicates every closure of a PR number forever, so a PR closed,
    reopened and closed again would never record its second closure. The
    item's position alone cannot tell "already closed" from "resumed out of a
    human wait with the PR still open", which lands where a closure leaves an
    item having closed nothing.

    And the outcome has to match, not just the fact of a closure: a retry
    naming a different `--next` is asking for something that never happened,
    so reporting success for it would claim a transition the runtime never
    made. A closure to `parked` is the awkward one -- the runtime leaves the
    item's review status alone and sets the park instead, so the park it
    produced is what the retry is compared against.

    The ledger records no outcome, which is why the item's position stands in
    for one -- and a position only speaks for this closure while the closure is
    still the last thing that touched the item. Without that guard an unrelated
    later transition can leave the item on a status a retry happens to name:
    close to `queued`, start the item, then ask to close again to
    `in-progress`, and the request matches a state the closure never produced.

    The runtime's timestamps are second-granular, so an intervening event in
    the same second still defeats the guard -- measured, not assumed. What is
    left is benign: this row writes nothing and calls no tracker verb, so a
    wrongly-idempotent answer produces no append, no tracker call and no
    divergence, and the outcome it reports is the one the item is actually in.
    Closing it exactly needs the ledger to record each closure's `next`, which
    is the runtime's to add.
    """
    closure_ts = state.closures.get((item.id, pr))
    if closure_ts is None or state.last_item_ts.get(item.id) != closure_ts:
        return False
    if next_status == "parked":
        return item.parked and item.park_reason == _park_typing(reason)
    return not item.parked and item.status == next_status


def _plan_pr_closed(args: VerbArgs, item: ItemView, state: RunState) -> Plan:
    pr = _require_pr(args, "pr-closed")
    if args.next_status is None:
        raise ExecutorError(ErrorCode.USAGE, "pr-closed requires --next")
    if args.reason is None:
        raise ExecutorError(ErrorCode.USAGE, "pr-closed requires --reason")
    if _closure_applied(item, state, pr=pr, next_status=args.next_status, reason=args.reason):
        return Plan(ROWS["pr-closed"], item, None)
    _require_current_pr(item, pr, "pr-closed")
    _require_appendable(item, _REVIEWABLE, "pr-closed")
    payload: dict[str, JsonValue] = {
        "item": item.id,
        "pr": pr,
        "next": args.next_status,
        "reason": args.reason,
    }
    return Plan(ROWS["pr-closed"], item, payload)


def _plan_merged(args: VerbArgs, item: ItemView, state: RunState) -> Plan:
    if args.sha is None:
        raise ExecutorError(ErrorCode.USAGE, "merged requires --sha")
    if item.status in ("merged", "done"):
        # The retry path: the fact is recorded, so only the tracker close and
        # the trailing sync are re-issued. The PR number is not needed and not
        # demanded -- refusing here would strand a converging retry.
        #
        # The commit is checked, though, when the ledger recorded one: "already
        # merged" is not the same claim as "already merged at this commit", and
        # answering a different commit with success reports a fact no event
        # holds. A ledger entry with no commit cannot answer, and an
        # unanswerable check must not strand the retry, so it does not refuse.
        recorded = state.merged_shas.get(item.id)
        if recorded is not None and recorded != args.sha:
            raise ExecutorError(
                ErrorCode.USAGE,
                f"item {item.id!r} is recorded as merged at {recorded!r}, not {args.sha!r}",
            )
        return Plan(ROWS["merged"], item, None)
    if item.pr_number is None:
        raise ExecutorError(
            ErrorCode.NO_OPEN_PR,
            f"item {item.id!r} holds no PR reference to record as merged",
        )
    _require_appendable(item, _REVIEWABLE, "merged")
    return Plan(ROWS["merged"], item, {"item": item.id, "pr": item.pr_number, "sha": args.sha})


def _plan_done(item: ItemView) -> Plan:
    if item.status == "done" and not item.parked:
        return Plan(ROWS["done"], item, None)
    _require_appendable(item, _DONEABLE, "done")
    return Plan(ROWS["done"], item, {"item": item.id})


def build_plan(verb: str, args: VerbArgs, state: RunState) -> Plan:
    """Resolve one executor verb against the folded state into a `Plan`.

    Refusals are raised, never returned as a degenerate plan: a caller that
    forgot to check a `Plan.refused` flag would enact half a row.
    """
    item = state.item(args.item)
    if verb == "start":
        return _plan_start(item)
    if verb == "park":
        return _plan_park(args, item)
    if verb == "redispatch":
        return _plan_redispatch(item)
    if verb == "abandon":
        return _plan_abandon(args, item, state)
    if verb == "pr-opened":
        return _plan_pr_opened(args, item)
    if verb == "pr-closed":
        return _plan_pr_closed(args, item, state)
    if verb == "merged":
        return _plan_merged(args, item, state)
    if verb == "done":
        return _plan_done(item)
    raise ExecutorError(ErrorCode.USAGE, f"unknown executor verb {verb!r}")
