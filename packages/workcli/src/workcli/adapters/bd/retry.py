"""Bounded backoff around a single bd invocation.

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
from workcli.envelope import ErrorCode, WorkError

_ATTEMPTS = 3
_BACKOFFS = (0.5, 1.0)

# States the fact and stops there. What a caller should RUN about it names a
# `work` verb, which is the CLI's word and not this adapter's to spell: an
# adapter that spelled it would go stale the day the verb was renamed, and a
# second adapter would have to copy it to stay consistent. The CLI attaches
# its own recovery advice to this code on the way out.
_TIMEOUT_MESSAGE = "the backend did not respond in time; the operation may have partially applied"

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
    last_failure_was_timeout = False
    for attempt in range(_ATTEMPTS):
        try:
            result = runner.run(args)
        except subprocess.TimeoutExpired as exc:
            if not retry_on_timeout:
                # Non-idempotent mutation (create/append_note): re-running a
                # possibly-completed call would duplicate it, so a timeout
                # surfaces immediately rather than retrying blind.
                raise WorkError(ErrorCode.TIMEOUT, _TIMEOUT_MESSAGE) from exc
            last_failure_was_timeout = True
        else:
            if result.returncode == 0 or not _is_retryable_stderr(result.stderr):
                return result
            last_failure_was_timeout = False

        if attempt < _ATTEMPTS - 1:
            sleep(_BACKOFFS[attempt])

    if last_failure_was_timeout:
        # Every retry timed out: surface E_TIMEOUT so repeated timeouts are not
        # misreported to callers as lock contention.
        raise WorkError(ErrorCode.TIMEOUT, _TIMEOUT_MESSAGE)

    raise WorkError(
        ErrorCode.LOCK_CONTENTION,
        f"the backend stayed locked through all {_ATTEMPTS} attempts; retry when it is idle",
    )
