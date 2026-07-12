"""Retry-safety fix (plan L4, 38o1v #3): `retry_on_timeout` on `run_with_retry`.

Non-idempotent bd mutations (`create`, `append_note`) must not retry a
subprocess timeout -- re-running a possibly-completed create/append would
duplicate it. `retry_on_timeout=False` turns a `TimeoutExpired` into an
immediate `E_TIMEOUT`, zero retries. Idempotent mutations and reads keep the
default `retry_on_timeout=True` and retry a timeout exactly like lock
contention. Lock-contention stderr retry is unchanged and independent of the
flag either way.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from io import StringIO

import pytest

from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.retry import run_with_retry
from workcli.adapters.bd.runner import BdResult
from workcli.cli import main
from workcli.envelope import ErrorCode, WorkError


def _recording_sleep() -> tuple[list[float], object]:
    calls: list[float] = []

    def sleep(seconds: float) -> None:
        calls.append(seconds)

    return calls, sleep


class _TimeoutOnceRunner:
    """BdRunner double: raises TimeoutExpired on the first call, then returns
    `then` on every subsequent call. ScriptedBdRunner's pinned shape can only
    return BdResults, never raise -- this mirrors test_lock_retry.py's own
    minimal double for the same reason.
    """

    def __init__(self, then: BdResult) -> None:
        self._then = then
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str]) -> BdResult:
        self.calls.append(tuple(args))
        if len(self.calls) == 1:
            raise subprocess.TimeoutExpired(cmd=["bd", *args], timeout=60)
        return self._then


class _AlwaysTimeoutRunner:
    """BdRunner double: raises TimeoutExpired on every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str]) -> BdResult:
        self.calls.append(tuple(args))
        raise subprocess.TimeoutExpired(cmd=["bd", *args], timeout=60)


def _invoke(argv: Sequence[str], runner: object, *, sleep=None):
    out = StringIO()
    err = StringIO()
    exit_code = main(list(argv), runner=runner, out=out, err=err, sleep=sleep)  # type: ignore[arg-type]
    envelope = json.loads(out.getvalue())
    return exit_code, envelope, err.getvalue()


# --- run_with_retry level ---------------------------------------------------


def test_retry_on_timeout_true_retries_a_timeout_and_succeeds():
    ok = BdResult(returncode=0, stdout="[]", stderr="")
    runner = _TimeoutOnceRunner(ok)
    sleep_calls, sleep = _recording_sleep()

    result = run_with_retry(runner, ["show", "x.1", "--json"], sleep=sleep, retry_on_timeout=True)

    assert result is ok
    assert sleep_calls == [0.5]
    assert len(runner.calls) == 2


def test_retry_on_timeout_false_raises_timeout_immediately_with_zero_retries():
    runner = _AlwaysTimeoutRunner()
    sleep_calls, sleep = _recording_sleep()

    with pytest.raises(WorkError) as exc_info:
        run_with_retry(
            runner, ["create", "--json", "--title", "T"], sleep=sleep, retry_on_timeout=False
        )

    assert exc_info.value.code == ErrorCode.TIMEOUT
    assert sleep_calls == []
    assert len(runner.calls) == 1


def test_retry_on_timeout_false_still_retries_lock_contention_stderr():
    locked = BdResult(returncode=1, stdout="", stderr="database is locked")
    ok = BdResult(returncode=0, stdout="", stderr="")
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("update",), locked), ScriptedStep(("update",), ok)]
    )
    sleep_calls, sleep = _recording_sleep()

    result = run_with_retry(
        runner, ["update", "x.1", "--append-notes", "hi"], sleep=sleep, retry_on_timeout=False
    )

    assert result is ok
    assert sleep_calls == [0.5]
    assert len(runner.calls) == 2


# --- end-to-end through main() ----------------------------------------------


def test_end_to_end_create_surfaces_timeout_without_retry():
    runner = _AlwaysTimeoutRunner()

    exit_code, envelope, _ = _invoke(["create", "--raw", "--title", "T"], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert error["code"] == str(ErrorCode.TIMEOUT)
    assert len(runner.calls) == 1


def test_end_to_end_note_surfaces_timeout_without_retry():
    runner = _AlwaysTimeoutRunner()

    exit_code, envelope, _ = _invoke(["note", "x.1", "hello"], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert error["code"] == str(ErrorCode.TIMEOUT)
    assert len(runner.calls) == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["close", "x.1"],
        ["update", "x.1", "--set-title", "T"],
        ["label", "add", "x.1", "foo"],
    ],
)
def test_end_to_end_idempotent_mutations_retry_a_timeout_then_succeed(argv: list[str]):
    ok = BdResult(returncode=0, stdout="", stderr="")
    runner = _TimeoutOnceRunner(ok)
    sleep_calls, sleep = _recording_sleep()

    exit_code, envelope, _ = _invoke(argv, runner, sleep=sleep)

    assert exit_code == 0
    assert envelope["ok"] is True
    assert sleep_calls == [0.5]
    assert len(runner.calls) == 2
