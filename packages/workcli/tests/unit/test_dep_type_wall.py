"""`dep add/remove/list` — type-wall pre-check, positional order, direction mapping.

Spec test-plan item 4 + decision 5: a `blocks` dep between an epic and a
non-epic is pre-checked via one `Backend.batch_get([from_id, to_id])` read
(never a bd `dep` mutation) and raises the named `E_TYPE_WALL` before bd is
ever asked to add the edge. The wall only applies to `blocks`; any other dep
type skips the pre-check entirely. `dep list` maps bd's own inverted
direction naming (`down` = depends-on, `up` = dependents) into the ruling's
renamed fields.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import run_cli, run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

_OK = BdResult(returncode=0, stdout="", stderr="")


def _combined_show_result(*entries: tuple[str, str]) -> BdResult:
    """A `bd show a b --json` response covering the type-wall's combined read.

    `entries` is `(id, issue_type)` pairs listed in whatever order the fake
    should emit them -- deliberately independent of request order, since the
    wall check's own contract (Finding 1) is that `Backend.batch_get`
    reorders to match the request regardless of bd's own output order.
    """
    payload = [
        {"id": item_id, "title": "t", "issue_type": issue_type, "status": "open", "priority": 2}
        for item_id, issue_type in entries
    ]
    return BdResult(returncode=0, stdout=json.dumps(payload), stderr="")


def test_dep_add_blocks_between_epic_and_task_yields_type_wall_and_never_mutates():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show", "epic.1", "task.1", "--json"),
                _combined_show_result(("epic.1", "epic"), ("task.1", "task")),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["dep", "add", "epic.1", "task.1", "--type", "blocks"], runner
    )

    assert exit_code == 1
    error = envelope["error"]
    assert error["code"] == str(ErrorCode.TYPE_WALL)
    assert error["detail"] == {"from": "epic.1", "to": "task.1", "dep_type": "blocks"}
    assert runner.calls == [("show", "epic.1", "task.1", "--json")]
    assert not any(call[:2] == ("dep", "add") for call in runner.calls)


def test_dep_add_blocks_between_task_and_epic_yields_type_wall_the_other_direction():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show", "task.1", "epic.1", "--json"),
                _combined_show_result(("task.1", "task"), ("epic.1", "epic")),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["dep", "add", "task.1", "epic.1", "--type", "blocks"], runner
    )

    assert exit_code == 1
    error = envelope["error"]
    assert error["code"] == str(ErrorCode.TYPE_WALL)
    assert error["detail"] == {"from": "task.1", "to": "epic.1", "dep_type": "blocks"}
    assert not any(call[:2] == ("dep", "add") for call in runner.calls)


def test_dep_add_blocks_between_two_epics_passes_through_to_one_dep_add_call():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show", "epic.1", "epic.2", "--json"),
                _combined_show_result(("epic.1", "epic"), ("epic.2", "epic")),
            ),
            ScriptedStep(("dep", "add"), _OK),
        ]
    )

    exit_code, _, _ = run_cli_with_runner(
        ["dep", "add", "epic.1", "epic.2", "--type", "blocks"], runner
    )

    assert exit_code == 0
    assert runner.calls == [
        ("show", "epic.1", "epic.2", "--json"),
        ("dep", "add", "epic.1", "epic.2", "--type", "blocks"),
    ]


def test_dep_add_blocks_between_two_tasks_passes_through_with_correct_positional_order():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show", "task.1", "task.2", "--json"),
                _combined_show_result(("task.1", "task"), ("task.2", "task")),
            ),
            ScriptedStep(("dep", "add"), _OK),
        ]
    )

    # `work dep add A B` = A depends on B (plan CLI table).
    exit_code, _, _ = run_cli_with_runner(["dep", "add", "task.1", "task.2"], runner)

    assert exit_code == 0
    assert runner.calls[-1] == ("dep", "add", "task.1", "task.2", "--type", "blocks")


def test_dep_add_with_a_milestone_and_a_task_yields_type_wall_milestone_counts_as_non_epic():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show", "epic.1", "milestone.1", "--json"),
                _combined_show_result(("epic.1", "epic"), ("milestone.1", "milestone")),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["dep", "add", "epic.1", "milestone.1", "--type", "blocks"], runner
    )

    assert exit_code == 1
    assert envelope["error"]["code"] == str(ErrorCode.TYPE_WALL)
    # The diagnostic names the actual item types, never a hardcoded
    # "task" stand-in for every non-epic (milestone here).
    assert envelope["error"]["message"] == "blocks: epic may not block milestone"


def test_dep_add_epic_task_still_detects_the_wall_when_the_combined_show_returns_reversed_order():
    # Regression test for the Finding-1 bug: `_type_wall_check` positionally
    # unpacks `from_item, to_item = backend.batch_get([from_id, to_id])`. If
    # `batch_get` ever handed back bd's raw output order instead of request
    # order, a reversed response here would silently validate the wrong item
    # against each role and miss the violation entirely.
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show", "epic.1", "task.1", "--json"),
                # bd's own response order reversed vs the request.
                _combined_show_result(("task.1", "task"), ("epic.1", "epic")),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["dep", "add", "epic.1", "task.1", "--type", "blocks"], runner
    )

    assert exit_code == 1
    error = envelope["error"]
    assert error["code"] == str(ErrorCode.TYPE_WALL)
    assert error["detail"] == {"from": "epic.1", "to": "task.1", "dep_type": "blocks"}


def test_dep_add_with_related_to_type_skips_the_wall_check_entirely():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("dep", "add"), _OK)])

    exit_code, _, _ = run_cli_with_runner(
        ["dep", "add", "epic.1", "task.1", "--type", "related-to"], runner
    )

    assert exit_code == 0
    # No `show` reads at all -- the pre-check never runs for a non-blocks type.
    assert runner.calls == [("dep", "add", "epic.1", "task.1", "--type", "related-to")]


def test_dep_remove_sends_exactly_one_bd_call_with_no_type_flag():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("dep", "remove"), _OK)])

    exit_code, _, _ = run_cli_with_runner(["dep", "remove", "x.1", "y.1"], runner)

    assert exit_code == 0
    assert runner.calls == [("dep", "remove", "x.1", "y.1")]


def test_dep_add_requires_a_target():
    exit_code, envelope, _ = run_cli(["dep", "add", "x.1"], steps=[])

    assert exit_code == 1
    assert envelope["error"]["code"] == str(ErrorCode.USAGE)


def test_dep_list_maps_bds_inverted_directions_into_depends_on_and_dependents():
    # bd_dep_list_down.json (default direction) is what wgclw.9.1 depends on;
    # bd_dep_list_up.json (--direction up) is what depends on wgclw.9.1.
    # Getting this backward is the worst silent bug this test guards against.
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("dep", "list", "agents-config-wgclw.9.1", "--json"),
                BdResult(
                    returncode=0,
                    stdout=(FIXTURES / "bd_dep_list_down.json").read_text(),
                    stderr="",
                ),
            ),
            ScriptedStep(
                ("dep", "list", "agents-config-wgclw.9.1", "--direction", "up", "--json"),
                BdResult(
                    returncode=0,
                    stdout=(FIXTURES / "bd_dep_list_up.json").read_text(),
                    stderr="",
                ),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["dep", "list", "agents-config-wgclw.9.1"], runner)

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["depends_on"] == [
        {"id": "agents-config-wgclw.9", "type": "parent-child", "status": "open"}
    ]
    assert data["dependents"] == [
        {"id": "agents-config-wgclw.9.2", "type": "blocks", "status": "open"}
    ]


def test_dep_add_backend_fallback_maps_a_cycle_stderr_to_dep_cycle():
    # Both same type (task), so the pre-check passes and the mutating call
    # reaches bd -- which is the only layer that can see a real cycle.
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show", "task.1", "task.2", "--json"),
                _combined_show_result(("task.1", "task"), ("task.2", "task")),
            ),
            ScriptedStep(
                ("dep", "add"),
                BdResult(
                    returncode=1,
                    stdout="",
                    stderr="Error: adding dependency would create a cycle\n",
                ),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["dep", "add", "task.1", "task.2", "--type", "blocks"], runner
    )

    assert exit_code == 1
    assert envelope["error"]["code"] == str(ErrorCode.DEP_CYCLE)
