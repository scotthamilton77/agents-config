"""`update` (replace-semantics fields), `close` (batch + disposition), `reopen`.

`update` never moves status (lifecycle verbs own that -- no status flag
exists at all on this subparser) and requires at least one `--set-*` flag.
`close --disposition` is one batch `bd close` call followed by one
`--append-notes` call per id, in that order (orchestrator ruling: `bd close
--reason` lands in the wrong field; the disposition text is an appended
note), then the close-walk's parent probe (one `bd show` of the closed ids;
walk *behavior* is state-tested in `test_close_walk.py`).
`reopen` is a single id, single bd call.
"""

from __future__ import annotations

import json

from tests.conftest import run_cli, run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode

_OK = BdResult(returncode=0, stdout="", stderr="")


def _parentless_show_result(*ids: str) -> BdResult:
    """A `bd show` result for the walk's parent probe: closed, parentless items."""
    raw = [
        {
            "id": item_id,
            "title": "T",
            "issue_type": "task",
            "status": "closed",
            "priority": 2,
            "labels": [],
            "parent": None,
            "dependencies": [],
            "dependents": [],
        }
        for item_id in ids
    ]
    return BdResult(returncode=0, stdout=json.dumps(raw), stderr="")


def test_update_set_title_and_set_priority_sends_one_bd_call_with_both_flags():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("update",), _OK)])

    exit_code, _, _ = run_cli_with_runner(
        ["update", "x.1", "--set-title", "New title", "--set-priority", "P1"], runner
    )

    assert exit_code == 0
    assert runner.calls == [
        ("update", "x.1", "--title", "New title", "--priority", "P1"),
    ]


def test_update_with_no_set_flags_yields_usage_envelope():
    exit_code, envelope, _ = run_cli(["update", "x.1"], steps=[])

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)


def test_update_not_found_maps_to_not_found_envelope():
    exit_code, envelope, _ = run_cli(
        ["update", "bogus-id", "--set-title", "T"],
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


def test_close_with_disposition_closes_then_appends_one_note_per_id_in_order():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("close",), _OK),
            ScriptedStep(("update",), _OK),
            ScriptedStep(("update",), _OK),
            ScriptedStep(("show",), _parentless_show_result("a.1", "a.2")),
        ]
    )

    exit_code, _, _ = run_cli_with_runner(
        ["close", "a.1", "a.2", "--disposition", "done, wontfix elsewhere"], runner
    )

    assert exit_code == 0
    assert runner.calls == [
        ("close", "a.1", "a.2"),
        ("update", "a.1", "--append-notes", "done, wontfix elsewhere"),
        ("update", "a.2", "--append-notes", "done, wontfix elsewhere"),
        ("show", "a.1", "a.2", "--json"),
    ]


def test_close_without_disposition_sends_close_then_one_parent_probe():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("close",), _OK),
            ScriptedStep(("show",), _parentless_show_result("a.1")),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["close", "a.1"], runner)

    assert exit_code == 0
    # Nothing walked (parentless) -- the envelope keeps its legacy None shape.
    assert envelope["data"] is None
    assert runner.calls == [("close", "a.1"), ("show", "a.1", "--json")]


def test_close_not_found_maps_to_not_found_envelope():
    exit_code, envelope, _ = run_cli(
        ["close", "bogus-id"],
        steps=[
            ScriptedStep(
                ("close",),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "bogus-id"\n'),
            )
        ],
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.NOT_FOUND)


def test_reopen_sends_exactly_one_bd_call_with_the_id():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("reopen",), _OK)])

    exit_code, _, _ = run_cli_with_runner(["reopen", "a.1"], runner)

    assert exit_code == 0
    assert runner.calls == [("reopen", "a.1")]


def test_reopen_not_found_maps_to_not_found_envelope():
    exit_code, envelope, _ = run_cli(
        ["reopen", "bogus-id"],
        steps=[
            ScriptedStep(
                ("reopen",),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "bogus-id"\n'),
            )
        ],
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.NOT_FOUND)
