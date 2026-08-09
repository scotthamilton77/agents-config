"""Smoke tests for the typer CLI root.

These pin the *user-facing contract*: every MVP verb is wired, discoverable via
``--help``, and has its own ``--help``; ``sweep`` (charter D13's explicit
"never build" prohibition) is neither discoverable nor a registered command.
They are behavior tests at the CLI boundary, not tautologies — a verb that is
defined but not registered, registered under the wrong name, or a forbidden
verb that slips back onto the surface, fails here.
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
# prohibition — it is not a command and must not become discoverable.


def test_sweep_is_not_registered() -> None:
    result = runner.invoke(app, ["--help"])
    assert "sweep" not in result.output


def test_sweep_is_rejected_as_unknown_command() -> None:
    # Absence from --help alone would also pass for a hidden-but-still-wired
    # command; invoking it directly proves Typer has no such command at all.
    result = runner.invoke(app, ["sweep", "octo/demo"])
    assert result.exit_code != 0
    assert "no such command" in result.output.lower()
