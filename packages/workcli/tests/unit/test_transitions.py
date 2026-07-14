"""`claim`/`release`/`plan`/`promote` -- guarded lifecycle transitions (plan Task 4,
test-plan items 8, 9, 10).

`claim`'s container guard is label/type-based (`is_container`), never child-count
(§5/invariant 5) -- the childless-`epic` test below is the proof. `promote`'s
mutation order (labels, then `instantiate_spec_shape`, then `planned` last, L16)
mirrors `create spec`. All call-log assertions go through `run_cli_with_runner`
(conftest.py) since `run_cli` discards its runner and exposes no `.calls`.
"""

from __future__ import annotations

import json

from tests.conftest import run_cli, run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode

_OK = BdResult(returncode=0, stdout="", stderr="")


def _item_raw(
    item_id: str,
    *,
    status: str = "open",
    labels: list[str] | None = None,
    issue_type: str = "task",
    title: str = "T",
) -> dict[str, object]:
    return {
        "id": item_id,
        "title": title,
        "issue_type": issue_type,
        "status": status,
        "priority": 2,
        "labels": labels or [],
        "dependencies": [],
        "dependents": [],
    }


def _show_result(*raw_items: dict[str, object]) -> BdResult:
    return BdResult(returncode=0, stdout=json.dumps(list(raw_items)), stderr="")


def _ready_result(*raw_items: dict[str, object]) -> BdResult:
    return BdResult(returncode=0, stdout=json.dumps(list(raw_items)), stderr="")


def _create_result(new_id: str) -> BdResult:
    return BdResult(
        returncode=0,
        stdout=json.dumps({"id": new_id, "schema_version": 3, "title": "T"}),
        stderr="",
    )


# --- claim ---------------------------------------------------------------


def test_claim_on_open_unblocked_leaf_sends_claim_and_returns_in_progress():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="open"))),
            ScriptedStep(("ready",), _ready_result(_item_raw("x.1", status="open"))),
            ScriptedStep(("update",), _OK),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["claim", "x.1"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "status": "in_progress"}
    assert runner.calls == [
        ("show", "x.1", "--json"),
        ("ready", "--json", "--limit", "0"),
        ("update", "x.1", "--claim"),
    ]


def test_claim_on_childless_epic_is_not_claimable_with_no_ready_or_claim_call():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("x.1", status="open", labels=["shape-epic"])),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["claim", "x.1"], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.NOT_CLAIMABLE)
    assert runner.calls == [("show", "x.1", "--json")]


def test_claim_on_impl_container_is_not_claimable_by_label():
    # A multi-unit reconciled sub-container carries `shape-impl-container`;
    # `claim` refuses it exactly like any other container, keyed on the label
    # (never child count) -- the new handle joins the declared container set, so
    # the guard trips before the `ready` set is even consulted.
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("x.1", status="open", labels=["shape-impl-container"])),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["claim", "x.1"], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.NOT_CLAIMABLE)
    assert runner.calls == [("show", "x.1", "--json")]


def test_claim_on_leaf_absent_from_ready_set_is_not_claimable_blocked():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="open"))),
            ScriptedStep(("ready",), _ready_result()),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["claim", "x.1"], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.NOT_CLAIMABLE)
    assert "blocked" in error["message"]
    assert runner.calls == [
        ("show", "x.1", "--json"),
        ("ready", "--json", "--limit", "0"),
    ]


def test_claim_on_already_in_progress_is_a_noop_with_no_claim_call():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="in_progress"))),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["claim", "x.1"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "status": "in_progress"}
    assert runner.calls == [("show", "x.1", "--json")]


def test_claim_on_closed_item_is_not_claimable():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="closed"))),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["claim", "x.1"], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.NOT_CLAIMABLE)
    assert runner.calls == [("show", "x.1", "--json")]


# --- release ---------------------------------------------------------------


def test_release_on_in_progress_sets_status_open():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="in_progress"))),
            ScriptedStep(("update",), _OK),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["release", "x.1"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "status": "open"}
    assert runner.calls == [
        ("show", "x.1", "--json"),
        ("update", "x.1", "--status", "open"),
    ]


def test_release_on_already_open_is_a_noop():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="open"))),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["release", "x.1"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "status": "open"}
    assert runner.calls == [("show", "x.1", "--json")]


def test_release_on_closed_is_usage_error():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="closed"))),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["release", "x.1"], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)
    assert runner.calls == [("show", "x.1", "--json")]


# --- plan --------------------------------------------------------------


def test_plan_done_on_container_with_children_adds_planned_label():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("x.1", status="open", labels=["shape-spec"])),
            ),
            ScriptedStep(("label", "add"), _OK),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["plan", "x.1", "--done"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "planned": True}
    assert runner.calls == [
        ("show", "x.1", "--json"),
        ("label", "add", "x.1", "planned"),
    ]


def test_plan_done_on_childless_noncontainer_without_force_is_usage_error():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="open"))),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["plan", "x.1", "--done"], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)
    assert runner.calls == [("show", "x.1", "--json")]


def test_plan_done_with_force_on_noncontainer_stamps_planned():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="open"))),
            ScriptedStep(("label", "add"), _OK),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["plan", "x.1", "--done", "--force"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "planned": True}
    assert runner.calls == [
        ("show", "x.1", "--json"),
        ("label", "add", "x.1", "planned"),
    ]


def test_plan_done_already_planned_is_a_noop():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("x.1", status="open", labels=["shape-spec", "planned"])),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["plan", "x.1", "--done"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "planned": True}
    assert runner.calls == [("show", "x.1", "--json")]


def test_plan_undo_removes_planned_label():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("label", "remove"), _OK)])

    exit_code, envelope, _ = run_cli_with_runner(["plan", "x.1", "--undo"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "planned": False}
    assert runner.calls == [("label", "remove", "x.1", "planned")]


def test_plan_with_neither_done_nor_undo_is_usage_error():
    exit_code, envelope, _ = run_cli(["plan", "x.1"], steps=[])

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)


def test_plan_with_both_done_and_undo_is_usage_error():
    exit_code, envelope, _ = run_cli(["plan", "x.1", "--done", "--undo"], steps=[])

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)


# --- promote --------------------------------------------------------------


def test_promote_shape_feat_leaf_mints_spec_shape_in_order_planned_stamped_last():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("x.1", status="open", labels=["shape-feat"], title="T")),
            ),
            ScriptedStep(("label", "add"), _OK),  # shape-spec
            ScriptedStep(("label", "remove"), _OK),  # shape-feat
            ScriptedStep(("create",), _create_result("x.2")),  # design child
            ScriptedStep(("create",), _create_result("x.3")),  # placeholder
            ScriptedStep(("label", "add"), _OK),  # planned
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["promote", "x.1"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "promoted": "spec"}
    assert runner.calls == [
        ("show", "x.1", "--json"),
        ("label", "add", "x.1", "shape-spec"),
        ("label", "remove", "x.1", "shape-feat"),
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
    ]
    # No reparent/new-parent call on x.1 itself -- id, parent, and edges
    # untouched (L16/plan item 10).
    assert not any(call[:2] == ("update", "x.1") for call in runner.calls)


def test_promote_on_non_feat_item_is_usage_error():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="open"))),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["promote", "x.1"], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)
    assert runner.calls == [("show", "x.1", "--json")]


def test_promote_already_shape_spec_is_a_noop():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("x.1", status="open", labels=["shape-feat", "shape-spec"])),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["promote", "x.1"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "promoted": "spec"}
    assert runner.calls == [("show", "x.1", "--json")]
