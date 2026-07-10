"""The bd subprocess port — the fake's seam.

This is a Task 1 scaffold: it exists only so `cli.main()`'s pinned signature
(`runner: BdRunner | None = None`) has a concrete type to import under
`mypy --strict`. `runner` is unused until Task 2, which implements
`SubprocessBdRunner.run()` (real subprocess dispatch, 60s timeout, retryable
`TimeoutExpired` per decision 8) and wires the retry loop around it. Task 2
extends this file — it does not recreate it.
"""

from __future__ import annotations

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
    """Drives the real bd binary. timeout=60s; TimeoutExpired is retryable (decision 8)."""
