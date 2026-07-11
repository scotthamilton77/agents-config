"""`work search QUERY` — behavioral test through the full CLI."""

from __future__ import annotations

import json

from tests.conftest import run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult


def test_search_sends_the_query_and_surfaces_matching_items():
    raw = {
        "id": "x.1",
        "title": "quarantine bd behind a shim",
        "issue_type": "task",
        "status": "open",
        "priority": 1,
        "labels": [],
        "dependencies": [],
        "dependents": [],
    }
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("search",),
                BdResult(returncode=0, stdout=json.dumps([raw]), stderr=""),
            )
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["search", "quarantine"], runner)

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    assert [item["id"] for item in data["items"]] == ["x.1"]
    assert runner.calls == [("search", "quarantine", "--json")]
