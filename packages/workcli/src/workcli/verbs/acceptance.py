"""`work acceptance set ID TEXT [--why REASON]` -- correcting the contract, on the record.

Its own verb family for the same reason `track set` is: `update` is
replace-semantics over scalar fields, and a silent replace is the one thing
acceptance criteria must never have. They are the termination condition a
claim is checked against, so criteria quietly rewritten to match whatever was
built let the check pass because the contract moved rather than because the
work met it. Everything here exists to keep that visible.

THE TRAIL. The criteria being superseded are quoted into a note, and the note
is written BEFORE the replacement. The order is the integrity argument: a
failure between the two writes can only ever leave a trail without a change,
never a change without a trail. Nothing extra is needed to tell those apart
either -- the note quotes what it superseded, so criteria that still equal the
quote are criteria the replacement never reached. A retry appends a second
entry rather than deduplicating, because a second attempt is a second event
and the history of the contract is the thing being preserved.

THE GATE. Once anybody has started, the change needs a stated reason, and the
note records that work was underway when the target moved. Refusing outright
was the alternative and it is worse: `release` is one call away, leaves no
trace of its own, and returns the item to a status this verb waves through --
so a refusal would convert a recorded mid-flight change into an unrecorded
one. What is required instead is the sentence a reviewer needs. "Started" is
read as "not one of the two statuses meaning nobody has picked this up", so a
parked item -- work that began and stuck -- takes the gate exactly as a claim
in hand does.
"""

from __future__ import annotations

from argparse import Namespace
from datetime import datetime

from workcli.backend import Backend
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.lifecycle.defer import DEFERRED_STATUS

# full: "[work] acceptance restated <ISO-8601>[ while <status>][: <why>]"
RESTATED_MARKER = "[work] acceptance restated"
# The same line for an item that carried no criteria at all. Two markers
# rather than one, because "nothing was superseded" and "the quote is missing"
# are different facts and a reader should not have to infer the first from the
# second.
FIRST_SET_MARKER = "[work] acceptance first set"
QUOTE_PREFIX = "> "

# The statuses meaning nobody has started: criteria move freely here, which is
# the ordinary case this verb exists for. Every other status -- a claim in
# hand, a parked item, a closed one -- requires a stated reason.
_UNSTARTED_STATUSES = frozenset({"open", DEFERRED_STATUS})


def _require_criteria(text: str) -> str:
    """Refuse a blank restatement: this verb states a contract, never removes one.

    An unset shell variable expands to exactly this, and emptying the criteria
    a claim is checked against is not what anyone typing a correction means --
    the same reason `update --set-parent` refuses an empty id.
    """
    if not text.strip():
        raise WorkError(
            ErrorCode.USAGE,
            "acceptance set requires criteria; it restates them, it cannot remove them",
            detail={"field": "acceptance"},
        )
    return text


def _require_single_line_reason(why: str | None) -> str | None:
    """The reason's shape rule: non-blank and single-line, or absent entirely.

    It travels on the marker's own line, so a second line would land in the
    note unquoted, beside the criteria the note preserves.
    """
    if why is None:
        return None
    stripped = why.strip()
    if not stripped or "\n" in stripped or "\r" in stripped:
        raise WorkError(
            ErrorCode.USAGE,
            "--why must be a non-blank, single-line reason",
            detail={"field": "why"},
        )
    return stripped


def _marker_line(previous: str | None, now: datetime, status: str, why: str | None) -> str:
    head = FIRST_SET_MARKER if previous is None else RESTATED_MARKER
    line = f"{head} {now.isoformat()}"
    if status not in _UNSTARTED_STATUSES:
        line += f" while {status}"
    if why is not None:
        line += f": {why}"
    return line


def _trail(previous: str | None, now: datetime, status: str, why: str | None) -> str:
    """The whole note: the marker, then the superseded criteria, quoted line by line.

    The quote prefix is what keeps a later note appended underneath from
    reading as part of the criteria this one preserved.
    """
    line = _marker_line(previous, now, status, why)
    if previous is None:
        return line
    return "\n".join([line, *(f"{QUOTE_PREFIX}{part}" for part in previous.splitlines())])


def acceptance(backend: Backend, args: Namespace) -> JsonValue:
    """Dispatch `work acceptance ACTION`; v1 ships `set` only (argparse pins choices)."""
    text = _require_criteria(args.text)
    why = _require_single_line_reason(args.why)
    item = backend.get(args.id)

    if item.status not in _UNSTARTED_STATUSES and why is None:
        raise WorkError(
            ErrorCode.FIELD_CLOBBER_GUARD,
            f"{args.id}: work has started ({item.status}); moving the criteria a claim is "
            "checked against now requires --why, which is recorded on the item",
            detail={"field": "acceptance", "status": item.status},
        )

    payload: JsonValue = {
        "id": args.id,
        "acceptance": text,
        "previous": item.acceptance,
        "status": item.status,
    }
    if item.acceptance == text:
        # Replay safety: converge on the state already there rather than mint a
        # trail entry for a change nobody made.
        return payload

    backend.append_note(args.id, _trail(item.acceptance, args.now(), item.status, why))
    backend.set_acceptance(args.id, text)
    return payload
