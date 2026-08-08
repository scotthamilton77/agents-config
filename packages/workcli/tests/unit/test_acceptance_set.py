"""Correcting acceptance criteria after create -- and what that costs.

The criteria are the termination condition a claim is checked against, so the
one thing this verb must never be is a silent replace: criteria rewritten to
match whatever was built let a check pass because the contract moved rather
than because the work met it. Three properties carry that, and they are what
these tests hold.

- The previous criteria stay recoverable. They are quoted into a note, so
  whoever later checks a claim can see the contract moved and what it was.
- The trail is written FIRST. A failure between the two writes can then only
  leave a trail without a change, never a change without a trail -- and the
  quote is what tells the two apart, because criteria that still equal it are
  criteria the replacement never reached.
- Once anybody has started, the change needs a stated reason, and the note
  says work was underway. Refusing outright was the alternative, and it is
  worse: `release` is one call away and leaves no trace at all, so the refusal
  would convert a recorded mid-flight change into an unrecorded one.

`update` is deliberately not a route to any of this: it recognises
`--set-acceptance` only to refuse it by name.
"""

from __future__ import annotations

import json
from argparse import Namespace
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from tests.conftest import run_cli, run_cli_with_runner
from tests.fake_backend import FakeBackend, ReadOnlyFakeBackend
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.cli import main
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.verbs.acceptance import (
    FIRST_SET_MARKER,
    QUOTE_PREFIX,
    RESTATED_MARKER,
    acceptance,
)

_NOW = datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC)
_ISO = _NOW.isoformat()
_OLD = "AC1 the item reports the criteria it was created with."
_NEW = "AC1 the item reports the criteria it now carries."


def _args(item_id: str, text: str, *, why: str | None = None) -> Namespace:
    return Namespace(action="set", id=item_id, text=text, why=why, now=lambda: _NOW)


def _quoted(text: str) -> list[str]:
    return [f"{QUOTE_PREFIX}{line}" for line in text.splitlines()]


# -- the correction itself ----------------------------------------------------


def test_the_criteria_an_item_was_created_with_can_be_corrected() -> None:
    # The whole gap in one assertion: before this verb, the criteria were
    # settable exactly once and a typo had no repair short of recreating.
    backend = FakeBackend().add("w1", acceptance=_OLD)

    data = acceptance(backend, _args("w1", _NEW))

    assert backend.acceptance_of("w1") == _NEW
    assert data == {"id": "w1", "acceptance": _NEW, "previous": _OLD, "status": "open"}


def test_the_previous_criteria_survive_the_change_as_a_quoted_note() -> None:
    backend = FakeBackend().add("w1", acceptance=_OLD)

    acceptance(backend, _args("w1", _NEW))

    assert backend.note_lines("w1") == [f"{RESTATED_MARKER} {_ISO}", *_quoted(_OLD)]


def test_multi_line_criteria_are_quoted_line_by_line() -> None:
    # Every line carries the quote prefix, so a later note appended underneath
    # can never be read as part of the criteria this one preserved.
    previous = "AC1 the first thing.\nAC2 the second thing."
    backend = FakeBackend().add("w1", acceptance=previous)

    acceptance(backend, _args("w1", _NEW))

    assert backend.note_lines("w1") == [
        f"{RESTATED_MARKER} {_ISO}",
        f"{QUOTE_PREFIX}AC1 the first thing.",
        f"{QUOTE_PREFIX}AC2 the second thing.",
    ]


def test_an_item_that_had_no_criteria_records_a_first_set_and_quotes_nothing() -> None:
    # Nothing was superseded, so there is nothing to preserve and the marker
    # says which of the two happened rather than leaving a reader to infer it
    # from an absent quote.
    backend = FakeBackend().add("w1", acceptance="")

    data = acceptance(backend, _args("w1", _NEW))

    assert backend.note_lines("w1") == [f"{FIRST_SET_MARKER} {_ISO}"]
    assert data == {"id": "w1", "acceptance": _NEW, "previous": None, "status": "open"}


