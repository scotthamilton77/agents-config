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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
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

    `bd_binary`/`cwd`/`env` are injectable and thread straight into
    `subprocess.run` -- `cwd=None`/`env=None` means "inherit", which is
    `subprocess.run`'s own documented default, so the default construction
    reproduces today's behavior exactly.
    """

    def __init__(
        self,
        *,
        bd_binary: str = "bd",
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._bd_binary = bd_binary
        self._cwd = cwd
        self._env = env

    def run(self, args: Sequence[str]) -> BdResult:
        completed = subprocess.run(
            [self._bd_binary, *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            cwd=self._cwd,
            env=dict(self._env) if self._env is not None else None,
        )
        return BdResult(
            returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
        )
