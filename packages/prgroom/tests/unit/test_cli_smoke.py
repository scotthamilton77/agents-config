"""Smoke tests for the typer CLI root.

These pin the *user-facing contract* that every MVP verb is wired and discoverable
via ``--help`` (the foundation deliverable: skeletons exist and are listed). They
are behavior tests at the CLI boundary, not tautologies — a verb that is defined
but not registered, or registered under the wrong name, fails here.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from prgroom.cli import SKELETON_EXIT_CODE, app

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
    "sweep",
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


# Each single-PR-arg skeleton verb invoked with a positional ref. resolve-escalated
# has a richer signature and is exercised separately below. ``poll`` is no longer a
# skeleton (8.9a wired it for real); ``status`` likewise (8.11); ``cluster`` + ``fix``
# (8.15); ``push`` + ``rereview`` + ``resolve`` (8.16); ``run`` + ``wait`` (8.10) — their
# behavior is covered by the per-verb test_cli_*.py suites. The remaining single-arg
# skeleton is ``reply``.
_WIRED_VERBS = {
    "resolve-escalated",
    "sweep",
    "poll",
    "status",
    "cluster",
    "fix",
    "push",
    "rereview",
    "resolve",
    "run",
    "wait",
}
_SINGLE_ARG_VERBS = [v for v in MVP_VERBS if v not in _WIRED_VERBS]


@pytest.mark.parametrize("verb", _SINGLE_ARG_VERBS)
def test_invoking_a_skeleton_verb_exits_nonzero_with_notice(verb: str) -> None:
    # A foundation skeleton must never silently succeed: every wired verb exits
    # non-zero and says so, so a caller can tell "not implemented" from "did
    # nothing". Parametrized over every verb to prove each is reachable, not just
    # registered in --help.
    result = runner.invoke(app, [verb, "123"])
    assert result.exit_code == SKELETON_EXIT_CODE
    assert "not yet implemented" in result.output


def test_sweep_skeleton_exits_nonzero() -> None:
    result = runner.invoke(app, ["sweep", "octo/demo"])
    assert result.exit_code == SKELETON_EXIT_CODE


def test_resolve_escalated_skeleton_accepts_its_required_options() -> None:
    # resolve-escalated has a richer signature (--as, --rationale); prove the
    # arg surface is wired before it reaches the skeleton body.
    result = runner.invoke(
        app, ["resolve-escalated", "123", "C_1", "--as", "fixed", "--rationale", "done"]
    )
    assert result.exit_code == SKELETON_EXIT_CODE
