"""Smoke tests for the typer CLI root.

These pin the *user-facing contract* that every MVP verb is wired and discoverable
via ``--help`` (the foundation deliverable: skeletons exist and are listed). They
are behavior tests at the CLI boundary, not tautologies — a verb that is defined
but not registered, or registered under the wrong name, fails here.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from prgroom.cli import app

runner = CliRunner()

MVP_VERBS = [
    "poll",
    "cluster",
    "fix",
    "push",
    "rereview",
    "reply",
    "resolve",
    "resolve-escalated",
    "wait",
    "status",
    "run",
]


def test_help_exits_zero() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


@pytest.mark.parametrize("verb", MVP_VERBS)
def test_help_lists_every_mvp_verb(verb: str) -> None:
    result = runner.invoke(app, ["--help"])
    assert verb in result.output


@pytest.mark.parametrize("verb", MVP_VERBS)
def test_each_verb_has_its_own_help(verb: str) -> None:
    result = runner.invoke(app, [verb, "--help"])
    assert result.exit_code == 0


# Every MVP verb above is wired for real; behavior is covered by the per-verb
# test_cli_*.py suites. ``sweep`` is charter D13's explicit "never build"
# prohibition (9k9.215.6) — it is not a command and must not become discoverable.


def test_sweep_is_not_registered() -> None:
    result = runner.invoke(app, ["--help"])
    assert "sweep" not in result.output
