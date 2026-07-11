"""Bounded backoff around a single bd invocation (locked decision 8).

Retryable = a lock-contention stderr pattern, or subprocess `TimeoutExpired`.
3 attempts total; injectable `sleep(0.5)` then `sleep(1.0)` between them.
Exhaustion raises `WorkError(E_LOCK_CONTENTION)`. A non-retryable failure is
returned as-is on the first attempt -- classifying *which* error it is
belongs to the adapter's error-mapping table (`adapters/bd/backend.py`), not
to this module.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence

from workcli.adapters.bd.runner import BdResult, BdRunner
from workcli.envelope import ErrorCode, JsonValue, WorkError

_ATTEMPTS = 3
_BACKOFFS = (0.5, 1.0)

_RETRYABLE_STDERR_SUBSTRINGS = (
    "database is locked",
    "lock contention",
    "resource temporarily unavailable",
    "connection refused",
)


def _is_retryable_stderr(stderr: str) -> bool:
    return any(pattern in stderr for pattern in _RETRYABLE_STDERR_SUBSTRINGS)


def run_with_retry(
    runner: BdRunner, args: Sequence[str], *, sleep: Callable[[float], None]
) -> BdResult:
    last_result: BdResult | None = None
    for attempt in range(_ATTEMPTS):
        try:
            result = runner.run(args)
        except subprocess.TimeoutExpired as exc:
            last_result = BdResult(returncode=124, stdout="", stderr=str(exc))
        else:
            if result.returncode == 0 or not _is_retryable_stderr(result.stderr):
                return result
            last_result = result

        if attempt < _ATTEMPTS - 1:
            sleep(_BACKOFFS[attempt])

    detail: dict[str, JsonValue] = {
        "argv": list(args),
        "stderr": last_result.stderr if last_result is not None else "",
    }
    raise WorkError(
        ErrorCode.LOCK_CONTENTION, "bd lock contention exhausted all retry attempts", detail=detail
    )
