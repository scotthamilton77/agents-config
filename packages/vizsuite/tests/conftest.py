"""Shared pytest fixtures and helpers for the vizsuite test suite."""

from __future__ import annotations

import json
from collections.abc import Sequence
from io import StringIO

from vizsuite.adapters.gh.runner import GhRunner
from vizsuite.adapters.git.runner import GitRunner
from vizsuite.adapters.scc.runner import SccRunner
from vizsuite.cli import main
from vizsuite.envelope import JsonValue
from vizsuite.tracker.port import TrackerRunner


def run_cli(
    argv: Sequence[str],
    *,
    git_runner: GitRunner | None = None,
    gh_runner: GhRunner | None = None,
    scc_runner: SccRunner | None = None,
    tracker_runner: TrackerRunner | None = None,
) -> tuple[int, dict[str, JsonValue], str]:
    """Invoke `main()` capturing stdout/stderr; return `(exit_code, envelope, stderr)`.

    Parsing the entire captured stdout as one JSON value enforces the "exactly
    one envelope" invariant implicitly: any extra output on stdout fails the
    `json.loads` with a clear error instead of silently reading the first line.
    """
    out = StringIO()
    err = StringIO()
    exit_code = main(
        argv,
        git_runner=git_runner,
        gh_runner=gh_runner,
        scc_runner=scc_runner,
        tracker_runner=tracker_runner,
        out=out,
        err=err,
    )
    envelope: dict[str, JsonValue] = json.loads(out.getvalue())
    return exit_code, envelope, err.getvalue()
