"""The S9T1-D11 envelope contract: one versioned object, a closed code set,
and retryability as a property of the code."""

from __future__ import annotations

import io
import json

import pytest

from executor import PROTOCOL_VERSION
from executor.envelope import (
    RETRYABLE_CODES,
    ErrorCode,
    ExecutorError,
    emit_failure,
    emit_success,
    error_json,
)


def test_protocol_version_starts_at_one() -> None:
    """
    Given the executor package
    When its protocol version is read
    Then it is "1".

    The envelope is versioned from birth, so a consumer never has to guess
    which shape it is holding.
    """
    assert PROTOCOL_VERSION == "1"


def test_success_envelope_carries_protocol_ok_data_and_null_error() -> None:
    """
    Given a success payload
    When emit_success writes it
    Then the envelope is {protocol, ok: true, data, error: null} and exit 0.
    """
    out = io.StringIO()

    code = emit_success({"verb": "start"}, out)

    assert code == 0
    assert json.loads(out.getvalue()) == {
        "protocol": "1",
        "ok": True,
        "data": {"verb": "start"},
        "error": None,
    }


def test_failure_envelope_carries_code_message_and_retryable() -> None:
    """
    Given a transport failure
    When emit_failure writes it
    Then the envelope's error is {code, message, retryable: true}, data is
    null, and the exit code is 1.
    """
    out = io.StringIO()

    code = emit_failure(ExecutorError(ErrorCode.TRACKER_SUBPROCESS, "facade unreachable"), out)

    assert code == 1
    assert json.loads(out.getvalue()) == {
        "protocol": "1",
        "ok": False,
        "data": None,
        "error": {
            "code": "E_TRACKER_SUBPROCESS",
            "message": "facade unreachable",
            "retryable": True,
        },
    }


def test_error_data_is_omitted_when_empty_and_present_when_not() -> None:
    """
    Given two errors, one with detail and one without
    When each is rendered
    Then only the one with detail carries a `data` key.

    D11 marks `data` optional; an empty object reads as "there were details"
    to a consumer that only checks for the key.
    """
    bare = error_json(ExecutorError(ErrorCode.NO_OPEN_PR, "no PR"))
    detailed = error_json(ExecutorError(ErrorCode.BUDGET_EXHAUSTED, "spent", {"budget": 2}))

    assert "data" not in bare
    assert detailed["data"] == {"budget": 2}


def test_the_code_set_is_closed() -> None:
    """
    Given the ErrorCode enum
    When its members are listed
    Then they are D11's seven codes plus the two documented extensions.

    Pins the closed set: a new code is a contract change, not an
    implementation detail. E_USAGE and E_INTERNAL are extensions D11 does not
    enumerate — argv faults and the never-a-traceback backstop need a code
    too, and both are recorded as such in `ErrorCode`'s docstring.
    """
    assert {str(code) for code in ErrorCode} == {
        "E_TRACKER_SUBPROCESS",
        "E_RUNTIME_SUBPROCESS",
        "E_RUNTIME_ENVELOPE",
        "E_SYNC_FAILED",
        "E_ITEM_PARKED",
        "E_NO_OPEN_PR",
        "E_BUDGET_EXHAUSTED",
        "E_USAGE",
        "E_INTERNAL",
    }


@pytest.mark.parametrize(
    ("code", "retryable"),
    [
        (ErrorCode.TRACKER_SUBPROCESS, True),
        (ErrorCode.RUNTIME_SUBPROCESS, True),
        (ErrorCode.RUNTIME_ENVELOPE, True),
        (ErrorCode.SYNC_FAILED, True),
        (ErrorCode.ITEM_PARKED, False),
        (ErrorCode.NO_OPEN_PR, False),
        (ErrorCode.BUDGET_EXHAUSTED, False),
        (ErrorCode.USAGE, False),
        (ErrorCode.INTERNAL, False),
    ],
)
def test_retryability_is_a_property_of_the_code(code: ErrorCode, retryable: bool) -> None:
    """
    Given each code in the closed set
    When its retryability is read
    Then transport failures are retryable and contract refusals are not.

    Pins that no call site chooses this: two sites raising the same code
    cannot disagree about whether a retry is worth making.
    """
    assert ExecutorError(code, "x").retryable is retryable
    assert (code in RETRYABLE_CODES) is retryable
