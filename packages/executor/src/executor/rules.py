"""The three matrices every S9T1-D12 row is decided by.

`S9T1-D12` closes the pairing universe over *which* verb maps to which event
and which tracker call. It says nothing about three further questions each row
has to answer, every one of which was discovered a cell at a time under
review:

**Matrix A -- the source-state matrix.** Which item states a row may legally
fire from, and the typed refusal for each state it may not. The executor is the
runtime's single writer, so an event it can prove illegal is a caller's
mistake, not something that happened: refusing keeps the log a record of
transitions rather than of the executor's errors. For the tracker-first rows it
is also correctness -- they write to the tracker before appending, so an append
the fold would flag leaves the two planes disagreeing with no retry that
converges.

**Matrix B -- the command-identity tuple.** Which arguments make a
re-invocation *the same command*. `S9T1-D6` says enactment is state-checked
idempotent, and the skip fires only on a full-tuple match against what the fold
records. A partial match is a *different* command: it is enacted or refused on
the merits, never silently skipped. Answering "already done" to a re-invocation
carrying a different PR, outcome, commit or park reason claims a transition
neither plane made.

**Matrix C -- the payload rules.** Which fields the fold requires non-empty in
the event a row appends, and what an empty one becomes -- the row's documented
default, or a refusal. Same standing as the source states: a payload the fold
rejects is a precondition, and on a tracker-first row it is the one that can
diverge the planes, since an empty park note parks the tracker and only then
has the append refused.

All three matrices duplicate facts the runtime's fold owns, which is the cost of
being able to refuse before enacting. `GrindRuntime.append` refusing an
`applied: false` reply is the backstop that catches this file drifting from the
fold, and it names the fold's own reason when it fires.

Two axes are deliberately absent from Matrix A and must stay absent. An item
whose id matches the run-local slug grammar is **not** a refusal (`S9T1-A6`):
handle routing happens in `enact`, and such an item enacts normally with no
tracker call and an `unpromoted` entry. And an item absent from the fold is
refused before a row is ever selected, by `RunState.item`.

`ATTEMPT_KINDS` sits alongside the three as the fourth table: the `--kind`
vocabulary and where each kind's budget number is read from. It answers what a
budget *is*, never whether one is spent -- that is the runtime's
`attempt_budget_spent` condition and only ever that (`S9T1-C3`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
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

# The reason an exhausted budget parks under, on both planes (S9T1-D12). A
# member of the failure axis, which is what makes the exhaustion row's tracker
# column a `work park --reason` rather than the scheduling axis's none.
BUDGET_EXHAUSTED = "budget-exhausted"


# ---------------------------------------------------------------------------
# The attempt kinds and where their budgets come from
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttemptKind:
    """One `--kind`, and where its budget number is read from.

    The config key and the fallback mirror the runtime's, because the executor
    has to *report* a budget on the path where no condition fires -- the same
    standing as Matrix A duplicating the fold's source states, and the same
    backstop: the two are read from one snapshot of the runtime's own `config`,
    so they can only disagree if this table drifts from the runtime's.

    The **decision** never reads this number. Whether a budget is spent is the
    runtime's `attempt_budget_spent` condition and nothing else (S9T1-C3), and
    that condition carries the numbers the refusal reports.
    """

    kind: str
    config_key: str
    default_budget: int


ATTEMPT_KINDS: dict[str, AttemptKind] = {
    "ci-fix": AttemptKind("ci-fix", "ci_fix_budget", 2),
    "rebase": AttemptKind("rebase", "rebase_budget", 1),
}


def attempt_kind(kind: str) -> AttemptKind:
    """The kind a `--kind` names. An unknown one is a refusal, not a default:
    the runtime's fold flags an unrecognized kind as an anomaly, so guessing
    would spend an attempt the ledger never records."""
    found = ATTEMPT_KINDS.get(kind)
    if found is None:
        raise ExecutorError(
            ErrorCode.USAGE,
            f"unknown attempt kind {kind!r}; expected one of {'|'.join(ATTEMPT_KINDS)}",
        )
    return found


def attempt_budget(kind: AttemptKind, config: Mapping[str, JsonValue]) -> int:
    """The caller-seeded budget for a kind, or this table's fallback.

    A seeded `0` is legal and means "spend nothing on this kind", so it is
    honored rather than read as unset -- restoring a default there would hand
    back attempts the caller forbade. A negative or non-integer value is not a
    budget at all and falls back, exactly as the runtime's threshold reader
    does, so both planes report the same number for the same config.
    """
    seeded = config.get(kind.config_key)
    if isinstance(seeded, int) and not isinstance(seeded, bool) and seeded >= 0:
        return seeded
    return kind.default_budget


# ---------------------------------------------------------------------------
# Matrix A vocabulary
# ---------------------------------------------------------------------------

# Source-status sets, named after the fold handler each mirrors.
STARTABLE = frozenset({"queued"})
PARKABLE = frozenset({"queued", "in-progress", "pr-open", "in-review", "waiting-human", "blocked"})
PR_OPENABLE = frozenset({"in-progress", "waiting-human"})
# `pr_closed` and `item_merged` share a source set: both end a live PR.
REVIEWABLE = frozenset({"pr-open", "in-review", "waiting-human"})
DONEABLE = frozenset({"merged"})
# `fix_attempted`'s source set: every status but the two terminal ones. Stated
# separately from `PARKABLE` rather than aliased to it: the two mirror
# different fold handlers, which happen to exclude the same statuses today and
# are each free to change without the other. The status axis only has to keep
# finished work out, because the fold gates an attempt on an open PR reference
# instead -- `in-progress` holds one via a resume and `queued` via a park exit,
# so status alone cannot answer it.
ATTEMPTABLE = frozenset(
    {"queued", "in-progress", "pr-open", "in-review", "waiting-human", "blocked"}
)
# Where a closure leaves an item, and so where a live PR never does.
POST_CLOSURE = frozenset({"in-progress", "queued"})

# `item_enqueued` is the one handler that gates on parkedness instead of
# status, so its rows constrain no status at all.
ANY_STATE: frozenset[str] = frozenset()
# Where an enqueue leaves an item: `queued`, or `blocked` when it re-enters
# play with unresolved blocker edges.
ENQUEUED = frozenset({"queued", "blocked"})


class Parked(StrEnum):
    """Parked is a flag beside a status, not a status.

    A scheduling park leaves an item `queued`, so a status set alone waves a
    parked item straight through. The fold treats a parked item as absent for
    every handler but `item_enqueued`, which is the one that requires it.
    """

    FORBIDDEN = "forbidden"
    REQUIRED = "required"


class Requires(StrEnum):
    """Preconditions that are not about status.

    `PR_MATCHES_ITEM` has no counterpart in the fold at all -- the fold
    compares an event's PR against nothing, so a delayed notification naming a
    superseded PR would be taken as fact and, for `pr-closed`, would tear down
    the live review cycle.

    It is strict about absence: an item holding no reference matches no PR.
    A requirement named "the PR matches" that passed vacuously when there was
    no PR would be a trap for the next row that used it -- which is exactly
    how `pr-closed` came to accept an invented closure against an item that
    had never opened one. Rows wanting the clearer `E_NO_OPEN_PR` for that
    case pair it with `PR_REFERENCE`, which is why the two stay separate.

    `OPEN_PR` is the strictly stronger form of `PR_REFERENCE` and the two are
    not interchangeable. A closure leaves the reference behind and marks it
    closed, which is deliberate: a failure-axis park describes a PR that
    already failed to merge, so a reference is what it needs, while a fix
    attempt claims to be fixing one that is still open. Reading a reference as
    an open PR would charge a budget against a cycle that is over.
    """

    LANE = "lane"
    PR_REFERENCE = "pr-reference"
    PR_MATCHES_ITEM = "pr-matches-item"
    OPEN_PR = "open-pr"


@dataclass(frozen=True)
class PayloadRule:
    """One Matrix C cell: a `VerbArgs` field the fold requires non-empty.

    `default` supplies the value an empty or absent one takes, computed from
    the rest of the request; `None` means an empty value is a refusal. The
    difference is per row and documented, not a house style -- a park note has
    a natural stand-in (its reason code) while a merge commit does not.
    """

    field: str
    default: Callable[[Request], str] | None = None


@dataclass(frozen=True)
class Request:
    """One resolved command: the item it names and the arguments it carries."""

    item: ItemView
    state: RunState
    pr: int | None = None
    sha: str | None = None
    next_status: str | None = None
    reason: str | None = None
    note: str | None = None
    kind: str | None = None


Identity = tuple[JsonValue, ...]


@dataclass(frozen=True)
class RowRules:
    """One row of both matrices.

    `identity_fields` names Matrix B's tuple for documentation and for the
    refusal message; `identity` and `recorded` compute the two sides that are
    compared. `recorded` returns `None` when the fold records no such
    transition for this item at all.
    """

    key: str
    verb: str
    legal_states: frozenset[str]
    parked: Parked
    requires: tuple[Requires, ...]
    identity_fields: tuple[str, ...]
    identity: Callable[[Request], Identity]
    recorded: Callable[[Request], Identity | None]
    payload: tuple[PayloadRule, ...] = ()
    notes: str = field(default="")


# ---------------------------------------------------------------------------
# Matrix B: what each row's identity is, and what the fold records of it
# ---------------------------------------------------------------------------


def park_typing(reason: str) -> str | None:
    """How the runtime types a park produced from free text.

    `pr_closed.reason` shares a field name with the park vocabulary and not its
    contract: on the `parked` path the runtime runs it through this same
    lookup, typing the park when the text names a member and leaving it untyped
    otherwise.
    """
    return reason if reason in FAILURE_REASONS or reason in SCHEDULING_REASONS else None


def _closed_out(item: ItemView) -> bool:
    """Whether the item sits where a closure leaves it and a live PR does not."""
    return item.parked or item.status in POST_CLOSURE


def _item_only(request: Request) -> Identity:
    return (request.item.id,)


def _started_recorded(request: Request) -> Identity | None:
    item = request.item
    return (item.id,) if item.status == "in-progress" and not item.parked else None


def _park_identity(request: Request) -> Identity:
    return (request.item.id, request.reason)


def _park_recorded(request: Request) -> Identity | None:
    item = request.item
    return (item.id, item.park_reason) if item.parked else None


def _enqueued_recorded(request: Request) -> Identity | None:
    """Back in play *and* still where the enqueue left it.

    "Not parked" alone is also true of every state the item reaches
    afterwards, so a delayed duplicate would be read as a retry: the append is
    suppressed but the tracker verb is deliberately re-issued, and `work
    redispatch` refuses an item it has already moved on from -- turning a
    completed command into a transport failure and an unnecessary sync.
    """
    item = request.item
    if item.parked or item.status not in ENQUEUED:
        return None
    return (item.id,)


def _abandon_identity(request: Request) -> Identity:
    return (request.item.id, request.pr)


def _abandon_recorded(request: Request) -> Identity | None:
    """A *cleared* PR reference plus a closure for that PR, and nothing weaker.

    Only an abandon produces both: `S9T1-B7` has the fold clear the reference
    when it interprets the closure an `item_enqueued` carries, where an
    ordinary `pr_closed` records its closure and leaves the reference in place.
    Nothing else clears a reference at all.

    Weaker proxies were each tried and each matches a state some other command
    produces -- being out of the parking lot, the surviving reference, ledger
    membership alone -- and an ordinary `pr-closed --next queued` looks
    identical under every one of them. That is why the conjunction is the
    evidence and no single half of it is.
    """
    item = request.item
    if item.pr_number is not None or request.pr is None:
        return None
    return (item.id, request.pr) if (item.id, request.pr) in request.state.closures else None


def _pr_opened_identity(request: Request) -> Identity:
    return (request.item.id, request.pr)


def _pr_opened_recorded(request: Request) -> Identity | None:
    """An opened PR outlives the `pr-open` status -- review, a human wait, a
    blocker, a merge -- so the evidence is the reference plus the item not
    sitting where a closure leaves it.

    The closed-PR ledger cannot answer this: it holds closures with no
    counterpart for openings, so a PR closed once and reopened looks the same
    as one still closed, forever.
    """
    item = request.item
    if item.pr_number is None or _closed_out(item):
        return None
    return (item.id, item.pr_number)


def _closure_outcome(request: Request) -> JsonValue:
    """The requested `--next`, normalised so both sides compare alike.

    A closure to `parked` leaves the item's review status alone and sets the
    park instead, so status is the wrong thing to compare it against.
    """
    if request.next_status == "parked" and request.reason is not None:
        return f"parked:{park_typing(request.reason)}"
    return request.next_status


def _pr_closed_identity(request: Request) -> Identity:
    return (request.item.id, request.pr, _closure_outcome(request))


def _pr_closed_recorded(request: Request) -> Identity | None:
    """The ledger entry, the item's position, and nothing having touched it
    since.

    Each of the first two covers the other's blind spot: the ledger alone
    deduplicates every closure of a PR number forever, so a PR closed, reopened
    and closed again would never record its second closure; the position alone
    cannot tell "already closed" from "resumed out of a human wait with the PR
    still open", which lands in the same place having closed nothing.

    The ledger records no outcome, so the position stands in for one -- and a
    position only speaks for this closure while the closure is still the last
    thing that touched the item. Timestamps are second-granular, so an
    intervening event inside the same second still defeats that guard
    (measured, not assumed). What is left is benign: this row writes nothing
    and calls no tracker verb. Closing it exactly needs the ledger to record
    each closure's `next`, which is the runtime's to add.
    """
    item, state = request.item, request.state
    if request.pr is None or not _closed_out(item):
        # Sitting where a live PR puts it means the closure is not in effect --
        # the PR was reopened, and this is a new cycle's closure rather than
        # any retry of the recorded one, whatever the ledger still remembers.
        return None
    closure_ts = state.closures.get((item.id, request.pr))
    if closure_ts is None or state.last_item_ts.get(item.id) != closure_ts:
        return None
    outcome = f"parked:{item.park_reason}" if item.parked else item.status
    return (item.id, request.pr, outcome)


def _merged_identity(request: Request) -> Identity:
    return (request.item.id, request.sha)


def _merged_recorded(request: Request) -> Identity | None:
    """ "Already merged" is not "already merged at this commit".

    A ledger entry with no commit cannot answer which one, so it produces an
    identity that matches nothing and the request is refused rather than
    skipped -- an unanswerable probe never authorises a skip.
    """
    item = request.item
    if item.status not in ("merged", "done") or item.parked:
        return None
    return (item.id, request.state.merged_shas.get(item.id))


def _done_recorded(request: Request) -> Identity | None:
    item = request.item
    return (item.id,) if item.status == "done" and not item.parked else None


def _attempt_identity(request: Request) -> Identity:
    return (request.item.id, request.kind)


def _no_recorded_transition(_request: Request) -> Identity | None:
    """Both `attempt` rows: the fold records no transition this row could be a
    retry of, so nothing here ever authorises a skip.

    Under budget, `fix_attempted` folds into a *count*, not a transition. Two
    identical invocations are two attempts, not one attempt and its retry, and
    the fold is built to say so -- it counts past the budget and never caps
    (S9T1-B2). Nothing in the state can tell a response-lost retry from a
    genuine second attempt, and the pre-charge picks the safe side of that:
    over-counting spends one more attempt inside a bound that exists for the
    purpose, where under-counting removes the bound.

    At exhaustion the row's park *is* a transition, but the condition that
    selects the row is absent for a parked item -- so once the park is on
    record the row is unreachable and the reachable answer to "already
    exhausted?" is the under-budget row's parked refusal (S9T1-C5).
    """
    return None


# ---------------------------------------------------------------------------
# The matrices, as one table
# ---------------------------------------------------------------------------

ROW_RULES: dict[str, RowRules] = {
    "start": RowRules(
        key="start",
        verb="start",
        legal_states=STARTABLE,
        parked=Parked.FORBIDDEN,
        requires=(),
        identity_fields=("item",),
        identity=_item_only,
        recorded=_started_recorded,
    ),
    "park:failure": RowRules(
        key="park:failure",
        verb="park",
        legal_states=PARKABLE,
        parked=Parked.FORBIDDEN,
        requires=(Requires.PR_REFERENCE,),
        identity_fields=("item", "reason"),
        identity=_park_identity,
        recorded=_park_recorded,
        payload=(PayloadRule("note", lambda request: request.reason or ""),),
        notes=(
            "A failure reason states this item's PR did not merge, so the fold "
            "refuses one on an item holding no PR -- keyed on the reference, not "
            "on status. The note is not part of the identity: it is free text a "
            "retry may legitimately word differently."
        ),
    ),
    "park:scheduling": RowRules(
        key="park:scheduling",
        verb="park",
        legal_states=PARKABLE,
        parked=Parked.FORBIDDEN,
        requires=(),
        identity_fields=("item", "reason"),
        identity=_park_identity,
        recorded=_park_recorded,
        payload=(PayloadRule("note", lambda request: request.reason or ""),),
        notes="A sequencing decision makes no claim about a PR and needs none.",
    ),
    "redispatch": RowRules(
        key="redispatch",
        verb="redispatch",
        legal_states=ANY_STATE,
        parked=Parked.REQUIRED,
        requires=(Requires.LANE,),
        identity_fields=("item",),
        identity=_item_only,
        recorded=_enqueued_recorded,
    ),
    "abandon": RowRules(
        key="abandon",
        verb="abandon",
        legal_states=ANY_STATE,
        parked=Parked.REQUIRED,
        requires=(Requires.PR_REFERENCE, Requires.PR_MATCHES_ITEM, Requires.LANE),
        identity_fields=("item", "pr"),
        identity=_abandon_identity,
        recorded=_abandon_recorded,
        payload=(PayloadRule("reason", lambda _request: "abandoned"),),
        notes=(
            "The closure this writes goes into the log as the record, so the PR "
            "it names has to be the item's own."
        ),
    ),
    "pr-opened": RowRules(
        key="pr-opened",
        verb="pr-opened",
        legal_states=PR_OPENABLE,
        parked=Parked.FORBIDDEN,
        requires=(),
        identity_fields=("item", "pr"),
        identity=_pr_opened_identity,
        recorded=_pr_opened_recorded,
        notes="A different PR number is new work, not a retry -- no match required.",
    ),
    "pr-closed": RowRules(
        key="pr-closed",
        verb="pr-closed",
        legal_states=REVIEWABLE,
        parked=Parked.FORBIDDEN,
        # `waiting-human` is reachable without a PR ever having opened, and the
        # fold does not check for one either, so without PR_REFERENCE a closure
        # could be invented against a waiting item and silently move it.
        requires=(Requires.PR_REFERENCE, Requires.PR_MATCHES_ITEM),
        identity_fields=("item", "pr", "next"),
        identity=_pr_closed_identity,
        recorded=_pr_closed_recorded,
        payload=(PayloadRule("reason"),),
        notes=(
            "`reason` is outside the identity as text, but it is inside it on the "
            "`parked` path, where the runtime types the park from it."
        ),
    ),
    "merged": RowRules(
        key="merged",
        verb="merged",
        legal_states=REVIEWABLE,
        parked=Parked.FORBIDDEN,
        requires=(Requires.PR_REFERENCE,),
        identity_fields=("item", "sha"),
        identity=_merged_identity,
        recorded=_merged_recorded,
        payload=(PayloadRule("sha"),),
        notes="The PR comes from the fold, never from an argument, so it cannot mismatch.",
    ),
    "done": RowRules(
        key="done",
        verb="done",
        legal_states=DONEABLE,
        parked=Parked.FORBIDDEN,
        requires=(),
        identity_fields=("item",),
        identity=_item_only,
        recorded=_done_recorded,
    ),
    "attempt:under-budget": RowRules(
        key="attempt:under-budget",
        verb="attempt",
        legal_states=ATTEMPTABLE,
        parked=Parked.FORBIDDEN,
        requires=(Requires.OPEN_PR,),
        identity_fields=("item", "kind"),
        identity=_attempt_identity,
        recorded=_no_recorded_transition,
        notes=(
            "The one row whose append is deliberately not idempotent: it charges "
            "a counter, and charging it twice is what a second attempt means. "
            "The append is also a pre-charge -- it lands before any fix runs, "
            "because a crash after this call has already spent the attempt and a "
            "budget that counted only completed attempts would bound nothing."
        ),
    ),
    "attempt:exhausted": RowRules(
        key="attempt:exhausted",
        verb="attempt",
        legal_states=ATTEMPTABLE,
        parked=Parked.FORBIDDEN,
        requires=(Requires.OPEN_PR,),
        identity_fields=("item", "reason"),
        identity=_park_identity,
        recorded=_no_recorded_transition,
        payload=(PayloadRule("note", lambda request: request.reason or ""),),
        notes=(
            "The same refusal edges as the row above, checked before the branch "
            "matters: a parked item or an item holding no open PR is refused "
            "with zero events and zero tracker calls whichever side of the "
            "budget it is on (S9T1-C4). Beyond them this is a failure-axis park, "
            "so it needs what one needs -- and `OPEN_PR` is strictly stronger "
            "than the reference `park:failure` asks for."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Applying the matrices
# ---------------------------------------------------------------------------


def _render(fields: tuple[str, ...], identity: Identity) -> str:
    return ", ".join(f"{name}={value!r}" for name, value in zip(fields, identity, strict=False))


def _filled(request: Request, field_name: str, value: str) -> Request:
    """`replace` with a dynamic field name defeats the type checker, so the
    fields Matrix C may fill are named here -- which also keeps that a closed
    set rather than anything a rule feels like reaching for."""
    if field_name == "note":
        return replace(request, note=value)
    if field_name == "reason":
        return replace(request, reason=value)
    if field_name == "sha":
        return replace(request, sha=value)
    raise ExecutorError(ErrorCode.INTERNAL, f"no payload rule may fill {field_name!r}")


def apply_payload_rules(rules: RowRules, request: Request) -> Request:
    """Apply Matrix C, returning the request with defaults filled in.

    Runs before identity is computed, because a defaulted field can be part of
    it. A field the fold requires non-empty and this row gives no default is a
    refusal here rather than an append the fold rejects -- which on a
    tracker-first row would have parked the tracker first.
    """
    resolved = request
    for rule in rules.payload:
        if getattr(resolved, rule.field):
            continue
        if rule.default is None:
            raise ExecutorError(
                ErrorCode.USAGE,
                f"{rules.verb} requires a non-empty --{rule.field}",
            )
        filled = rule.default(resolved)
        if not filled:
            # A default computed from another field can itself come back empty.
            # Appending that would hand the fold exactly the payload this axis
            # exists to keep away from it, so the table is at fault, not the
            # caller.
            raise ExecutorError(
                ErrorCode.INTERNAL,
                f"the {rules.key!r} default for {rule.field!r} produced an empty value",
            )
        resolved = _filled(resolved, rule.field, filled)
    return resolved


def already_recorded(rules: RowRules, request: Request) -> bool:
    """Whether this exact command is on record (Matrix B).

    A row recorded for this item under a *different* identity is refused here
    rather than falling through: the request names something that never
    happened, and the refusal can say so precisely while the generic
    precondition checks below could only say the status is wrong.
    """
    recorded = rules.recorded(request)
    if recorded is None:
        return False
    wanted = rules.identity(request)
    if recorded == wanted:
        return True
    code = (
        ErrorCode.ITEM_PARKED
        if request.item.parked and rules.parked is Parked.FORBIDDEN
        else ErrorCode.USAGE
    )
    raise ExecutorError(
        code,
        f"{rules.verb} is already recorded for item {request.item.id!r} as "
        f"[{_render(rules.identity_fields, recorded)}], not "
        f"[{_render(rules.identity_fields, wanted)}]",
    )


def _check_parked(rules: RowRules, item: ItemView) -> None:
    if rules.parked is Parked.FORBIDDEN and item.parked:
        raise ExecutorError(
            ErrorCode.ITEM_PARKED,
            f"{rules.verb} is not legal on parked item {item.id!r}; "
            f"the parking lot's only exit is a redispatch or an abandon",
        )
    if rules.parked is Parked.REQUIRED and not item.parked:
        raise ExecutorError(
            ErrorCode.USAGE,
            f"{rules.verb} applies to a parked item, and {item.id!r} is not parked",
        )


def _check_requirement(rules: RowRules, request: Request, requirement: Requires) -> None:
    item = request.item
    if requirement is Requires.LANE and item.lane is None:
        raise ExecutorError(
            ErrorCode.USAGE,
            f"{rules.verb} needs the item's lane, and {item.id!r} is not on one",
        )
    if requirement is Requires.PR_REFERENCE and item.pr_number is None:
        raise ExecutorError(
            ErrorCode.NO_OPEN_PR,
            f"{rules.verb} needs a PR, and item {item.id!r} holds no PR reference",
        )
    if requirement is Requires.OPEN_PR and not item.pr_open:
        # The two cases read very differently to an operator: one item never
        # opened a PR, the other holds a reference a closure left behind and
        # marked closed. Collapsing them would send someone looking for a PR
        # the state names right there.
        held = (
            f"its PR {item.pr_number} is not recorded open"
            if item.pr_number is not None
            else f"item {item.id!r} holds no PR reference"
        )
        raise ExecutorError(
            ErrorCode.NO_OPEN_PR,
            f"{rules.verb} needs an open PR, and {held}",
        )
    if (
        requirement is Requires.PR_MATCHES_ITEM
        and request.pr is not None
        and item.pr_number != request.pr
    ):
        raise ExecutorError(
            ErrorCode.USAGE,
            f"item {item.id!r} is on PR {item.pr_number}, not {request.pr}; "
            f"recording a closure for a PR the item is not on would name the wrong cycle",
        )


def check_preconditions(rules: RowRules, request: Request) -> None:
    """Apply Matrix A: the parked rule, the source-status set, then the row's
    non-status requirements in their declared order."""
    item = request.item
    _check_parked(rules, item)
    if rules.legal_states and item.status not in rules.legal_states:
        raise ExecutorError(
            ErrorCode.USAGE,
            f"{rules.verb} is not legal from status {item.status!r}; "
            f"the runtime accepts it from {'|'.join(sorted(rules.legal_states))}",
        )
    for requirement in rules.requires:
        _check_requirement(rules, request, requirement)
