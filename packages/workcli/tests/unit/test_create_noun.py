"""`work create <noun>` -- noun-templated creation (plan Task 3, test-plan items 1-3).

Duplicate-title guard (L13) fires before any `create` reaches bd; placement
(L14) requires exactly one of `--parent`/`--orphan`; the spec shape mints its
design child + placeholder before stamping `planned` LAST (L16). All
call-log assertions go through `run_cli_with_runner` (conftest.py) since
`run_cli` discards its runner and exposes no `.calls`.
"""

from __future__ import annotations

import json

from tests.conftest import run_cli, run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode
from workcli.lifecycle import ORPHAN_MARKER


def _create_result(new_id: str) -> BdResult:
    return BdResult(
        returncode=0,
        stdout=json.dumps({"id": new_id, "schema_version": 3, "title": "T"}),
        stderr="",
    )


def _search_result(*raw_items: dict[str, object]) -> BdResult:
    return BdResult(returncode=0, stdout=json.dumps(list(raw_items)), stderr="")


def _item_raw(item_id: str, title: str) -> dict[str, object]:
    return {
        "id": item_id,
        "title": title,
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "labels": [],
        "dependencies": [],
        "dependents": [],
    }


def test_create_with_no_raw_and_no_noun_yields_usage_naming_both():
    exit_code, envelope, _ = run_cli(["create", "--title", "T"], steps=[])

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)
    assert "--raw" in error["message"]
    assert "spike" in error["message"]


def test_create_spike_with_parent_sends_search_then_one_create_call():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("search",), _search_result()),
            ScriptedStep(("create",), _create_result("x.1")),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["create", "spike", "--title", "T", "--parent", "P"], runner
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1"}
    assert runner.calls == [
        ("search", "T", "--json"),
        (
            "create",
            "--json",
            "--title",
            "T",
            "--type",
            "task",
            "--parent",
            "P",
            "--labels",
            "shape-spike",
        ),
    ]


def test_create_chore_with_orphan_creates_with_no_parent_and_records_orphan_note():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("search",), _search_result()),
            ScriptedStep(("create",), _create_result("x.1")),
            ScriptedStep(("update",), BdResult(returncode=0, stdout="", stderr="")),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["create", "chore", "--title", "T", "--orphan"], runner
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1"}
    assert runner.calls == [
        ("search", "T", "--json"),
        ("create", "--json", "--title", "T", "--type", "chore", "--labels", "shape-chore"),
        ("update", "x.1", "--append-notes", ORPHAN_MARKER),
    ]


def test_create_requires_exactly_one_of_parent_or_orphan_neither_given():
    exit_code, envelope, _ = run_cli(["create", "spike", "--title", "T"], steps=[])

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)


def test_create_requires_exactly_one_of_parent_or_orphan_both_given():
    exit_code, envelope, _ = run_cli(
        ["create", "spike", "--title", "T", "--parent", "P", "--orphan"], steps=[]
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)


def test_create_duplicate_title_blocks_before_any_create_call():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("search",), _search_result(_item_raw("x.9", "T")))]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["create", "spike", "--title", "T", "--parent", "P"], runner
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.DUPLICATE_TITLE)
    assert error["detail"] == {"id": "x.9"}
    assert runner.calls == [("search", "T", "--json")]


def test_create_feat_with_type_flag_is_usage_error_without_any_bd_call():
    exit_code, envelope, _ = run_cli(
        ["create", "feat", "--title", "T", "--parent", "P", "--type", "bug"], steps=[]
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)


def test_create_feat_with_label_flag_is_usage_error_without_any_bd_call():
    # The noun owns its labels (lifecycle-semantic queryable handles); a
    # user-supplied --label is rejected rather than silently dropped, mirroring
    # the --type rejection.
    exit_code, envelope, _ = run_cli(
        ["create", "feat", "--title", "T", "--parent", "P", "--label", "hot"], steps=[]
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)
    assert "--label" in error["message"]


def test_create_feat_with_spec_evidence_adds_spec_ready_label():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("search",), _search_result()),
            ScriptedStep(("create",), _create_result("x.1")),
        ]
    )

    exit_code, _, _ = run_cli_with_runner(
        ["create", "feat", "--title", "T", "--parent", "P", "--spec", "S"], runner
    )

    assert exit_code == 0
    assert runner.calls == [
        ("search", "T", "--json"),
        (
            "create",
            "--json",
            "--title",
            "T",
            "--type",
            "feature",
            "--parent",
            "P",
            "--labels",
            "shape-feat,spec-ready",
        ),
    ]


def test_create_feat_without_evidence_omits_spec_ready_label():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("search",), _search_result()),
            ScriptedStep(("create",), _create_result("x.1")),
        ]
    )

    exit_code, _, _ = run_cli_with_runner(
        ["create", "feat", "--title", "T", "--parent", "P"], runner
    )

    assert exit_code == 0
    assert runner.calls == [
        ("search", "T", "--json"),
        (
            "create",
            "--json",
            "--title",
            "T",
            "--type",
            "feature",
            "--parent",
            "P",
            "--labels",
            "shape-feat",
        ),
    ]


