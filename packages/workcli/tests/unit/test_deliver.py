"""`deliver` -- evidence-gated leaf delivery + design-spec placeholder
reconciliation (plan Task 5, test-plan items 4, 5, 6).

DESIGN path dispatches on the `shape-design` label: it locates the sibling
placeholder under the design child's parent (the container always has
exactly the two children `instantiate_spec_shape` minted -- L9), records the
`[work] spec:` marker on the placeholder, reconciles it against the parsed
`## Continuations` manifest, then closes the design child. LEAF path
verifies bd-observable evidence (`--items` existence via `batch_get`,
`--pr` caller-attested, `--trivial`) before recording the
`[work] delivered:` marker and closing. All call-log assertions go through
`run_cli_with_runner` (conftest.py) since `run_cli` discards its runner and
exposes no `.calls`.
"""

from __future__ import annotations

import json

from tests.conftest import fake_reader, run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode
from workcli.lifecycle import DELIVERED_MARKER, SPEC_MARKER

_OK = BdResult(returncode=0, stdout="", stderr="")


def _item_raw(
    item_id: str,
    *,
    status: str = "open",
    labels: list[str] | None = None,
    issue_type: str = "task",
    title: str = "T",
    parent: str | None = None,
    notes: str = "",
    children: list[str] | None = None,
) -> dict[str, object]:
    dependents = [
        {"id": child_id, "dependency_type": "parent-child", "status": "open"}
        for child_id in (children or [])
    ]
    return {
        "id": item_id,
        "title": title,
        "issue_type": issue_type,
        "status": status,
        "priority": 2,
        "labels": labels or [],
        "parent": parent,
        "notes": notes,
        "dependencies": [],
        "dependents": dependents,
    }


def _show_result(*raw_items: dict[str, object]) -> BdResult:
    return BdResult(returncode=0, stdout=json.dumps(list(raw_items)), stderr="")


def _create_result(new_id: str) -> BdResult:
    return BdResult(
        returncode=0,
        stdout=json.dumps({"id": new_id, "schema_version": 3, "title": "T"}),
        stderr="",
    )


_MANIFEST_SINGLE = """## Continuations
- feat: Widget X — AC: it works
"""

_MANIFEST_MULTI = """## Continuations
- feat: Widget A — AC: a works
- bugfix: Widget B — AC: b works
- chore: Widget C — AC: c works
"""

_MANIFEST_NONE = """## Continuations
- none — this spec is the deliverable
"""


# --- deliver (design path) -------------------------------------------------


def test_deliver_design_single_unit_reconciles_placeholder_then_closes_design():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw("d.1", status="open", labels=["shape-design"], parent="c.1")
                ),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("c.1", status="open", children=["d.1", "p.1"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("p.1", status="open", labels=["impl-placeholder"])),
            ),
            ScriptedStep(("update",), _OK),  # append [work] spec: S note
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("p.1", status="open", labels=["impl-placeholder"])),
            ),
            ScriptedStep(("update",), _OK),  # set_type
            ScriptedStep(("update",), _OK),  # set_fields title
            ScriptedStep(("update",), _OK),  # set_acceptance
            ScriptedStep(("label", "remove"), _OK),  # impl-placeholder
            ScriptedStep(("label", "add"), _OK),  # shape-feat
            ScriptedStep(("label", "add"), _OK),  # spec-ready
            ScriptedStep(("close",), _OK),  # design child
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["deliver", "d.1", "--spec", "S"],
        runner,
        read_file=fake_reader({"S": _MANIFEST_SINGLE}),
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "d.1", "status": "closed"}
    assert runner.calls == [
        ("show", "d.1", "--json"),
        ("show", "c.1", "--json"),
        ("show", "p.1", "--json"),
        ("update", "p.1", "--append-notes", f"{SPEC_MARKER} S"),
        ("show", "p.1", "--json"),
        ("update", "p.1", "--type", "feature"),
        ("update", "p.1", "--title", "Widget X"),
        ("update", "p.1", "--acceptance", "it works"),
        ("label", "remove", "p.1", "impl-placeholder"),
        ("label", "add", "p.1", "shape-feat"),
        ("label", "add", "p.1", "spec-ready"),
        ("close", "d.1"),
    ]


