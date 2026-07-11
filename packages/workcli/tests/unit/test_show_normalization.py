"""`show` verb normalization (spec test-plan item 2, decision 10).

A single id must yield an object (never a single-element array), with lean
dep edges (`{id, type, status}`) and `string[]` labels. Multiple ids must
yield `data == {"items": [...]}`. Both drive the real CLI end-to-end through
`ScriptedBdRunner`.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import run_cli, run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_show_single_id_returns_a_lean_object_not_an_array():
    exit_code, envelope, stderr_text = run_cli(
        ["show", "agents-config-wgclw.9.1"],
        steps=[
            ScriptedStep(
                ("show",),
                BdResult(returncode=0, stdout=_read("bd_show_wgclw9.1.json"), stderr=""),
            )
        ],
    )

    assert exit_code == 0
    assert stderr_text == ""
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["id"] == "agents-config-wgclw.9.1"
    # Lean labels: bare string[], not embedded objects.
    assert data["labels"] == ["implementation-ready", "shape-feat", "vision-85-5-10"]
    # The fixture's one `dependencies[]` entry is parent-child (filtered out
    # of `deps`, since it's the item's own parent edge, not a real
    # dependency); its one `dependents[]` entry is `dependency_type: blocks`,
    # not parent-child, so it is not a child either.
    assert data["deps"] == []
    assert data["children"] == []


def test_show_single_id_with_a_real_dependency_yields_a_lean_dep_edge():
    # bd_show_wgclw9.json's one non-parent-child dependency (`discovered-from`
    # -> agents-config-fca6.12, status closed) already backs the parser-level
    # assertion in test_bd_parse.py; this pins the same edge end-to-end
    # through `work show`, proving the envelope's `deps` serialization is
    # exactly the lean `{id, type, status}` shape, no extra keys.
    exit_code, envelope, stderr_text = run_cli(
        ["show", "agents-config-wgclw.9"],
        steps=[
            ScriptedStep(
                ("show",),
                BdResult(returncode=0, stdout=_read("bd_show_wgclw9.json"), stderr=""),
            )
        ],
    )

    assert exit_code == 0
    assert stderr_text == ""
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["deps"] == [
        {"id": "agents-config-fca6.12", "type": "discovered-from", "status": "closed"}
    ]


def test_show_two_ids_returns_an_items_array():
    raw_a = {
        "id": "x.1",
        "title": "First",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "labels": ["a"],
        "dependencies": [],
        "dependents": [],
    }
    raw_b = {
        "id": "x.2",
        "title": "Second",
        "issue_type": "bug",
        "status": "closed",
        "priority": 1,
        "labels": [],
        "dependencies": [],
        "dependents": [],
    }
    exit_code, envelope, _ = run_cli(
        ["show", "x.1", "x.2"],
        steps=[
            ScriptedStep(
                ("show",),
                BdResult(returncode=0, stdout=json.dumps([raw_a, raw_b]), stderr=""),
            )
        ],
    )

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    assert [item["id"] for item in data["items"]] == ["x.1", "x.2"]


def test_show_sends_bd_show_with_all_requested_ids_and_json_flag():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                (),
                BdResult(returncode=0, stdout=_read("bd_show_wgclw9.1.json"), stderr=""),
            )
        ]
    )

    exit_code, _, _ = run_cli_with_runner(["show", "agents-config-wgclw.9.1"], runner)

    assert exit_code == 0
    assert runner.calls == [("show", "agents-config-wgclw.9.1", "--json")]


def test_show_missing_id_yields_not_found_envelope_end_to_end():
    exit_code, envelope, _ = run_cli(
        ["show", "bogus-id"],
        steps=[
            ScriptedStep(
                ("show",),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "bogus-id"\n'),
            )
        ],
    )

    assert exit_code == 1
    assert envelope["ok"] is False
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.NOT_FOUND)
