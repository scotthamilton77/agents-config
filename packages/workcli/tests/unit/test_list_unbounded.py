"""`list`/`ready` default to unbounded.

bd's own `list`/`ready` default row caps (50/100) are the exact quirk this
facade exists to kill: the adapter always sends `--limit 0` unless the
caller passes a positive `--limit`, and every row bd returns must surface in
the envelope, not just the first page.
"""

from __future__ import annotations

import json

from tests.conftest import run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult


def _bare_items(count: int, *, prefix: str = "x") -> list[dict[str, object]]:
    return [
        {
            "id": f"{prefix}.{i}",
            "title": f"item {i}",
            "issue_type": "task",
            "status": "open",
            "priority": 2,
            "labels": [],
            "dependencies": [],
            "dependents": [],
        }
        for i in range(count)
    ]


def test_list_defaults_to_unbounded_and_every_row_surfaces():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("list",),
                BdResult(returncode=0, stdout=json.dumps(_bare_items(60)), stderr=""),
            )
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["list"], runner)

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    assert len(data["items"]) == 60
    assert runner.calls == [("list", "--json", "--limit", "0")]


def test_list_limit_flag_passes_through_a_positive_limit():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("list",), BdResult(returncode=0, stdout="[]", stderr=""))]
    )

    exit_code, _, _ = run_cli_with_runner(["list", "--limit", "7"], runner)

    assert exit_code == 0
    assert runner.calls == [("list", "--json", "--limit", "7")]


def test_list_status_label_parent_type_filters_map_to_bd_flags():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("list",), BdResult(returncode=0, stdout="[]", stderr=""))]
    )

    exit_code, _, _ = run_cli_with_runner(
        [
            "list",
            "--status",
            "open",
            "--label",
            "foo",
            "--type",
            "task",
            "--parent",
            "x.1",
        ],
        runner,
    )

    assert exit_code == 0
    assert runner.calls == [
        (
            "list",
            "--json",
            "--status",
            "open",
            "--label",
            "foo",
            "--parent",
            "x.1",
            "--type",
            "task",
            "--limit",
            "0",
        )
    ]


def test_ready_defaults_to_unbounded_and_every_row_surfaces():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("ready",),
                BdResult(returncode=0, stdout=json.dumps(_bare_items(120)), stderr=""),
            )
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["ready"], runner)

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    assert len(data["items"]) == 120
    assert runner.calls == [("ready", "--json", "--limit", "0")]


def test_ready_label_flag_passes_through():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("ready",), BdResult(returncode=0, stdout="[]", stderr=""))]
    )

    exit_code, _, _ = run_cli_with_runner(["ready", "--label", "tech-debt"], runner)

    assert exit_code == 0
    assert runner.calls == [("ready", "--json", "--label", "tech-debt", "--limit", "0")]
