"""What a missing workspace tells the caller to do, and why it stops there.

The classification itself is pinned elsewhere (`test_drift_alarm.py` proves
this failure is a configuration failure rather than the drift alarm; the
integration suite proves the backend still emits the marker). What this file
pins is the advice, which is a separate decision and was wrong for a
different reason: it told the caller to create a workspace, and no verb of
this facade creates one.

Creating a workspace is not a facade operation and is not becoming one. It is
a directory-shaped act carrying storage-engine, remote and id-prefix
decisions the facade would have to take a position on, and it has no referent
at all for a backend whose items do not live in a directory. So the message
names the one remedy the facade can honour, states that setup happens
elsewhere, and points at the documentation that covers it.

Two assertions, because the message is only honest while its premise holds:
the message itself, and the verb inventory that makes its second clause true.
"""

from __future__ import annotations

import json
from io import StringIO

import pytest

from tests.conftest import run_cli
from tests.fakes import ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.cli import main

# The same capture the drift alarm keys on, restated here for the same reason
# it is restated there: this file asserts what the facade says back, and that
# claim should not go quiet because another file's copy was edited.
_MISSING_WORKSPACE_STDERR = (
    "Error: no beads database found\n"
    "Hint: run 'bd where' to inspect the resolved workspace, or 'bd init' to create a new "
    "database\n      or set BEADS_DIR to point to your .beads directory\n"
)

_EXPECTED_MESSAGE = (
    "no tracker workspace is configured for this directory; run from a directory that "
    "already has one. Creating a workspace is a setup step outside this tool, covered by "
    "your project's tracker setup documentation"
)


def test_the_missing_workspace_message_advises_only_what_the_facade_can_honour():
    # Pinned verbatim rather than by keyword: the defect this replaces was a
    # single clause of otherwise-correct advice, and a substring assertion
    # would have passed over it.
    _, envelope, _ = run_cli(
        ["show", "x.1"],
        steps=[
            ScriptedStep(
                ("show",),
                BdResult(returncode=1, stdout="", stderr=_MISSING_WORKSPACE_STDERR),
            )
        ],
    )

    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["message"] == _EXPECTED_MESSAGE


class _ExplodingRunner:
    """Fails the test the instant a bootstrap probe reaches the backend."""

    def run(self, args):
        raise AssertionError(f"a rejected verb must never reach the backend, got: {args!r}")


@pytest.mark.parametrize("spelling", ["init", "bootstrap", "new-workspace"])
def test_no_facade_verb_creates_a_workspace(spelling: str):
    # The premise of the message's second clause. Name-based, because a verb's
    # name is the whole surface a caller searching for one can see -- and if
    # one of these ever becomes a real subcommand, whatever it does, this goes
    # red and the message above has to be read again before it ships.
    out = StringIO()
    err = StringIO()

    exit_code = main([spelling], runner=_ExplodingRunner(), out=out, err=err)

    assert exit_code == 1
    envelope = json.loads(out.getvalue())
    assert envelope["error"]["code"] == "E_USAGE"
