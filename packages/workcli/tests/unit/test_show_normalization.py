"""`show` verb normalization.

`data == {"items": [...]}` for one id and for many alike, and each row is a
lean item: dep edges as `{id, type, status}`, labels as bare `string[]`.
Every test here drives the real CLI end-to-end through `ScriptedBdRunner`.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import only_item, run_cli, run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_show_single_id_returns_a_lean_item():
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
    item = only_item(envelope["data"])
    assert item["id"] == "agents-config-wgclw.9.1"
    # Lean labels: bare string[], not embedded objects.
    assert item["labels"] == ["implementation-ready", "shape-feat", "vision-85-5-10"]
    # The fixture's one `dependencies[]` entry is parent-child (filtered out
    # of `deps`, since it's the item's own parent edge, not a real
    # dependency); its one `dependents[]` entry is `dependency_type: blocks`,
    # not parent-child, so it is not a child either.
    assert item["deps"] == []
    assert item["children"] == []


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
    assert only_item(envelope["data"])["deps"] == [
        {"id": "agents-config-fca6.12", "type": "discovered-from", "status": "closed"}
    ]


def test_show_answers_one_id_in_the_same_shape_it_answers_many():
    # The uniform-shape contract, and the reason the two tests above read
    # through `items[0]`. Answering one id with the item itself and two or
    # more with `{"items": [...]}` leaves a consumer unable to write one
    # accessor for the verb -- and the argument count is frequently not a
    # literal at the call site: a script showing whatever ids a previous verb
    # returned would get one shape on a one-result day and another on a
    # two-result day. The two answers differ in the length of `items` and in
    # nothing else, which is what this asserts rather than the singular case
    # alone.
    raw = {
        "id": "x.1",
        "title": "First",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "labels": [],
        "dependencies": [],
        "dependents": [],
    }
    singular = run_cli(
        ["show", "x.1"],
        steps=[
            ScriptedStep(("show",), BdResult(returncode=0, stdout=json.dumps([raw]), stderr=""))
        ],
    )[1]
    plural = run_cli(
        ["show", "x.1", "x.2"],
        steps=[
            ScriptedStep(
                ("show",),
                BdResult(returncode=0, stdout=json.dumps([raw, {**raw, "id": "x.2"}]), stderr=""),
            )
        ],
    )[1]

    assert list(singular["data"].keys()) == list(plural["data"].keys()) == ["items"]
    assert [item["id"] for item in singular["data"]["items"]] == ["x.1"]
    assert [item["id"] for item in plural["data"]["items"]] == ["x.1", "x.2"]


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
