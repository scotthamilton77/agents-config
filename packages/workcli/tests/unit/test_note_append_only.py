"""`work note` is append-only; `work update` refuses to clobber notes.

Two `note` calls concatenate via bd's `--append-notes`
flag, in order; no verb path may ever reach bd's bare replace flag `--notes`.
`--set-notes` on `update` is recognized by argparse (so it is never swallowed
as a generic `E_USAGE` unknown-flag error) but the verb handler rejects it
with the named `E_FIELD_CLOBBER_GUARD` code before any bd call --
notes only ever move through `work note`. The flag is also
suppressed from `--help` (rationale at its `add_argument` site in `cli.py`).
"""

from __future__ import annotations

import pytest

from tests.conftest import run_cli
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.cli import main
from workcli.envelope import ErrorCode


def test_two_note_calls_send_two_append_notes_invocations_in_order():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("update",), BdResult(returncode=0, stdout="", stderr="")),
            ScriptedStep(("update",), BdResult(returncode=0, stdout="", stderr="")),
        ]
    )

    first_exit = main(["note", "x.1", "hello"], runner=runner)
    second_exit = main(["note", "x.1", "world"], runner=runner)

    assert first_exit == 0
    assert second_exit == 0
    assert runner.calls == [
        ("update", "x.1", "--append-notes", "hello"),
        ("update", "x.1", "--append-notes", "world"),
    ]
    # No call anywhere ever carries the bare replace flag.
    assert all("--notes" not in call for call in runner.calls)


def test_note_not_found_maps_to_not_found_envelope():
    exit_code, envelope, _ = run_cli(
        ["note", "bogus-id", "hello"],
        steps=[
            ScriptedStep(
                ("update",),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "bogus-id"\n'),
            )
        ],
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.NOT_FOUND)


def test_update_set_notes_yields_field_clobber_guard_not_generic_usage():
    exit_code, envelope, _ = run_cli(["update", "x.1", "--set-notes", "sneaky"], steps=[])

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.FIELD_CLOBBER_GUARD)


def test_update_help_does_not_advertise_set_notes(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc_info:
        main(["update", "--help"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "--set-notes" not in captured.out
    assert "--set-title" in captured.out
