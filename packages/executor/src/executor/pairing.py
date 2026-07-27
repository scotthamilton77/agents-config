"""The S9T1-D12 pairing table and the plan one executor verb produces.

The table is the executor's whole *mutation* universe: which grind event a verb
appends, which tracker verb it enacts (or the explicit none), and which side
leads. Port reads appear in no row and are unrestricted -- reading the fold to
find an item's lane or PR is not a mutation.

What D12 does *not* say -- which item states a row may fire from, and which
arguments make a re-invocation the same command -- lives next door in
`rules.py` as two enumerated matrices. Every builder here is the same four
steps against them: resolve the arguments, pick the row, ask whether the exact
command is already recorded, and otherwise check the row's preconditions before
building a payload. Guards belong in that table, never inline here.

This module is pure. It reads a `RunState` and produces a `Plan`; it never
touches a port, which is what makes every row's pairing assertable without
faking anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from executor.envelope import ErrorCode, ExecutorError, JsonValue
from executor.rules import (
    ATTEMPT_KINDS,
    BUDGET_EXHAUSTED,
    FAILURE_REASONS,
    ROW_RULES,
    SCHEDULING_REASONS,
    Request,
    RowRules,
    already_recorded,
    apply_payload_rules,
    attempt_budget,
    attempt_kind,
    check_preconditions,
)
from executor.state import BudgetSpent, ItemView, RunState

__all__ = [
    "ATTEMPT_KINDS",
    "BUDGET_EXHAUSTED",
    "EXECUTOR_VERBS",
    "FAILURE_REASONS",
    "PAIRING_TABLE",
    "PENDING_VERBS",
    "READ_ONLY_VERBS",
    "ROWS",
    "SCHEDULING_REASONS",
    "WIRED_VERBS",
    "Axis",
    "Order",
    "PairingRow",
    "Plan",
    "TrackerVerb",
    "VerbArgs",
    "build_plan",
    "park_axis",
]


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
        "redispatch", "redispatch", "item_enqueued", TrackerVerb.REDISPATCH, Order.TRACKER_FIRST
    ),
    PairingRow("abandon", "abandon", "item_enqueued", TrackerVerb.ABANDON, Order.TRACKER_FIRST),
    PairingRow("pr-opened", "pr-opened", "pr_opened", None, Order.RUNTIME_FIRST),
    PairingRow("pr-closed", "pr-closed", "pr_closed", None, Order.RUNTIME_FIRST),
    PairingRow("merged", "merged", "item_merged", TrackerVerb.CLOSE, Order.RUNTIME_FIRST),
    PairingRow("done", "done", "item_done", None, Order.RUNTIME_FIRST),
    # `attempt` is one verb over two rows, chosen by the runtime's
    # `attempt_budget_spent` condition exactly as `park`'s two rows are chosen
    # by its reason's axis. Both are intents rather than world-facts: an
    # attempt is declared before it is made, and the exhaustion park is a
    # decision this layer takes -- so both lead with the tracker, and the
    # under-budget row's explicit none makes that ordering a no-op the way it
    # already is for `park:scheduling`.
    PairingRow("attempt:under-budget", "attempt", "fix_attempted", None, Order.TRACKER_FIRST),
    PairingRow(
        "attempt:exhausted", "attempt", "item_parked", TrackerVerb.PARK, Order.TRACKER_FIRST
    ),
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

# Verbs inside the closed universe that no slice has wired yet: `next` is the
# open-new-work decision surface. It lands by deleting its name from here and
# adding its parser, so the totality test measures the gap instead of ignoring
# it.
PENDING_VERBS: frozenset[str] = frozenset({"next"})

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
    kind: str | None = None


@dataclass(frozen=True)
class Plan:
    """What one executor verb will do: at most one runtime append, at most one
    tracker write.

    `payload is None` is the state-checked idempotent skip (S9T1-D6): the fold
    already records this exact command, so re-running appends no duplicate and
    still reports success. The tracker side is re-issued regardless -- the
    facade verbs are idempotent, and a response-lost retry has to be able to
    converge the side that did not land.

    `report` is the verb-specific block the envelope carries beside the
    enactment report -- `attempt`'s counts (S9T1-D11) are the only one today.

    `refusal` is a typed failure the plan carries *through* its enactment: the
    exhaustion row parks the item and then refuses the attempt (S9T1-C2), so
    the refusal has to survive a successful enactment rather than pre-empt it.
    It lives on the plan, and `enact` raises it, so a caller reaching the
    pairing layer directly cannot enact the park and miss the refusal.
    """

    row: PairingRow
    item: ItemView
    payload: dict[str, JsonValue] | None
    park_reason: str | None = None
    park_note: str | None = None
    report: dict[str, JsonValue] | None = None
    refusal: ExecutorError | None = None

    @property
    def appends(self) -> bool:
        return self.payload is not None


def _require(value: int | str | None, verb: str, flag: str) -> int | str:
    if value is None:
        raise ExecutorError(ErrorCode.USAGE, f"{verb} requires {flag}")
    return value


def _resolve(rules: RowRules, request: Request) -> tuple[Request, bool]:
    """The shared middle of every builder.

    Matrix C first, since a defaulted field can be part of the identity; then
    Matrix B's "is this exact command already recorded"; then Matrix A's
    preconditions. Returns the normalized request and whether to skip.
    """
    request = apply_payload_rules(rules, request)
    if already_recorded(rules, request):
        return request, True
    check_preconditions(rules, request)
    return request, False


def _plan_start(item: ItemView, state: RunState) -> Plan:
    rules, row = ROW_RULES["start"], ROWS["start"]
    _, skip = _resolve(rules, Request(item=item, state=state))
    if skip:
        return Plan(row, item, None)
    return Plan(row, item, {"item": item.id})


def _plan_park(args: VerbArgs, item: ItemView, state: RunState) -> Plan:
    reason = str(_require(args.reason, "park", "--reason"))
    axis = park_axis(reason)
    key = "park:failure" if axis is Axis.FAILURE else "park:scheduling"
    rules, row = ROW_RULES[key], ROWS[key]
    # Matrix C fills the note: `item_parked.note` is required, and a park whose
    # note only repeats its typed reason says exactly as much as the reason.
    request, skip = _resolve(rules, Request(item=item, state=state, reason=reason, note=args.note))
    note = request.note or reason
    if skip:
        return Plan(row, item, None, park_reason=reason, park_note=note)
    payload: dict[str, JsonValue] = {"item": item.id, "reason": reason, "note": note}
    return Plan(row, item, payload, park_reason=reason, park_note=note)


def _plan_redispatch(item: ItemView, state: RunState) -> Plan:
    rules, row = ROW_RULES["redispatch"], ROWS["redispatch"]
    _, skip = _resolve(rules, Request(item=item, state=state))
    if skip:
        return Plan(row, item, None)
    return Plan(row, item, {"item": item.id, "lane": item.lane})


def _plan_abandon(args: VerbArgs, item: ItemView, state: RunState) -> Plan:
    pr = int(_require(args.pr, "abandon", "--pr"))
    rules, row = ROW_RULES["abandon"], ROWS["abandon"]
    request, skip = _resolve(rules, Request(item=item, state=state, pr=pr, reason=args.reason))
    if skip:
        return Plan(row, item, None)
    payload: dict[str, JsonValue] = {
        "item": item.id,
        "lane": item.lane,
        # The single park exit carries the closure, so an abandoned PR is
        # recorded without granting `pr_closed` a new source state.
        "closure": {"pr": pr, "reason": request.reason},
    }
    return Plan(row, item, payload)


def _plan_pr_opened(args: VerbArgs, item: ItemView, state: RunState) -> Plan:
    pr = int(_require(args.pr, "pr-opened", "--pr"))
    rules, row = ROW_RULES["pr-opened"], ROWS["pr-opened"]
    _, skip = _resolve(rules, Request(item=item, state=state, pr=pr))
    if skip:
        return Plan(row, item, None)
    return Plan(row, item, {"item": item.id, "pr": pr})


def _plan_pr_closed(args: VerbArgs, item: ItemView, state: RunState) -> Plan:
    pr = int(_require(args.pr, "pr-closed", "--pr"))
    next_status = str(_require(args.next_status, "pr-closed", "--next"))
    reason = str(_require(args.reason, "pr-closed", "--reason"))
    rules, row = ROW_RULES["pr-closed"], ROWS["pr-closed"]
    request, skip = _resolve(
        rules, Request(item=item, state=state, pr=pr, next_status=next_status, reason=reason)
    )
    if skip:
        return Plan(row, item, None)
    payload: dict[str, JsonValue] = {
        "item": item.id,
        "pr": pr,
        "next": next_status,
        "reason": request.reason,
    }
    return Plan(row, item, payload)


def _plan_merged(args: VerbArgs, item: ItemView, state: RunState) -> Plan:
    sha = str(_require(args.sha, "merged", "--sha"))
    rules, row = ROW_RULES["merged"], ROWS["merged"]
    _, skip = _resolve(rules, Request(item=item, state=state, sha=sha))
    if skip:
        return Plan(row, item, None)
    # The PR comes from the fold, never from an argument: closed means merged,
    # and the executor must not be able to close against a PR the runtime never
    # saw. `Requires.PR_REFERENCE` has already proven it is there.
    return Plan(row, item, {"item": item.id, "pr": item.pr_number, "sha": sha})


def _plan_done(item: ItemView, state: RunState) -> Plan:
    rules, row = ROW_RULES["done"], ROWS["done"]
    _, skip = _resolve(rules, Request(item=item, state=state))
    if skip:
        return Plan(row, item, None)
    return Plan(row, item, {"item": item.id})


def _plan_exhausted(spent: BudgetSpent, item: ItemView, state: RunState) -> Plan:
    """The refusal that parks first (S9T1-C2).

    Takes the condition itself rather than looking it up again: the numbers
    reported are the runtime's, never recomputed here, and reporting one it
    did not decide on would let the report and the fact disagree.
    """
    rules, row = ROW_RULES["attempt:exhausted"], ROWS["attempt:exhausted"]
    # `_resolve`'s skip is statically False here: the row declares no recorded
    # transition (Matrix B), which the matrix suite walks.
    request, _ = _resolve(
        rules, Request(item=item, state=state, kind=spent.kind, reason=BUDGET_EXHAUSTED)
    )
    note = request.note or BUDGET_EXHAUSTED
    return Plan(
        row,
        item,
        {"item": item.id, "reason": BUDGET_EXHAUSTED, "note": note},
        park_reason=BUDGET_EXHAUSTED,
        park_note=note,
        report={
            "kind": spent.kind,
            "attempts": spent.attempts,
            "budget": spent.budget,
            "proceed": False,
        },
        refusal=ExecutorError(
            ErrorCode.BUDGET_EXHAUSTED,
            f"the {spent.kind} budget for item {item.id!r} is spent "
            f"({spent.attempts} of {spent.budget}); it is parked as {BUDGET_EXHAUSTED}",
        ),
    )


def _plan_attempt(args: VerbArgs, item: ItemView, state: RunState) -> Plan:
    """One verb, two rows, chosen by the runtime's condition and nothing else.

    S9T1-C3: `attempt_budget_spent` is the single definition of exhaustion.
    This layer keeps no counter, compares no threshold, and reads the counts
    only to report them.
    """
    kind = attempt_kind(str(_require(args.kind, "attempt", "--kind")))
    spent = state.budget_spent.get((item.id, kind.kind))
    if spent is not None:
        return _plan_exhausted(spent, item, state)

    rules, row = ROW_RULES["attempt:under-budget"], ROWS["attempt:under-budget"]
    # Same static-False skip as above, and here it is also what the row means:
    # a repeat is a second attempt, not a retry.
    _resolve(rules, Request(item=item, state=state, kind=kind.kind))
    budget = attempt_budget(kind, state.config)
    # The ledger as this command leaves it, not as it found it: the append is a
    # pre-charge, so by the time the caller reads this the attempt is spent.
    charged = item.attempts.get(kind.kind, 0) + 1
    return Plan(
        row,
        item,
        {"item": item.id, "kind": kind.kind},
        report={
            "kind": kind.kind,
            "attempts": charged,
            "budget": budget,
            "remaining": budget - charged,
            "proceed": True,
        },
    )


def build_plan(verb: str, args: VerbArgs, state: RunState) -> Plan:
    """Resolve one executor verb against the folded state into a `Plan`.

    Refusals are raised, never returned as a degenerate plan: a caller that
    forgot to check a `Plan.refused` flag would enact half a row.
    """
    item = state.item(args.item)
    if verb == "start":
        return _plan_start(item, state)
    if verb == "park":
        return _plan_park(args, item, state)
    if verb == "redispatch":
        return _plan_redispatch(item, state)
    if verb == "abandon":
        return _plan_abandon(args, item, state)
    if verb == "pr-opened":
        return _plan_pr_opened(args, item, state)
    if verb == "pr-closed":
        return _plan_pr_closed(args, item, state)
    if verb == "merged":
        return _plan_merged(args, item, state)
    if verb == "done":
        return _plan_done(item, state)
    if verb == "attempt":
        return _plan_attempt(args, item, state)
    raise ExecutorError(ErrorCode.USAGE, f"unknown executor verb {verb!r}")
