"""The S9T1-D11 envelope: one protocol-versioned JSON object per invocation.

Exactly one envelope reaches stdout, success or failure, and a failure is never
a traceback. `error` is `{code, message, retryable, data?}`; whether a code is
retryable is a property of the code, not of the call site, so it is looked up
here rather than passed in -- two call sites cannot disagree about whether
`E_SYNC_FAILED` is worth retrying.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TextIO

from executor import PROTOCOL_VERSION

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class ErrorCode(StrEnum):
    """The closed code set.

    The first seven are S9T1-D11's enumeration: four transport failures that a
    retry can clear, then three contract refusals that it cannot.
    `E_ITEM_PARKED` and `E_BUDGET_EXHAUSTED` are raised by `executor attempt`
    (slice C) and are declared here because the code set is the contract, not
    the current call sites.

    `E_USAGE` and `E_INTERNAL` extend that enumeration. D11 names no code for a
    malformed argv, a reference to an item the runtime has never folded, or an
    unexpected exception -- and "a failure is never a traceback" leaves those
    needing a code all the same. Both are non-retryable: the caller has to
    change something before re-running.
    """

    TRACKER_SUBPROCESS = "E_TRACKER_SUBPROCESS"
    RUNTIME_SUBPROCESS = "E_RUNTIME_SUBPROCESS"
    RUNTIME_ENVELOPE = "E_RUNTIME_ENVELOPE"
    SYNC_FAILED = "E_SYNC_FAILED"
    ITEM_PARKED = "E_ITEM_PARKED"
    NO_OPEN_PR = "E_NO_OPEN_PR"
    BUDGET_EXHAUSTED = "E_BUDGET_EXHAUSTED"
    USAGE = "E_USAGE"
    INTERNAL = "E_INTERNAL"


# A transport failure says the call did not get through, so the same command
# run again is the repair. A contract refusal says the command was answered and
# refused, so re-running it unchanged only repeats the refusal.
RETRYABLE_CODES: frozenset[ErrorCode] = frozenset(
    {
        ErrorCode.TRACKER_SUBPROCESS,
        ErrorCode.RUNTIME_SUBPROCESS,
        ErrorCode.RUNTIME_ENVELOPE,
        ErrorCode.SYNC_FAILED,
    }
)


@dataclass(frozen=True)
class ExecutorError(Exception):
    """A typed failure on its way to the envelope. `data` is the optional
    `error.data` block -- `E_BUDGET_EXHAUSTED` carries its counts there, and a
    failed trailing sync carries the mutations that did land."""

    code: ErrorCode
    message: str
    data: dict[str, JsonValue] = field(default_factory=dict)

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CODES


def error_json(err: ExecutorError) -> dict[str, JsonValue]:
    """`error.data` is omitted when empty rather than emitted as `{}` -- D11
    marks it optional, and an empty object reads as "there were details" to a
    consumer that only checks for the key."""
    payload: dict[str, JsonValue] = {
        "code": str(err.code),
        "message": err.message,
        "retryable": err.retryable,
    }
    if err.data:
        payload["data"] = dict(err.data)
    return payload


def emit_success(data: JsonValue, out: TextIO = sys.stdout) -> int:
    json.dump({"protocol": PROTOCOL_VERSION, "ok": True, "data": data, "error": None}, out)
    out.write("\n")
    return 0


def emit_failure(err: ExecutorError, out: TextIO = sys.stdout) -> int:
    json.dump(
        {"protocol": PROTOCOL_VERSION, "ok": False, "data": None, "error": error_json(err)},
        out,
    )
    out.write("\n")
    return 1
