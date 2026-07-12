"""Bounded backoff around a single bd invocation (locked decision 8).

Retryable = a lock-contention stderr pattern, or subprocess `TimeoutExpired`.
3 attempts total; injectable `sleep(0.5)` then `sleep(1.0)` between them.
Exhaustion surfaces the code matching the *last* retryable failure: a run of
timeouts raises `WorkError(E_TIMEOUT)`, lock contention raises
`WorkError(E_LOCK_CONTENTION)` -- so repeated timeouts don't masquerade as
lock contention to callers. A non-retryable failure is returned as-is on the
first attempt -- classifying *which* error it is belongs to the adapter's
error-mapping table (`adapters/bd/backend.py`), not to this module.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence

from workcli.adapters.bd.runner import BdResult, BdRunner
from workcli.envelope import ErrorCode, JsonValue, WorkError

_ATTEMPTS = 3
_BACKOFFS = (0.5, 1.0)

_TIMEOUT_MESSAGE = "bd timed out; the operation may have partially applied — run `work reconcile`"

_RETRYABLE_STDERR_SUBSTRINGS = (
    "database is locked",
    "lock contention",
    "resource temporarily unavailable",
    "connection refused",
)


def _is_retryable_stderr(stderr: str) -> bool:
    return any(pattern in stderr for pattern in _RETRYABLE_STDERR_SUBSTRINGS)


def run_with_retry(
    runner: BdRunner,
    args: Sequence[str],
    *,
    sleep: Callable[[float], None],
    retry_on_timeout: bool = True,
) -> BdResult:
    last_result: BdResult | None = None
    last_failure_was_timeout = False
    for attempt in range(_ATTEMPTS):
        try:
            result = runner.run(args)
        except subprocess.TimeoutExpired as exc:
            if not retry_on_timeout:
                # Non-idempotent mutation (create/append_note): re-running a
                # possibly-completed call would duplicate it, so a timeout
                # surfaces immediately rather than retrying blind.
                raise WorkError(
                    ErrorCode.TIMEOUT,
                    _TIMEOUT_MESSAGE,
                    detail={"argv": list(args)},
                ) from exc
            last_result = BdResult(returncode=124, stdout="", stderr=str(exc))
            last_failure_was_timeout = True
        else:
            if result.returncode == 0 or not _is_retryable_stderr(result.stderr):
                return result
            last_result = result
            last_failure_was_timeout = False

        if attempt < _ATTEMPTS - 1:
            sleep(_BACKOFFS[attempt])

    if last_failure_was_timeout:
        # Every retry timed out: surface E_TIMEOUT so repeated timeouts are not
        # misreported to callers as lock contention.
        raise WorkError(
            ErrorCode.TIMEOUT,
            _TIMEOUT_MESSAGE,
            detail={"argv": list(args)},
        )

    detail: dict[str, JsonValue] = {
        "argv": list(args),
        "stderr": last_result.stderr if last_result is not None else "",
    }
    raise WorkError(
        ErrorCode.LOCK_CONTENTION, "bd lock contention exhausted all retry attempts", detail=detail
    )