def test_deliver_design_without_spec_is_usage_error_with_no_bd_call():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw("d.1", status="open", labels=["shape-design"], parent="c.1")
                ),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["deliver", "d.1"], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)
    assert runner.calls == [("show", "d.1", "--json")]


def test_deliver_design_replay_after_full_reconciliation_is_a_noop():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw("d.1", status="closed", labels=["shape-design"], parent="c.1")
                ),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("c.1", status="open", children=["d.1", "p.1"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("p.1", status="open", labels=["shape-feat", "spec-ready"])),
            ),
        ]
    )

    # No path scripted in the fake reader -- a manifest re-parse would blow
    # up loudly on the KeyError, proving the no-op short-circuits before it.
    exit_code, envelope, _ = run_cli_with_runner(
        ["deliver", "d.1", "--spec", "S"], runner, read_file=fake_reader({})
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "d.1", "status": "closed"}
    assert runner.calls == [
        ("show", "d.1", "--json"),
        ("show", "c.1", "--json"),
        ("show", "p.1", "--json"),
    ]


def test_deliver_design_multi_unit_mints_all_then_removes_placeholder_label_last():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw("d.1", status="open", labels=["shape-design"], parent="c.1")
                ),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("c.1", status="open", children=["d.1", "p.1"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("p.1", status="open", labels=["impl-placeholder"])),
            ),
            ScriptedStep(("update",), _OK),  # append [work] spec: S note
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("p.1", status="open", labels=["impl-placeholder"])),
            ),
            ScriptedStep(("create",), _create_result("u.1")),
            ScriptedStep(("create",), _create_result("u.2")),
            ScriptedStep(("create",), _create_result("u.3")),
            ScriptedStep(("label", "remove"), _OK),  # impl-placeholder, strictly last
            ScriptedStep(("close",), _OK),  # design child
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["deliver", "d.1", "--spec", "S"],
        runner,
        read_file=fake_reader({"S": _MANIFEST_MULTI}),
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "d.1", "status": "closed"}
    assert runner.calls == [
        ("show", "d.1", "--json"),
        ("show", "c.1", "--json"),
        ("show", "p.1", "--json"),
        ("update", "p.1", "--append-notes", f"{SPEC_MARKER} S"),
        ("show", "p.1", "--json"),
        (
            "create",
            "--json",
            "--title",
            "Widget A",
            "--type",
            "feature",
            "--parent",
            "p.1",
            "--labels",
            "shape-feat",
            "--acceptance",
            "a works",
        ),
        (
            "create",
            "--json",
            "--title",
            "Widget B",
            "--type",
            "bug",
            "--parent",
            "p.1",
            "--labels",
            "shape-bugfix",
            "--acceptance",
            "b works",
        ),
        (
            "create",
            "--json",
            "--title",
            "Widget C",
            "--type",
            "chore",
            "--parent",
            "p.1",
            "--labels",
            "shape-chore",
            "--acceptance",
            "c works",
        ),
        ("label", "remove", "p.1", "impl-placeholder"),
        ("close", "d.1"),
    ]


