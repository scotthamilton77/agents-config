"""The bd subprocess port — the fake's seam.

`BdRunner` is the one interface every contract test replaces with
`tests/fakes.ScriptedBdRunner`; `SubprocessBdRunner` is the sole
implementation that actually shells out to the real `bd` binary. It raises
`subprocess.TimeoutExpired` on its 60s deadline rather than catching it --
`adapters/bd/retry.py` is the layer that treats that as retryable
(decision 8).
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BdResult:
    returncode: int
    stdout: str
    stderr: str


class BdRunner(Protocol):
    def run(self, args: Sequence[str]) -> BdResult: ...  # pragma: no cover


class SubprocessBdRunner:
    """Drives the real bd binary. timeout=60s; TimeoutExpired is retryable (decision 8).

    Raising `subprocess.TimeoutExpired` on deadline is subprocess.run's own
    documented behavior -- this class does not catch it. `adapters/bd/retry.py`
    is the layer that treats it as a retryable signal.
    """

    def run(self, args: Sequence[str]) -> BdResult:
        completed = subprocess.run(
            ["bd", *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return BdResult(
            returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
        )