def test_create_feat_with_trivial_adds_spec_ready_label():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("search",), _search_result()),
            ScriptedStep(("create",), _create_result("x.1")),
        ]
    )

    exit_code, _, _ = run_cli_with_runner(
        ["create", "feat", "--title", "T", "--parent", "P", "--trivial"], runner
    )

    assert exit_code == 0
    assert runner.calls == [
        ("search", "T", "--json"),
        (
            "create",
            "--json",
            "--title",
            "T",
            "--type",
            "feature",
            "--parent",
            "P",
            "--labels",
            "shape-feat,spec-ready",
        ),
    ]


def test_create_spec_and_trivial_together_is_usage_error_without_any_bd_call():
    exit_code, envelope, _ = run_cli(
        [
            "create",
            "feat",
            "--title",
            "T",
            "--parent",
            "P",
            "--spec",
            "S",
            "--trivial",
        ],
        steps=[],
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)


def test_create_epic_sends_one_create_with_epic_type_and_shape_label():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("search",), _search_result()),
            ScriptedStep(("create",), _create_result("x.1")),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["create", "epic", "--title", "T", "--parent", "P"], runner
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1"}
    assert runner.calls == [
        ("search", "T", "--json"),
        (
            "create",
            "--json",
            "--title",
            "T",
            "--type",
            "epic",
            "--parent",
            "P",
            "--labels",
            "shape-epic",
        ),
    ]


def test_create_spec_mints_shape_with_creating_spec_handle_removed_last():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("search",), _search_result()),
            ScriptedStep(("create",), _create_result("x.1")),  # container
            ScriptedStep(
                ("label", "add"), BdResult(returncode=0, stdout="", stderr="")
            ),  # shape-spec
            ScriptedStep(
                ("label", "remove"), BdResult(returncode=0, stdout="", stderr="")
            ),  # shape-feat
            ScriptedStep(("show",), _search_result(_item_raw("x.1", "T"))),  # instantiate get
            ScriptedStep(("create",), _create_result("x.2")),  # design child
            ScriptedStep(("create",), _create_result("x.3")),  # placeholder
            ScriptedStep(("label", "add"), BdResult(returncode=0, stdout="", stderr="")),  # planned
            ScriptedStep(
                ("label", "remove"), BdResult(returncode=0, stdout="", stderr="")
            ),  # creating-spec
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["create", "spec", "--title", "T", "--parent", "P"], runner
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "design_child": "x.2", "placeholder": "x.3"}
    assert runner.calls == [
        ("search", "T", "--json"),
        (
            "create",
            "--json",
            "--title",
            "T",
            "--type",
            "feature",
            "--parent",
            "P",
            "--labels",
            "shape-spec,creating-spec",
        ),
        ("label", "add", "x.1", "shape-spec"),
        ("label", "remove", "x.1", "shape-feat"),
        ("show", "x.1", "--json"),
        (
            "create",
            "--json",
            "--title",
            "Design: T",
            "--type",
            "task",
            "--parent",
            "x.1",
            "--labels",
            "shape-design",
        ),
        (
            "create",
            "--json",
            "--title",
            "[Impl] T (scope: per spec)",
            "--type",
            "task",
            "--parent",
            "x.1",
            "--labels",
            "impl-placeholder",
            "--deps",
            "x.2",
        ),
        ("label", "add", "x.1", "planned"),
        ("label", "remove", "x.1", "creating-spec"),
    ]
    # `creating-spec` comes off strictly last, after `planned` (L16).
    assert runner.calls[-1] == ("label", "remove", "x.1", "creating-spec")


def test_create_spec_with_orphan_creates_container_with_no_parent_and_records_orphan_note():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("search",), _search_result()),
            ScriptedStep(("create",), _create_result("x.1")),  # container
            ScriptedStep(("update",), BdResult(returncode=0, stdout="", stderr="")),  # orphan note
            ScriptedStep(
                ("label", "add"), BdResult(returncode=0, stdout="", stderr="")
            ),  # shape-spec
            ScriptedStep(
                ("label", "remove"), BdResult(returncode=0, stdout="", stderr="")
            ),  # shape-feat
            ScriptedStep(("show",), _search_result(_item_raw("x.1", "T"))),  # instantiate get
            ScriptedStep(("create",), _create_result("x.2")),  # design child
            ScriptedStep(("create",), _create_result("x.3")),  # placeholder
            ScriptedStep(("label", "add"), BdResult(returncode=0, stdout="", stderr="")),  # planned
            ScriptedStep(
                ("label", "remove"), BdResult(returncode=0, stdout="", stderr="")
            ),  # creating-spec
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["create", "spec", "--title", "T", "--orphan"], runner
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "design_child": "x.2", "placeholder": "x.3"}
    assert runner.calls[:3] == [
        ("search", "T", "--json"),
        (
            "create",
            "--json",
            "--title",
            "T",
            "--type",
            "feature",
            "--labels",
            "shape-spec,creating-spec",
        ),
        ("update", "x.1", "--append-notes", ORPHAN_MARKER),
    ]
    # The container itself is orphaned, but its own children (design child +
    # placeholder) are still parented under it -- orphan-by-choice is a
    # placement decision about the top-level item, never its own children.
    assert all("--parent" in call and "x.1" in call for call in runner.calls[6:8])
    assert runner.calls[-1] == ("label", "remove", "x.1", "creating-spec")
