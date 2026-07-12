"""Envelope invariant matrix (spec test-plan item 1) + handshake tail (item 10).

Every one of the twelve contract verbs, in both a success and a failure
case, must emit exactly one parseable JSON envelope on stdout carrying
`protocol`, with the exit code mirroring `ok` and the error shape typed —
uniformly, regardless of which verb or which typed error fired. This file
asserts ONLY those uniform invariants; per-verb data-shape assertions
belong to that verb's own granular test file (`test_show_normalization.py`,
`test_sync.py`, etc.) and are deliberately not duplicated here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.conftest import run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli import PROTOCOL_VERSION
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

_OK = BdResult(returncode=0, stdout="", stderr="")
_EMPTY_ARRAY = BdResult(returncode=0, stdout="[]", stderr="")
_GARBAGE = BdResult(returncode=0, stdout="not json at all {{{", stderr="")
_NOT_FOUND = BdResult(returncode=1, stdout="", stderr='no issue found matching "bogus"\n')


def _create_ok() -> BdResult:
    return BdResult(
        returncode=0, stdout=json.dumps({"id": "x.9", "schema_version": 3, "title": "T"}), stderr=""
    )


def _show_ok() -> BdResult:
    return BdResult(
        returncode=0, stdout=(FIXTURES / "bd_show_wgclw9.1.json").read_text(), stderr=""
    )


def _dep_list_down() -> BdResult:
    return BdResult(
        returncode=0, stdout=(FIXTURES / "bd_dep_list_down.json").read_text(), stderr=""
    )


def _dep_list_up() -> BdResult:
    return BdResult(returncode=0, stdout=(FIXTURES / "bd_dep_list_up.json").read_text(), stderr="")


def _label_list_ok() -> BdResult:
    return BdResult(
        returncode=0, stdout=(FIXTURES / "bd_label_list_wgclw9.1.json").read_text(), stderr=""
    )


def _item_raw(
    item_id: str, title: str, *, status: str = "open", labels: list[str] | None = None
) -> dict[str, object]:
    return {
        "id": item_id,
        "title": title,
        "issue_type": "task",
        "status": status,
        "priority": 2,
        "labels": labels or [],
        "dependencies": [],
        "dependents": [],
    }


def _search_result(*raw_items: dict[str, object]) -> BdResult:
    return BdResult(returncode=0, stdout=json.dumps(list(raw_items)), stderr="")


def _show_result(*raw_items: dict[str, object]) -> BdResult:
    return BdResult(returncode=0, stdout=json.dumps(list(raw_items)), stderr="")


def _list_result(*raw_items: dict[str, object]) -> BdResult:
    return BdResult(returncode=0, stdout=json.dumps(list(raw_items)), stderr="")


def _lifecycle_create_result(new_id: str) -> BdResult:
    return BdResult(
        returncode=0,
        stdout=json.dumps({"id": new_id, "schema_version": 3, "title": "T"}),
        stderr="",
    )


@dataclass(frozen=True)
class VerbCase:
    verb: str
    success_argv: list[str]
    success_steps: list[ScriptedStep]
    failure_argv: list[str]
    failure_steps: list[ScriptedStep]


VERB_CASES: list[VerbCase] = [
    VerbCase(
        "show",
        ["show", "agents-config-wgclw.9.1"],
        [ScriptedStep(("show",), _show_ok())],
        ["show", "bogus"],
        [ScriptedStep(("show",), _NOT_FOUND)],
    ),
    VerbCase(
        "create",
        ["create", "--raw", "--title", "T"],
        [ScriptedStep(("create",), _create_ok())],
        ["create", "--title", "T"],  # missing --raw -> E_USAGE, no bd call
        [],
    ),
    VerbCase(
        "update",
        ["update", "x.1", "--set-title", "New title"],
        [ScriptedStep(("update",), _OK)],
        ["update", "x.1"],  # no --set-* flags -> E_USAGE, no bd call
        [],
    ),
    VerbCase(
        "note",
        ["note", "x.1", "hello"],
        [ScriptedStep(("update",), _OK)],
        ["note", "bogus", "hi"],
        [ScriptedStep(("update",), _NOT_FOUND)],
    ),
    VerbCase(
        "close",
        ["close", "a.1"],
        [ScriptedStep(("close",), _OK)],
        ["close", "bogus"],
        [ScriptedStep(("close",), _NOT_FOUND)],
    ),
    VerbCase(
        "reopen",
        ["reopen", "a.1"],
        [ScriptedStep(("reopen",), _OK)],
        ["reopen", "bogus"],
        [ScriptedStep(("reopen",), _NOT_FOUND)],
    ),
    VerbCase(
        "list",
        ["list"],
        [ScriptedStep(("list",), _EMPTY_ARRAY)],
        ["list"],
        [ScriptedStep(("list",), _GARBAGE)],
    ),
    VerbCase(
        "ready",
        ["ready"],
        [ScriptedStep(("ready",), _EMPTY_ARRAY)],
        ["ready"],
        [ScriptedStep(("ready",), _GARBAGE)],
    ),
    VerbCase(
        "dep",
        ["dep", "list", "agents-config-wgclw.9.1"],
        [
            ScriptedStep(("dep", "list", "agents-config-wgclw.9.1", "--json"), _dep_list_down()),
            ScriptedStep(
                ("dep", "list", "agents-config-wgclw.9.1", "--direction", "up", "--json"),
                _dep_list_up(),
            ),
        ],
        ["dep", "add", "x.1"],  # missing TARGET -> E_USAGE, no bd call
        [],
    ),
    VerbCase(
        "label",
        ["label", "list", "x.1"],
        [ScriptedStep(("label", "list"), _label_list_ok())],
        ["label", "add", "x.1"],  # no labels -> E_USAGE, no bd call
        [],
    ),
    VerbCase(
        "search",
        ["search", "quarantine"],
        [ScriptedStep(("search",), _EMPTY_ARRAY)],
        ["search", "quarantine"],
        [ScriptedStep(("search",), _GARBAGE)],
    ),
    VerbCase(
        "sync",
        ["sync"],
        [ScriptedStep(("dolt", "commit"), _OK), ScriptedStep(("dolt", "push"), _OK)],
        ["sync", "--pull"],
        [
            ScriptedStep(
                ("dolt", "pull"),
                BdResult(returncode=1, stdout="", stderr="cannot merge with uncommitted changes\n"),
            )
        ],
    ),
    # --- lifecycle verbs (plan Task 7 -- one success + one failure per verb,
    # over the seven lifecycle verbs from create through reconcile) ---------
    VerbCase(
        "create_noun",
        ["create", "spec", "--title", "New Objective", "--parent", "P"],
        [
            ScriptedStep(("search",), _search_result()),  # no title collision
            ScriptedStep(("create",), _lifecycle_create_result("s.1")),  # container
            ScriptedStep(("create",), _lifecycle_create_result("s.2")),  # design child
            ScriptedStep(("create",), _lifecycle_create_result("s.3")),  # placeholder
            ScriptedStep(("label", "add"), _OK),  # planned, stamped last
        ],
        ["create", "feat", "--title", "Existing Feature", "--parent", "P"],
        [ScriptedStep(("search",), _search_result(_item_raw("f.9", "Existing Feature")))],
    ),
    VerbCase(
        "claim",
        ["claim", "c.1"],
        [
            ScriptedStep(("show",), _show_result(_item_raw("c.1", "T", status="open"))),
            ScriptedStep(("ready",), _list_result(_item_raw("c.1", "T", status="open"))),
            ScriptedStep(("update",), _OK),
        ],
        ["claim", "c.2"],
        [ScriptedStep(("show",), _show_result(_item_raw("c.2", "T", status="closed")))],
    ),
    VerbCase(
        "release",
        ["release", "r.1"],
        [
            ScriptedStep(("show",), _show_result(_item_raw("r.1", "T", status="in_progress"))),
            ScriptedStep(("update",), _OK),
        ],
        ["release", "r.2"],
        [ScriptedStep(("show",), _show_result(_item_raw("r.2", "T", status="closed")))],
    ),
    VerbCase(
        "deliver",
        ["deliver", "d.1", "--pr", "https://example/pr/9"],
        [
            ScriptedStep(
                ("show",), _show_result(_item_raw("d.1", "T", status="open", labels=["shape-feat"]))
            ),
            ScriptedStep(("update",), _OK),  # delivered note
            ScriptedStep(("close",), _OK),
        ],
        ["deliver", "d.2"],  # no --pr/--items/--trivial -> E_EVIDENCE
        [
            ScriptedStep(
                ("show",), _show_result(_item_raw("d.2", "T", status="open", labels=["shape-feat"]))
            )
        ],
    ),
    VerbCase(
        "plan",
        ["plan", "p.1", "--done"],
        [
            ScriptedStep(
                ("show",), _show_result(_item_raw("p.1", "T", status="open", labels=["shape-spec"]))
            ),
            ScriptedStep(("label", "add"), _OK),
        ],
        ["plan", "p.2"],  # neither --done nor --undo -> E_USAGE, no bd call
        [],
    ),
    VerbCase(
        "promote",
        ["promote", "m.1"],
        [
            ScriptedStep(
                ("show",), _show_result(_item_raw("m.1", "T", status="open", labels=["shape-feat"]))
            ),
            ScriptedStep(("label", "add"), _OK),  # shape-spec
            ScriptedStep(("label", "remove"), _OK),  # shape-feat
            ScriptedStep(("create",), _lifecycle_create_result("m.2")),  # design child
            ScriptedStep(("create",), _lifecycle_create_result("m.3")),  # placeholder
            ScriptedStep(("label", "add"), _OK),  # planned, stamped last
        ],
        ["promote", "m.2"],  # not shape-feat -> E_USAGE
        [ScriptedStep(("show",), _show_result(_item_raw("m.2", "T", status="open")))],
    ),
    VerbCase(
        "reconcile",
        ["reconcile"],
        [
            ScriptedStep(("list",), _list_result()),  # interrupted-deliver sweep: empty
            ScriptedStep(("list",), _list_result()),  # impl-placeholder sweep: empty
        ],
        ["reconcile"],
        [ScriptedStep(("list",), _GARBAGE)],  # unparseable bd list output -> E_BACKEND_DRIFT
    ),
]

TYPED_ERROR_CODES = {str(code) for code in ErrorCode}


def _assert_stdout_is_exactly_one_envelope(runner: ScriptedBdRunner, argv: list[str]) -> dict:
    from io import StringIO

    from workcli.cli import main

    out = StringIO()
    err = StringIO()
    exit_code = main(argv, runner=runner, out=out, err=err)
    stdout_text = out.getvalue()
    # Exactly one JSON value on stdout, nothing before or after it: a
    # trailing newline is the only thing besides the envelope permitted.
    assert stdout_text.endswith("\n")
    body = stdout_text[:-1]
    assert "\n" not in body, f"stdout carried more than one line: {stdout_text!r}"
    envelope = json.loads(body)
    return exit_code, envelope  # type: ignore[return-value]


@pytest.mark.parametrize("case", VERB_CASES, ids=lambda c: c.verb)
def test_success_case_yields_a_uniform_ok_envelope(case: VerbCase) -> None:
    runner = ScriptedBdRunner(steps=list(case.success_steps))
    exit_code, envelope = _assert_stdout_is_exactly_one_envelope(runner, case.success_argv)

    assert exit_code == 0
    assert envelope["protocol"] == PROTOCOL_VERSION
    assert envelope["ok"] is True
    assert envelope["error"] is None


@pytest.mark.parametrize("case", VERB_CASES, ids=lambda c: c.verb)
def test_failure_case_yields_a_uniform_error_envelope(case: VerbCase) -> None:
    runner = ScriptedBdRunner(steps=list(case.failure_steps))
    exit_code, envelope = _assert_stdout_is_exactly_one_envelope(runner, case.failure_argv)

    assert exit_code == 1
    assert envelope["protocol"] == PROTOCOL_VERSION
    assert envelope["ok"] is False
    assert envelope["data"] is None
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] in TYPED_ERROR_CODES


def test_protocol_version_data_matches_every_other_verbs_protocol_field() -> None:
    handshake_exit, handshake_envelope, _ = run_cli_with_runner(
        ["--protocol-version"], ScriptedBdRunner(steps=[])
    )
    assert handshake_exit == 0
    assert handshake_envelope["data"] == {"protocol": PROTOCOL_VERSION}

    for case in VERB_CASES:
        runner = ScriptedBdRunner(steps=list(case.success_steps))
        _, envelope = _assert_stdout_is_exactly_one_envelope(runner, case.success_argv)
        assert envelope["protocol"] == handshake_envelope["data"]["protocol"]
