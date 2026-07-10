"""Shared pytest fixtures and helpers for the workcli test suite."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from io import StringIO

from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.cli import main
from workcli.envelope import JsonValue


def run_cli(
    argv: Sequence[str],
    steps: Sequence[ScriptedStep],
    *,
    sleep: Callable[[float], None] | None = None,
) -> tuple[int, dict[str, JsonValue], str]:
    """Invoke `main()` against a `ScriptedBdRunner`, capturing stdout/stderr.

    Returns ``(exit_code, envelope, stderr_text)``. Parsing the entire
    captured stdout as one JSON value enforces the "exactly one envelope"
    invariant implicitly: any extra output on stdout fails the `json.loads`
    call with a clear error instead of silently reading the first line.

    No verb is wired to a `Backend` yet (Task 2) -- `steps` is accepted now
    so Tasks 3-5 write pure behavioral tests (verb in, envelope + call log
    out) without touching this helper again.
    """
    out = StringIO()
    err = StringIO()
    runner = ScriptedBdRunner(steps=list(steps))
    exit_code = main(argv, runner=runner, out=out, err=err, sleep=sleep)
    envelope: dict[str, JsonValue] = json.loads(out.getvalue())
    return exit_code, envelope, err.getvalue()