def test_deliver_design_none_manifest_closes_placeholder_with_reason_note():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw("d.1", status="open", labels=["shape-design"], parent="c.1")
                ),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("c.1", status="open", children=["d.1", "p.1"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("p.1", status="open", labels=["impl-placeholder"])),
            ),
            ScriptedStep(("update",), _OK),  # append [work] spec: S note
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("p.1", status="open", labels=["impl-placeholder"])),
            ),
            ScriptedStep(("close",), _OK),  # placeholder
            ScriptedStep(("update",), _OK),  # none-reason note
            ScriptedStep(("close",), _OK),  # design child
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["deliver", "d.1", "--spec", "S"],
        runner,
        read_file=fake_reader({"S": _MANIFEST_NONE}),
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "d.1", "status": "closed"}
    assert runner.calls == [
        ("show", "d.1", "--json"),
        ("show", "c.1", "--json"),
        ("show", "p.1", "--json"),
        ("update", "p.1", "--append-notes", f"{SPEC_MARKER} S"),
        ("show", "p.1", "--json"),
        ("close", "p.1"),
        ("update", "p.1", "--append-notes", "this spec is the deliverable"),
        ("close", "d.1"),
    ]


# --- deliver (leaf path) ----------------------------------------------------


def test_deliver_leaf_with_pr_appends_delivered_note_then_closes():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",), _show_result(_item_raw("x.1", status="open", labels=["shape-feat"]))
            ),
            ScriptedStep(("update",), _OK),  # delivered note
            ScriptedStep(("close",), _OK),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["deliver", "x.1", "--pr", "https://example/pr/1"], runner
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "status": "closed"}
    assert runner.calls == [
        ("show", "x.1", "--json"),
        ("update", "x.1", "--append-notes", f"{DELIVERED_MARKER} https://example/pr/1"),
        ("close", "x.1"),
    ]


def test_deliver_leaf_with_missing_items_translates_not_found_to_evidence():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",), _show_result(_item_raw("x.1", status="open", labels=["shape-feat"]))
            ),
            ScriptedStep(
                ("show",), _show_result(_item_raw("x", status="closed"))
            ),  # batch_get x,y -- y missing
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["deliver", "x.1", "--items", "x,y"], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.EVIDENCE)
    assert runner.calls == [
        ("show", "x.1", "--json"),
        ("show", "x", "y", "--json"),
    ]


def test_deliver_leaf_with_no_evidence_flag_is_evidence_error():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",), _show_result(_item_raw("x.1", status="open", labels=["shape-feat"]))
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["deliver", "x.1"], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.EVIDENCE)
    assert runner.calls == [("show", "x.1", "--json")]


def test_deliver_leaf_already_closed_is_a_noop_with_no_evidence_check():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="closed"))),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["deliver", "x.1"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "status": "closed"}
    assert runner.calls == [("show", "x.1", "--json")]


def test_deliver_leaf_interrupted_replay_skips_duplicate_note_and_just_closes():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw(
                        "x.1",
                        status="open",
                        labels=["shape-feat"],
                        notes=f"{DELIVERED_MARKER} https://example/pr/1",
                    )
                ),
            ),
            ScriptedStep(("close",), _OK),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["deliver", "x.1", "--pr", "https://example/pr/1"], runner
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "status": "closed"}
    assert runner.calls == [
        ("show", "x.1", "--json"),
        ("close", "x.1"),
    ]


def test_deliver_leaf_items_batch_get_non_not_found_error_propagates_unchanged():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",), _show_result(_item_raw("x.1", status="open", labels=["shape-feat"]))
            ),
            ScriptedStep(
                ("show",), BdResult(returncode=1, stdout="", stderr="something bd never says")
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["deliver", "x.1", "--items", "x,y"], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.BACKEND_DRIFT)


def test_deliver_leaf_with_items_present_appends_items_evidence_then_closes():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",), _show_result(_item_raw("x.1", status="open", labels=["shape-feat"]))
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("a", status="closed"), _item_raw("b", status="closed")),
            ),
            ScriptedStep(("update",), _OK),  # delivered note
            ScriptedStep(("close",), _OK),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["deliver", "x.1", "--items", "a,b"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "status": "closed"}
    assert runner.calls == [
        ("show", "x.1", "--json"),
        ("show", "a", "b", "--json"),
        ("update", "x.1", "--append-notes", f"{DELIVERED_MARKER} items:a,b"),
        ("close", "x.1"),
    ]


