"""The pairing layer validates its own inputs.

`build_plan` is the seam a future dispatcher calls directly, not only what the
argument parser reaches. Its required-argument checks therefore have to hold
without argparse's `required=True` standing behind them — otherwise the layer's
guarantees would only be true of one caller.
"""

from __future__ import annotations

import pytest

from executor.envelope import ErrorCode, ExecutorError
from executor.pairing import VerbArgs, build_plan
from tests.unit.fakes import item, run_state

_STATE = run_state(item("it-1", status="pr-open", pr=7))


@pytest.mark.parametrize(
    ("verb", "args", "missing"),
    [
        ("park", VerbArgs(item="it-1"), "--reason"),
        ("abandon", VerbArgs(item="it-1"), "--pr"),
        ("pr-opened", VerbArgs(item="it-1"), "--pr"),
        ("pr-closed", VerbArgs(item="it-1"), "--pr"),
        ("pr-closed", VerbArgs(item="it-1", pr=7, reason="stale"), "--next"),
        ("pr-closed", VerbArgs(item="it-1", pr=7, next_status="queued"), "--reason"),
        ("merged", VerbArgs(item="it-1"), "--sha"),
    ],
    ids=[
        "park-reason",
        "abandon-pr",
        "pr-opened-pr",
        "pr-closed-pr",
        "pr-closed-next",
        "pr-closed-reason",
        "merged-sha",
    ],
)
def test_a_row_missing_a_required_argument_is_refused_by_name(
    verb: str, args: VerbArgs, missing: str
) -> None:
    """
    Given a plan request missing one of its row's required arguments
    When the plan is built
    Then E_USAGE names the missing flag.
    """
    with pytest.raises(ExecutorError) as raised:
        build_plan(verb, args, _STATE)

    assert raised.value.code is ErrorCode.USAGE
    assert missing in raised.value.message


def test_a_verb_the_table_does_not_hold_is_refused() -> None:
    """
    Given a verb with no pairing row
    When a plan is built for it
    Then E_USAGE names the verb.

    The pairing universe is closed at this layer too, not only at the parser:
    a caller reaching past argparse cannot invent a pairing.
    """
    with pytest.raises(ExecutorError) as raised:
        build_plan("promote", VerbArgs(item="it-1"), _STATE)

    assert raised.value.code is ErrorCode.USAGE
    assert "promote" in raised.value.message
