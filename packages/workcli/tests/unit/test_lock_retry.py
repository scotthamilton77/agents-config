"""Lock-contention retry (spec test-plan item 7, locked decision 8).

Retryable = lock-contention stderr patterns or subprocess `TimeoutExpired`;
3 attempts total, injectable `sleep(0.5)` then `sleep(1.0)` between them;
exhaustion surfaces `E_LOCK_CONTENTION`. A non-retryable failure is not the
retry layer's concern to classify further -- it returns immediately so the
caller's own error-mapping table decides the specific code.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

import pytest

from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.retry import run_with_retry
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode, WorkError


def _recording_sleep() -> tuple[list[float], object]:
    calls: list[float] = []

    def sleep(seconds: float) -> None:
        calls.append(seconds)

    return calls, sleep


def test_two_lock_contention_failures_then_success_returns_success_with_two_sleeps():
    locked = BdResult(returncode=1, stdout="", stderr="database is locked")
    ok = BdResult(returncode=0, stdout="[]", stderr="")
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show",), locked),
            ScriptedStep(("show",), locked),
            ScriptedStep(("show",), ok),
        ]
    )
    sleep_calls, sleep = _recording_sleep()

    result = run_with_retry(runner, ["show", "x.1", "--json"], sleep=sleep)

    assert result is ok
    assert sleep_calls == [0.5, 1.0]
    assert len(runner.calls) == 3


def test_lock_contention_exhausting_all_attempts_raises_lock_contention_error():
    locked = BdResult(returncode=1, stdout="", stderr="database is locked")
    runner = ScriptedBdRunner(steps=[ScriptedStep(("show",), locked) for _ in range(3)])
    sleep_calls, sleep = _recording_sleep()

    with pytest.raises(WorkError) as exc_info:
        run_with_retry(runner, ["show", "x.1", "--json"], sleep=sleep)

    assert exc_info.value.code == ErrorCode.LOCK_CONTENTION
    assert sleep_calls == [0.5, 1.0]
    assert len(runner.calls) == 3


def test_non_retryable_failure_returns_immediately_with_zero_retries_and_zero_sleeps():
    not_found = BdResult(returncode=1, stdout="", stderr='no issue found matching "x.1"')
    runner = ScriptedBdRunner(steps=[ScriptedStep(("show",), not_found)])
    sleep_calls, sleep = _recording_sleep()

    result = run_with_retry(runner, ["show", "x.1", "--json"], sleep=sleep)

    assert result is not_found
    assert sleep_calls == []
    assert len(runner.calls) == 1


class _TimeoutThenSuccessRunner:
    """A minimal BdRunner double for the one branch ScriptedBdRunner's pinned
    shape can't express: a subprocess.TimeoutExpired raised instead of a
    BdResult returned (decision 8's other retryable trigger).
    """

    def __init__(self, success: BdResult) -> None:
        self._success = success
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str]) -> BdResult:
        self.calls.append(tuple(args))
        if len(self.calls) == 1:
            raise subprocess.TimeoutExpired(cmd=["bd", *args], timeout=60)
        return self._success


def test_timeout_expired_is_retried_like_lock_contention():
    ok = BdResult(returncode=0, stdout="[]", stderr="")
    runner = _TimeoutThenSuccessRunner(ok)
    sleep_calls, sleep = _recording_sleep()

    result = run_with_retry(runner, ["show", "x.1", "--json"], sleep=sleep)

    assert result is ok
    assert sleep_calls == [0.5]
    assert len(runner.calls) == 2