def test_deliver_leaf_with_trivial_appends_trivial_evidence_then_closes():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",), _show_result(_item_raw("x.1", status="open", labels=["shape-chore"]))
            ),
            ScriptedStep(("update",), _OK),  # delivered note
            ScriptedStep(("close",), _OK),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["deliver", "x.1", "--trivial"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "status": "closed"}
    assert runner.calls == [
        ("show", "x.1", "--json"),
        ("update", "x.1", "--append-notes", f"{DELIVERED_MARKER} trivial"),
        ("close", "x.1"),
    ]


# --- reconcile_placeholder edge cases reached via replay --------------------


def test_deliver_design_interrupted_after_reconcile_before_close_finishes_close_only():
    """design still open (close never ran) but the placeholder is already fully
    reconciled and its `[work] spec:` note already recorded -- a replay must
    skip both the note and the reconciliation mutations and just close."""
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw("d.1", status="open", labels=["shape-design"], parent="c.1")
                ),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("c.1", status="open", children=["d.1", "p.1"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw(
                        "p.1",
                        status="open",
                        labels=["shape-feat", "spec-ready"],
                        notes=f"{SPEC_MARKER} S",
                    )
                ),
            ),
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw(
                        "p.1",
                        status="open",
                        labels=["shape-feat", "spec-ready"],
                        notes=f"{SPEC_MARKER} S",
                    )
                ),
            ),
            ScriptedStep(("close",), _OK),  # design child
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["deliver", "d.1", "--spec", "S"],
        runner,
        read_file=fake_reader({"S": _MANIFEST_SINGLE}),
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "d.1", "status": "closed"}
    assert runner.calls == [
        ("show", "d.1", "--json"),
        ("show", "c.1", "--json"),
        ("show", "p.1", "--json"),
        ("show", "p.1", "--json"),
        ("close", "d.1"),
    ]


def test_deliver_design_multi_unit_partial_mint_skips_existing_titles():
    """An interrupted expansion left one manifest child already minted under
    the placeholder; a replay must mint only the two missing ones."""
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw("d.1", status="open", labels=["shape-design"], parent="c.1")
                ),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("c.1", status="open", children=["d.1", "p.1"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("p.1", status="open", labels=["impl-placeholder"])),
            ),
            ScriptedStep(("update",), _OK),  # append [work] spec: S note
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw("p.1", status="open", labels=["impl-placeholder"], children=["e.1"])
                ),
            ),
            ScriptedStep(("show",), _show_result(_item_raw("e.1", title="Widget A"))),
            ScriptedStep(("create",), _create_result("u.2")),
            ScriptedStep(("create",), _create_result("u.3")),
            ScriptedStep(("label", "remove"), _OK),  # impl-placeholder, strictly last
            ScriptedStep(("close",), _OK),  # design child
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["deliver", "d.1", "--spec", "S"],
        runner,
        read_file=fake_reader({"S": _MANIFEST_MULTI}),
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "d.1", "status": "closed"}
    assert runner.calls == [
        ("show", "d.1", "--json"),
        ("show", "c.1", "--json"),
        ("show", "p.1", "--json"),
        ("update", "p.1", "--append-notes", f"{SPEC_MARKER} S"),
        ("show", "p.1", "--json"),
        ("show", "e.1", "--json"),
        (
            "create",
            "--json",
            "--title",
            "Widget B",
            "--type",
            "bug",
            "--parent",
            "p.1",
            "--labels",
            "shape-bugfix",
            "--acceptance",
            "b works",
        ),
        (
            "create",
            "--json",
            "--title",
            "Widget C",
            "--type",
            "chore",
            "--parent",
            "p.1",
            "--labels",
            "shape-chore",
            "--acceptance",
            "c works",
        ),
        ("label", "remove", "p.1", "impl-placeholder"),
        ("close", "d.1"),
    ]
