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


def _plan_start(item: ItemView) -> Plan:
    applied = item.status == "in-progress"
    return Plan(ROWS["start"], item, None if applied else {"item": item.id})


def _plan_park(args: VerbArgs, item: ItemView) -> Plan:
    if args.reason is None:
        raise ExecutorError(ErrorCode.USAGE, "park requires --reason")
    axis = park_axis(args.reason)
    # The reason code is the default note: `item_parked.note` is required, and
    # a park whose note only repeats its typed reason says exactly as much as
    # the reason does.
    note = args.note if args.note is not None else args.reason
    row = ROWS["park:failure" if axis is Axis.FAILURE else "park:scheduling"]
    payload: dict[str, JsonValue] | None = None
    if not item.parked:
        payload = {"item": item.id, "reason": args.reason, "note": note}
    return Plan(row, item, payload, park_reason=args.reason, park_note=note)


def _plan_redispatch(item: ItemView) -> Plan:
    payload: dict[str, JsonValue] | None = None
    if item.parked:
        payload = {"item": item.id, "lane": _lane(item, "redispatch")}
    return Plan(ROWS["redispatch"], item, payload)


def _plan_abandon(args: VerbArgs, item: ItemView) -> Plan:
    # `--pr` is checked before the idempotency skip: an abandon whose closure
    # names no PR is a malformed command, and answering it with "already done"
    # would hide that.
    pr = _require_pr(args, "abandon")
    payload: dict[str, JsonValue] | None = None
    if item.parked:
        payload = {
            "item": item.id,
            "lane": _lane(item, "abandon"),
            # The single park exit carries the closure, so an abandoned PR is
            # recorded without granting `pr_closed` a new source state.
            "closure": {"pr": pr, "reason": args.reason or "abandoned"},
        }
    return Plan(ROWS["abandon"], item, payload)


def _plan_pr_opened(args: VerbArgs, item: ItemView) -> Plan:
    pr = _require_pr(args, "pr-opened")
    # Both halves matter: the PR reference survives a close, so the number
    # alone would call a genuine reopen of the same PR "already applied".
    applied = item.pr_number == pr and item.status == "pr-open"
    return Plan(ROWS["pr-opened"], item, None if applied else {"item": item.id, "pr": pr})


def _plan_pr_closed(args: VerbArgs, item: ItemView, state: RunState) -> Plan:
    pr = _require_pr(args, "pr-closed")
    if args.next_status is None:
        raise ExecutorError(ErrorCode.USAGE, "pr-closed requires --next")
    if args.reason is None:
        raise ExecutorError(ErrorCode.USAGE, "pr-closed requires --reason")
    # The closed-PR ledger is the only evidence a close already applied: the
    # item keeps its PR reference across one, so the item alone cannot answer.
    applied = (item.id, pr) in state.closed_prs
    payload: dict[str, JsonValue] | None = None
    if not applied:
        payload = {
            "item": item.id,
            "pr": pr,
            "next": args.next_status,
            "reason": args.reason,
        }
    return Plan(ROWS["pr-closed"], item, payload)


def _plan_merged(args: VerbArgs, item: ItemView) -> Plan:
    if args.sha is None:
        raise ExecutorError(ErrorCode.USAGE, "merged requires --sha")
    if item.status in ("merged", "done"):
        # The retry path: the fact is recorded, so only the tracker close and
        # the trailing sync are re-issued. The PR number is not needed and not
        # demanded -- refusing here would strand a converging retry.
        return Plan(ROWS["merged"], item, None)
    if item.pr_number is None:
        raise ExecutorError(
            ErrorCode.NO_OPEN_PR,
            f"item {item.id!r} holds no PR reference to record as merged",
        )
    return Plan(ROWS["merged"], item, {"item": item.id, "pr": item.pr_number, "sha": args.sha})


def _plan_done(item: ItemView) -> Plan:
    applied = item.status == "done"
    return Plan(ROWS["done"], item, None if applied else {"item": item.id})


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
        return _plan_abandon(args, item)
    if verb == "pr-opened":
        return _plan_pr_opened(args, item)
    if verb == "pr-closed":
        return _plan_pr_closed(args, item, state)
    if verb == "merged":
        return _plan_merged(args, item)
    if verb == "done":
        return _plan_done(item)
    raise ExecutorError(ErrorCode.USAGE, f"unknown executor verb {verb!r}")