def test_a_reason_is_recorded_when_one_is_given() -> None:
    backend = FakeBackend().add("w1", acceptance=_OLD)

    acceptance(backend, _args("w1", _NEW, why="AC1 named the wrong verb"))

    assert backend.note_lines("w1")[0] == f"{RESTATED_MARKER} {_ISO}: AC1 named the wrong verb"


def test_setting_the_criteria_that_are_already_there_writes_nothing() -> None:
    # Replay safety: a re-issued call converges on the state that is already
    # there rather than minting a second trail entry for a change nobody made.
    backend = FakeBackend().add("w1", acceptance=_OLD)

    data = acceptance(backend, _args("w1", _OLD))

    assert backend.note_lines("w1") == []
    assert data == {"id": "w1", "acceptance": _OLD, "previous": _OLD, "status": "open"}


@pytest.mark.parametrize("text", ["", "   ", "\n"], ids=["empty", "spaces", "newline"])
def test_blank_criteria_are_refused_rather_than_emptying_the_contract(text: str) -> None:
    # An unset shell variable expands to exactly this, and deleting the
    # criteria a claim is checked against is not what anyone typing a
    # correction means -- the same reason `--set-parent` refuses an empty id.
    backend = FakeBackend().add("w1", acceptance=_OLD)

    with pytest.raises(WorkError) as exc_info:
        acceptance(backend, _args("w1", text))

    assert exc_info.value.code is ErrorCode.USAGE
    assert backend.acceptance_of("w1") == _OLD


@pytest.mark.parametrize(
    "why", ["", "   ", "line one\nline two"], ids=["empty", "spaces", "multi-line"]
)
def test_a_blank_or_multi_line_reason_is_refused(why: str) -> None:
    # The reason travels on the marker's own line; a second line would land
    # unquoted beside the criteria the note preserves.
    backend = FakeBackend().add("w1", acceptance=_OLD, status="in_progress")

    with pytest.raises(WorkError) as exc_info:
        acceptance(backend, _args("w1", _NEW, why=why))

    assert exc_info.value.code is ErrorCode.USAGE
    assert backend.acceptance_of("w1") == _OLD


def test_a_missing_item_is_reported_before_anything_is_written() -> None:
    backend = FakeBackend()

    with pytest.raises(WorkError) as exc_info:
        acceptance(backend, _args("nope", _NEW))

    assert exc_info.value.code is ErrorCode.NOT_FOUND


# -- the gate once work has started -------------------------------------------


@pytest.mark.parametrize("status", ["in_progress", "blocked", "closed"])
def test_a_started_item_refuses_a_restatement_that_states_no_reason(status: str) -> None:
    # `blocked` is a parked item: work that started and stuck, which is the
    # same case as a claim in hand. The refusal is proved to write nothing at
    # all rather than to leave a half-applied change behind.
    backend = ReadOnlyFakeBackend().add("w1", acceptance=_OLD, status=status)

    with pytest.raises(WorkError) as exc_info:
        acceptance(backend, _args("w1", _NEW))

    assert exc_info.value.code is ErrorCode.FIELD_CLOBBER_GUARD
    assert exc_info.value.detail == {"field": "acceptance", "status": status}
    assert "--why" in exc_info.value.message


@pytest.mark.parametrize("status", ["in_progress", "blocked", "closed"])
def test_a_started_item_takes_a_stated_restatement_and_the_note_says_so(status: str) -> None:
    backend = FakeBackend().add("w1", acceptance=_OLD, status=status)

    data = acceptance(backend, _args("w1", _NEW, why="the spec moved under it"))

    assert backend.acceptance_of("w1") == _NEW
    assert backend.note_lines("w1") == [
        f"{RESTATED_MARKER} {_ISO} while {status}: the spec moved under it",
        *_quoted(_OLD),
    ]
    assert data["status"] == status


@pytest.mark.parametrize("status", ["open", "deferred"])
def test_an_item_nobody_has_started_needs_no_reason(status: str) -> None:
    # Sharpening criteria before anyone picks the work up is the ordinary
    # case this verb exists for; ceremony there buys nothing.
    backend = FakeBackend().add("w1", acceptance=_OLD, status=status)

    acceptance(backend, _args("w1", _NEW))

    assert backend.acceptance_of("w1") == _NEW
    assert backend.note_lines("w1")[0] == f"{RESTATED_MARKER} {_ISO}"


