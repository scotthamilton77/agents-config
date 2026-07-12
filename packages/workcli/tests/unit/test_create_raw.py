"""`work create --raw` (spec test-plan item 3, locked decisions 6/7).

`create` is the adapter primitive only -- public, noun-templated creation
belongs to the lifecycle layer (bead .9.2), so a bare `work create` without
`--raw` must refuse with `E_USAGE` naming that layer (decision 7). With
`--raw`, exactly one bd invocation reaches the runner even when a `--parent`
is given -- bd's own `--parent` flag auto-adds the parent edge, so a second
`dep add` call would double it (established fact from earlier tasks).
"""

from __future__ import annotations

import json
from argparse import Namespace

from tests.conftest import run_cli, run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode, WorkError
from workcli.verbs.write import create_raw


def _create_result(new_id: str) -> BdResult:
    # bd create --json emits a single JSON *object* (the created issue, with
    # a schema_version key injected inline) -- not an array like show/list.
    return BdResult(
        returncode=0,
        stdout=json.dumps({"id": new_id, "schema_version": 3, "title": "T"}),
        stderr="",
    )


def test_create_raw_with_parent_sends_exactly_one_bd_call_and_no_dep_add():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("create",), _create_result("x.9"))])

    exit_code, envelope, _ = run_cli_with_runner(
        ["create", "--raw", "--title", "T", "--parent", "P"], runner
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.9"}
    assert len(runner.calls) == 1
    assert runner.calls == [("create", "--json", "--title", "T", "--parent", "P")]
    assert not any(call[0] == "dep" for call in runner.calls)


def test_create_raw_with_labels_joins_them_into_one_labels_flag():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("create",), _create_result("x.10"))])

    exit_code, _, _ = run_cli_with_runner(
        ["create", "--raw", "--title", "T", "--label", "a", "--label", "b", "--label", "c"],
        runner,
    )

    assert exit_code == 0
    assert runner.calls == [("create", "--json", "--title", "T", "--labels", "a,b,c")]


def test_create_without_raw_or_noun_yields_usage_envelope_naming_both_modes():
    # The `create` dispatcher (verbs/__init__.py) owns this case now -- it
    # never reaches create_raw's own internal `--raw` guard below, which
    # stays as defensive dead code once --raw is the dispatcher's own gate.
    exit_code, envelope, _ = run_cli(["create", "--title", "T"], steps=[])

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)
    assert "--raw" in error["message"]
    assert "spike" in error["message"]


def test_create_missing_title_yields_usage_envelope():
    exit_code, envelope, _ = run_cli(["create", "--raw"], steps=[])

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)


def test_create_raw_called_directly_without_raw_flag_still_refuses():
    # verbs/__init__.py's dispatcher gates --raw before ever calling
    # create_raw, so this branch is unreachable through the CLI (Task 3) --
    # it stays as create_raw's own defensive contract for any direct,
    # non-CLI caller (create_raw itself is unchanged by Task 3).
    try:
        create_raw(None, Namespace(raw=False))  # type: ignore[arg-type]
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.USAGE
        assert "lifecycle" in error.message.lower()


def test_create_raw_not_found_parent_maps_to_not_found_envelope():
    exit_code, envelope, _ = run_cli(
        ["create", "--raw", "--title", "T", "--parent", "bogus"],
        steps=[
            ScriptedStep(
                ("create",),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "bogus"\n'),
            )
        ],
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.NOT_FOUND)
