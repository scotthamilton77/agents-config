"""S9T1-A2: one envelope per invocation, and no path that answers with a
traceback."""

from __future__ import annotations

import io
import json

import pytest

from executor.cli import main
from executor.envelope import ErrorCode, ExecutorError
from executor.ports import StalenessVerdict
from executor.state import RunState
from tests.unit.fakes import FakeRuntime, FakeTracker, invoke, item, run_state


class _RaisingRuntime:
    """A runtime port whose fold read fails, standing in for an unreachable or
    broken `grind`."""

    def __init__(self, failure: Exception) -> None:
        self._failure = failure

    def state(self) -> RunState:
        raise self._failure

    def append(self, event_type: str, payload: object) -> None:  # noqa: ARG002
        raise AssertionError("nothing may be appended after the fold read failed")

    def staleness(self, max_age: str | None = None) -> StalenessVerdict:  # noqa: ARG002
        raise self._failure


def _envelope(argv: list[str]) -> tuple[int, dict[str, object]]:
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, out=out, err=err, runtime=FakeRuntime(run_state()), tracker=FakeTracker())
    return code, json.loads(out.getvalue())


def test_a_missing_verb_is_a_usage_envelope_listing_the_verbs() -> None:
    """
    Given no verb
    When the CLI runs
    Then one usage envelope comes back naming what may be run.
    """
    code, envelope = _envelope([])

    assert code == 1
    assert envelope["error"]["code"] == "E_USAGE"  # type: ignore[index]
    assert "start" in envelope["error"]["message"]  # type: ignore[index]


def test_a_malformed_flag_value_is_enveloped_rather_than_printed_as_usage() -> None:
    """
    Given a PR number that is not an integer
    When the CLI runs
    Then argparse's usage error arrives as a typed envelope on stdout.

    Pins that the parser raises rather than exiting: stdout stays exactly one
    JSON envelope even on a bad flag.
    """
    code, envelope = _envelope(["pr-opened", "it-1", "--pr", "forty-two"])

    assert code == 1
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "E_USAGE"  # type: ignore[index]


def test_an_unknown_item_is_refused_before_anything_is_enacted() -> None:
    """
    Given an item the fold does not hold
    When a command names it
    Then a usage envelope names the id and nothing is enacted.
    """
    runtime, tracker = FakeRuntime(run_state(item("it-1"))), FakeTracker()

    code, envelope = invoke(["start", "it-9"], runtime, tracker)

    assert code == 1
    assert "it-9" in envelope["error"]["message"]
    assert runtime.appended == []
    assert tracker.mutations == []


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            ExecutorError(ErrorCode.RUNTIME_SUBPROCESS, "grind exited 1"),
            "E_RUNTIME_SUBPROCESS",
        ),
        (
            ExecutorError(ErrorCode.RUNTIME_ENVELOPE, "unparseable reply"),
            "E_RUNTIME_ENVELOPE",
        ),
    ],
    ids=["subprocess", "envelope"],
)
def test_a_port_failure_reaches_stdout_as_its_own_typed_envelope(
    failure: ExecutorError, expected: str
) -> None:
    """
    Given a port that fails
    When a command runs
    Then the envelope carries that failure's code, retryable, on stdout.
    """
    out, err = io.StringIO(), io.StringIO()

    code = main(
        ["start", "it-1"],
        out=out,
        err=err,
        runtime=_RaisingRuntime(failure),
        tracker=FakeTracker(),
    )
    envelope = json.loads(out.getvalue())

    assert code == 1
    assert envelope["error"]["code"] == expected
    assert envelope["error"]["retryable"] is True


def test_an_unexpected_exception_becomes_a_typed_envelope_not_a_traceback() -> None:
    """
    Given a port raising something the executor never types
    When a command runs
    Then stdout still carries exactly one envelope, the traceback goes to
    stderr, and the code is E_INTERNAL.

    The backstop: an operator parsing stdout must never have to distinguish
    an envelope from a Python traceback.
    """
    out, err = io.StringIO(), io.StringIO()

    code = main(
        ["start", "it-1"],
        out=out,
        err=err,
        runtime=_RaisingRuntime(ValueError("boom")),
        tracker=FakeTracker(),
    )

    assert code == 1
    assert json.loads(out.getvalue())["error"]["code"] == "E_INTERNAL"
    assert "ValueError" in err.getvalue()


def test_stdout_carries_exactly_one_json_object_per_invocation() -> None:
    """
    Given a successful command
    When stdout is read
    Then it is one JSON object followed by a single newline.
    """
    out = io.StringIO()

    main(
        ["start", "it-1"],
        out=out,
        err=io.StringIO(),
        runtime=FakeRuntime(run_state(item("it-1"))),
        tracker=FakeTracker(),
    )

    assert out.getvalue().count("\n") == 1
    assert set(json.loads(out.getvalue())) == {"protocol", "ok", "data", "error"}
