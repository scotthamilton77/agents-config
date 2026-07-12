"""`BdBackend.batch_get` edge cases (plan L5, 38o1v #4).

Empty `ids` -> `[]` with zero bd calls (a new guard -- previously an empty
request still built and sent a `show --json` argv). Duplicate/extra-record
handling is already the contract (proven in test_bd_backend.py); pinned here
too as part of the same edge-case suite.
"""

from __future__ import annotations

import json

from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.backend import BdBackend
from workcli.adapters.bd.runner import BdResult


def test_batch_get_empty_ids_returns_empty_list_with_zero_bd_calls():
    runner = ScriptedBdRunner(steps=[])
    backend = BdBackend(runner)

    items = backend.batch_get([])

    assert items == []
    assert runner.calls == []


def test_batch_get_duplicate_requested_id_maps_to_the_same_item_at_each_position():
    payload = [{"id": "a.1", "title": "t1", "issue_type": "task", "status": "open", "priority": 1}]
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show", "a.1", "a.1", "--json"),
                BdResult(returncode=0, stdout=json.dumps(payload), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    items = backend.batch_get(["a.1", "a.1"])

    assert [item.id for item in items] == ["a.1", "a.1"]
    assert items[0] is items[1]


def test_batch_get_ignores_extra_unrequested_records_bd_returns():
    payload = [
        {"id": "a.1", "title": "t1", "issue_type": "task", "status": "open", "priority": 1},
        {
            "id": "z.9",
            "title": "unrequested",
            "issue_type": "task",
            "status": "open",
            "priority": 1,
        },
    ]
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show", "a.1", "--json"),
                BdResult(returncode=0, stdout=json.dumps(payload), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    items = backend.batch_get(["a.1"])

    assert [item.id for item in items] == ["a.1"]
