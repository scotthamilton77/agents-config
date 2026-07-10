"""Shared pytest fixtures and helpers for the workcli test suite.

`run_cli` grows into the pinned `run_cli(argv, steps, *, sleep=None)` shape
once `tests/fakes.py`'s `ScriptedBdRunner` lands (Task 2); no verb reaches a
backend yet, so this scaffold only needs to invoke `main()` with captured
stdout/stderr and parse the single envelope it must produce.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from io import StringIO

from workcli.cli import main
from workcli.envelope import JsonValue


def run_cli(argv: Sequence[str]) -> tuple[int, dict[str, JsonValue], str]:
    """Invoke `main()`, capturing stdout/stderr.

    Returns ``(exit_code, envelope, stderr_text)``. Parsing the entire
    captured stdout as one JSON value enforces the "exactly one envelope"
    invariant implicitly: any extra output on stdout fails the `json.loads`
    call with a clear error instead of silently reading the first line.
    """
    out = StringIO()
    err = StringIO()
    exit_code = main(argv, out=out, err=err)
    envelope: dict[str, JsonValue] = json.loads(out.getvalue())
    return exit_code, envelope, err.getvalue()
