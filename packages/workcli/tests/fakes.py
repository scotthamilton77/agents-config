"""ScriptedBdRunner: the fake `BdRunner` every contract test drives bd through.

No live Dolt, no real subprocess -- ever. Every workcli behavioral test
scripts a sequence of `BdResult`s and asserts against `.calls`, the full
argv the code under test actually sent to "bd".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from workcli.adapters.bd.runner import BdResult


@dataclass
class ScriptedStep:
    expect_prefix: tuple[str, ...]  # e.g. ("show",) — matched against args[:len(prefix)]
    result: BdResult


@dataclass
class ScriptedBdRunner:
    """Feeds scripted BdResults in order; records every call's full args.

    - `.calls`: every invocation, in order (the assertion surface for what
      reached bd, and in what order).
    - A mismatch between the next step's `expect_prefix` and the actual args
      is a loud test failure (diff of expected vs actual), never a silent
      skip.
    - Running past the script is a loud test failure, never a silent no-op.
    """

    steps: list[ScriptedStep]
    calls: list[tuple[str, ...]] = field(default_factory=list)
    _next: int = field(default=0, init=False, repr=False)

    def run(self, args: Sequence[str]) -> BdResult:
        args_tuple = tuple(args)
        self.calls.append(args_tuple)

        if self._next >= len(self.steps):
            raise AssertionError(
                f"ScriptedBdRunner script exhausted: no step left for call {args_tuple!r} "
                f"(all calls so far: {self.calls!r})"
            )

        step = self.steps[self._next]
        actual_prefix = args_tuple[: len(step.expect_prefix)]
        if actual_prefix != step.expect_prefix:
            raise AssertionError(
                f"ScriptedBdRunner step {self._next}: expected args to start with "
                f"{step.expect_prefix!r}, got {actual_prefix!r} (full args: {args_tuple!r})"
            )

        self._next += 1
        return step.result
