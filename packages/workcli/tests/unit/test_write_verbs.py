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


def test_update_set_parent_sends_one_bd_call_carrying_bds_own_reparent_flag():
    # bd's `update --parent` REPLACES the parent-child edge (verified against
    # bd 1.0.3), so the move is one call and never passes through a state where
    # the item has two parents.
    runner = ScriptedBdRunner(steps=[ScriptedStep(("update",), _OK)])

    exit_code, _, _ = run_cli_with_runner(["update", "x.1", "--set-parent", "p.2"], runner)

    assert exit_code == 0
    assert runner.calls == [("update", "x.1", "--parent", "p.2")]


def test_update_set_parent_alone_satisfies_the_at_least_one_flag_requirement():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("update",), _OK)])

    exit_code, envelope, _ = run_cli_with_runner(["update", "x.1", "--set-parent", "p.2"], runner)

    assert exit_code == 0
    assert envelope["error"] is None


def test_update_combines_set_parent_with_other_replace_fields_in_one_call():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("update",), _OK)])

    exit_code, _, _ = run_cli_with_runner(
        ["update", "x.1", "--set-title", "New title", "--set-parent", "p.2"], runner
    )

    assert exit_code == 0
    assert runner.calls == [("update", "x.1", "--title", "New title", "--parent", "p.2")]


def test_update_set_parent_with_an_empty_value_is_refused_before_any_bd_call():
    # bd reads an empty `--parent` as "remove the parent", which is what an
    # unset shell variable expands to. Silently orphaning an item is not what
    # anyone typing a move means.
    runner = ScriptedBdRunner(steps=[])

    exit_code, envelope, _ = run_cli_with_runner(["update", "x.1", "--set-parent", ""], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)
    assert error["detail"] == {"field": "parent"}
    assert runner.calls == []


def test_update_set_parent_to_a_missing_item_reports_not_found_not_backend_drift():
    # bd's reparent path uses a DIFFERENT not-found wording than every other
    # command ("not found: issue X", not "no issue found matching X"). Without
    # that second marker the likeliest `--set-parent` mistake reports
    # E_BACKEND_DRIFT -- "bd's own model of itself broke" -- for a plain typo.
    exit_code, envelope, _ = run_cli(
        ["update", "x.1", "--set-parent", "nosuch.1"],
        steps=[
            ScriptedStep(
                ("update",),
                BdResult(
                    returncode=1,
                    stdout="",
                    stderr="Error getting parent nosuch.1: not found: issue nosuch.1\n",
                ),
            )
        ],
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.NOT_FOUND)


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


def test_close_refused_for_open_blockers_is_a_refusal_not_a_drift_alarm():
    # The backend understood the request perfectly and declined it: the item
    # has an open blocker. Reporting that through the drift catch-all would
    # tell the caller their tracker is broken when their graph is working,
    # which is a worse answer than the leak it used to arrive with. The
    # blockers come back itemised, because "which ones" is the whole of what
    # the caller does next.
    exit_code, envelope, _ = run_cli(
        ["close", "itest-2mk"],
        steps=[
            ScriptedStep(
                ("close",),
                BdResult(
                    returncode=1,
                    stdout="",
                    stderr=(
                        "cannot close itest-2mk: blocked by open issues "
                        "[itest-6cl] (use --force to override)\n"
                    ),
                ),
            )
        ],
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.OPEN_BLOCKERS)
    assert error["detail"]["blocked_by"] == ["itest-6cl"]
    assert "itest-6cl" in error["message"]
    # The backend offers a flag that overrides this. The facade does not, so
    # the advice that travels is advice the caller can actually take.
    assert "--force" not in error["message"]


def test_a_blocker_refusal_the_adapter_cannot_itemise_is_still_a_refusal():
    # Same refusal, a wording this adapter's pattern does not fit. Falling
    # back to the drift alarm here would misreport a working tracker; falling
    # back to an un-itemised refusal loses the ids and nothing else.
    exit_code, envelope, _ = run_cli(
        ["close", "itest-2mk"],
        steps=[
            ScriptedStep(
                ("close",),
                BdResult(returncode=1, stdout="", stderr="refusing: blocked by open issues\n"),
            )
        ],
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.OPEN_BLOCKERS)
    assert error["detail"] == {}


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