# -- the order the two writes go in -------------------------------------------


def _raw_item(acceptance_criteria: str | None) -> dict[str, JsonValue]:
    raw: dict[str, JsonValue] = {
        "id": "x.1",
        "title": "T",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "labels": [],
        "dependencies": [],
        "dependents": [],
    }
    if acceptance_criteria is not None:
        raw["acceptance_criteria"] = acceptance_criteria
    return raw


def _show_step(acceptance_criteria: str | None) -> ScriptedStep:
    return ScriptedStep(
        ("show",),
        BdResult(returncode=0, stdout=json.dumps([_raw_item(acceptance_criteria)]), stderr=""),
    )


def _ok_step() -> ScriptedStep:
    return ScriptedStep(("update",), BdResult(returncode=0, stdout="", stderr=""))


def _writes(calls: Sequence[tuple[str, ...]]) -> list[tuple[str, ...]]:
    return [call for call in calls if call[0] == "update"]


def test_the_trail_is_written_before_the_criteria_change() -> None:
    """
    Given an item whose criteria are about to be replaced
    When the verb runs
    Then the note preserving them reaches the backend before the replacement.

    The order is the whole integrity argument. Reversed, a failure between the
    two writes would leave criteria that moved with nothing recording it --
    exactly the state the trail exists to make impossible.
    """
    runner = ScriptedBdRunner(steps=[_show_step(_OLD), _ok_step(), _ok_step()])

    exit_code, envelope, _ = run_cli_with_runner(["acceptance", "set", "x.1", _NEW], runner)

    assert exit_code == 0, envelope
    trail, change = _writes(runner.calls)
    assert "--append-notes" in trail
    assert _OLD in " ".join(trail)
    assert change == ("update", "x.1", "--acceptance", _NEW)


def test_a_failed_replacement_leaves_a_trail_whose_quote_still_matches_the_item() -> None:
    """
    Given a backend that accepts the note and then refuses the replacement
    When the verb runs
    Then the trail is there, the criteria are untouched, and the two agree.

    The half-failed write is legible without extra bookkeeping: the note
    quotes what it superseded, so criteria still equal to the quote are
    criteria the replacement never reached.
    """

    class _ReplacementFails(FakeBackend):
        def set_acceptance(self, _item_id: str, _text: str) -> None:
            raise WorkError(ErrorCode.TIMEOUT, "the tracker did not answer")

    backend = _ReplacementFails().add("w1", acceptance=_OLD)

    with pytest.raises(WorkError) as exc_info:
        acceptance(backend, _args("w1", _NEW))

    assert exc_info.value.code is ErrorCode.TIMEOUT
    assert backend.note_lines("w1") == [f"{RESTATED_MARKER} {_ISO}", *_quoted(_OLD)]
    assert backend.acceptance_of("w1") == _OLD


# -- the CLI surface ----------------------------------------------------------


def test_the_verb_is_reachable_from_the_command_line() -> None:
    exit_code, envelope, _ = run_cli(
        ["acceptance", "set", "x.1", _NEW, "--why", "AC1 named the wrong verb"],
        [_show_step(_OLD), _ok_step(), _ok_step()],
    )

    assert exit_code == 0
    assert envelope["data"] == {
        "id": "x.1",
        "acceptance": _NEW,
        "previous": _OLD,
        "status": "open",
    }


def test_update_refuses_to_move_the_criteria_and_names_the_verb_that_does() -> None:
    # An empty script: a backend call on this path would exhaust it and fail
    # loudly, which is how "refused before any write" is proved here.
    exit_code, envelope, _ = run_cli(["update", "x.1", "--set-acceptance", _NEW], steps=[])

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.FIELD_CLOBBER_GUARD)
    assert "acceptance set" in str(error["message"])


def test_update_help_does_not_advertise_set_acceptance(capsys: pytest.CaptureFixture[str]) -> None:
    # A tripwire, not an advertised option: naming it in --help would invite
    # the attempt it exists to reject.
    with pytest.raises(SystemExit) as exc_info:
        main(["update", "--help"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "--set-acceptance" not in captured.out
    assert "--set-title" in captured.out
