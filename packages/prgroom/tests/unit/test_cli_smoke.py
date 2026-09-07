"""Smoke tests for the typer CLI root.

These pin the *user-facing contract*: every MVP verb is wired, discoverable via
``--help``, and has its own ``--help``; charter D13 ("prgroom is carved, not
finished") explicitly forbids building ``sweep``, so it is neither
discoverable nor a registered command. They are behavior tests at the CLI
boundary, not tautologies — a verb that is defined but not registered,
registered under the wrong name, or a forbidden verb that slips back onto the
surface, fails here.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
import typer
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

# Registered, but not grooming verbs: each takes no PR lock, reads and writes no
# grooming state, and the `run` aggregate never threads either.
NON_LIFECYCLE_VERBS = ["approve", "post-verdict"]

REGISTERED_VERBS = [*MVP_VERBS, *NON_LIFECYCLE_VERBS]


def test_help_exits_zero() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


@pytest.mark.parametrize("verb", REGISTERED_VERBS)
def test_help_lists_every_registered_verb(verb: str) -> None:
    result = runner.invoke(app, ["--help"])
    assert verb in result.output


@pytest.mark.parametrize("verb", REGISTERED_VERBS)
def test_each_verb_has_its_own_help(verb: str) -> None:
    result = runner.invoke(app, [verb, "--help"])
    assert result.exit_code == 0


def test_registered_commands_match_the_expected_set_exactly() -> None:
    # The tests above only check that each expected verb is present; an
    # unintended extra command (e.g. a stub reintroduced without updating
    # the roster) would still pass them. Comparing the actual registered set
    # catches that.
    click_app = typer.main.get_command(app)
    assert set(click_app.commands) == set(REGISTERED_VERBS)


# Every MVP verb above is wired for real; behavior is covered by the per-verb
# test_cli_*.py suites. Charter D13 ("prgroom is carved, not finished")
# explicitly forbids building ``sweep`` — it is not a command and must not
# become discoverable.


def test_sweep_is_not_registered() -> None:
    result = runner.invoke(app, ["--help"])
    assert "sweep" not in result.output


def test_sweep_is_rejected_as_unknown_command() -> None:
    # Absence from --help alone would also pass for a hidden-but-still-wired
    # command; invoking it directly proves Typer has no such command at all.
    result = runner.invoke(app, ["sweep", "octo/demo"])
    assert result.exit_code != 0
    assert "no such command" in result.output.lower()


def test_the_package_declares_exactly_one_runtime_dependency() -> None:
    # The App client signs and speaks HTTP through the stdlib and the existing
    # subprocess seam; a cryptography or HTTP library appearing here means one
    # of those went around its seam.
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    with pyproject.open("rb") as fh:
        assert tomllib.load(fh)["project"]["dependencies"] == ["typer"]
