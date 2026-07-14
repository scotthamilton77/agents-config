"""`reconcile` -- bd-observable recovery sweep (plan Task 6, test-plan items 7, 11).

Enumerates candidates only through queryable handles (`query()`-sourced Items
carry `children == []` -- bd `list` has no `dependents` key) and `get()`s each
candidate before reading children/deps/notes (L10). All call-log assertions go
through `run_cli_with_runner` (conftest.py) since `run_cli` discards its
runner and exposes no `.calls`.
"""

from __future__ import annotations

import json

from tests.conftest import fake_reader, run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
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


def _list_result(*raw_items: dict[str, object]) -> BdResult:
    return BdResult(returncode=0, stdout=json.dumps(list(raw_items)), stderr="")


def _show_result(*raw_items: dict[str, object]) -> BdResult:
    return BdResult(returncode=0, stdout=json.dumps(list(raw_items)), stderr="")


def _create_result(new_id: str) -> BdResult:
    return BdResult(
        returncode=0,
        stdout=json.dumps({"id": new_id, "schema_version": 3, "title": "T"}),
        stderr="",
    )


_MANIFEST_MULTI = """## Continuations
- feat: Widget A — AC: a works
- bugfix: Widget B — AC: b works
- chore: Widget C — AC: c works
"""

_MANIFEST_SINGLE = """## Continuations
- feat: Widget X — AC: it works
"""


# --- interrupted-deliver leaf (item 11, case 1) -----------------------------


def test_reconcile_closes_in_progress_leaf_carrying_delivered_marker():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("list",),
                _list_result(_item_raw("x.1", status="in_progress")),
            ),
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw(
                        "x.1",
                        status="in_progress",
                        notes=f"{DELIVERED_MARKER} https://example/pr/1",
                    )
                ),
            ),
            ScriptedStep(("close",), _OK),
            ScriptedStep(("list",), _list_result()),  # impl-placeholder sweep
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["reconcile"], runner)

    assert exit_code == 0
    assert envelope["data"] == {
        "findings": [{"id": "x.1", "kind": "interrupted_deliver", "repaired": True}]
    }
    assert runner.calls == [
        ("list", "--json", "--status", "in_progress", "--limit", "0"),
        ("show", "x.1", "--json"),
        ("close", "x.1"),
        ("list", "--json", "--label", "impl-placeholder", "--limit", "0"),
    ]


def test_reconcile_rerun_over_healed_interrupted_deliver_tree_is_a_noop():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("list",), _list_result()),  # in_progress sweep: none open
            ScriptedStep(("list",), _list_result()),  # impl-placeholder sweep
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["reconcile"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"findings": []}
    assert runner.calls == [
        ("list", "--json", "--status", "in_progress", "--limit", "0"),
        ("list", "--json", "--label", "impl-placeholder", "--limit", "0"),
    ]


def test_reconcile_ignores_in_progress_leaf_without_delivered_marker():
    """An ordinary in-progress leaf (no delivered note) is not a finding at all."""
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("list",), _list_result(_item_raw("x.1", status="in_progress"))),
            ScriptedStep(
                ("show",), _show_result(_item_raw("x.1", status="in_progress"))
            ),  # no delivered marker
            ScriptedStep(("list",), _list_result()),  # impl-placeholder sweep
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["reconcile"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"findings": []}
    assert runner.calls == [
        ("list", "--json", "--status", "in_progress", "--limit", "0"),
        ("show", "x.1", "--json"),
        ("list", "--json", "--label", "impl-placeholder", "--limit", "0"),
    ]


# --- unreconciled placeholder / interrupted expansion (item 7) -------------


def test_reconcile_mints_missing_children_for_interrupted_expansion():
    """1 of 3 manifest children already minted + a closed design sibling +
    a `[work] spec:` note -> reconcile mints only the 2 missing children then
    removes `impl-placeholder`."""
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("list",), _list_result()),  # in_progress sweep: none
            ScriptedStep(
                ("list",),
                _list_result(_item_raw("p.1", labels=["impl-placeholder"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw(
                        "p.1",
                        labels=["impl-placeholder"],
                        parent="c.1",
                        notes=f"{SPEC_MARKER} S",
                    )
                ),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("c.1", children=["d.1", "p.1"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("d.1", status="closed", labels=["shape-design"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw(
                        "p.1",
                        labels=["impl-placeholder"],
                        parent="c.1",
                        notes=f"{SPEC_MARKER} S",
                        children=["e.1"],
                    )
                ),
            ),
            ScriptedStep(("show",), _show_result(_item_raw("e.1", title="Widget A"))),
            ScriptedStep(("create",), _create_result("u.2")),
            ScriptedStep(("create",), _create_result("u.3")),
            ScriptedStep(("label", "remove"), _OK),  # impl-placeholder, strictly last
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["reconcile"], runner, read_file=fake_reader({"S": _MANIFEST_MULTI})
    )

    assert exit_code == 0
    assert envelope["data"] == {
        "findings": [{"id": "p.1", "kind": "unreconciled_placeholder", "repaired": True}]
    }
    assert runner.calls == [
        ("list", "--json", "--status", "in_progress", "--limit", "0"),
        ("list", "--json", "--label", "impl-placeholder", "--limit", "0"),
        ("show", "p.1", "--json"),
        ("show", "c.1", "--json"),
        ("show", "d.1", "--json"),
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
    ]


def test_reconcile_skips_placeholder_whose_design_sibling_is_still_open():
    """A design child not yet closed means the placeholder is legitimately
    blocked -- no finding at all, no manifest re-parse, no mutation."""
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("list",), _list_result()),  # in_progress sweep: none
            ScriptedStep(
                ("list",),
                _list_result(_item_raw("p.1", labels=["impl-placeholder"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("p.1", labels=["impl-placeholder"], parent="c.1")),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("c.1", children=["d.1", "p.1"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("d.1", status="open", labels=["shape-design"])),
            ),
        ]
    )

    # No path scripted in the fake reader -- a manifest re-parse would blow
    # up loudly on the KeyError, proving the skip happens before that.
    exit_code, envelope, _ = run_cli_with_runner(["reconcile"], runner, read_file=fake_reader({}))

    assert exit_code == 0
    assert envelope["data"] == {"findings": []}
    assert runner.calls == [
        ("list", "--json", "--status", "in_progress", "--limit", "0"),
        ("list", "--json", "--label", "impl-placeholder", "--limit", "0"),
        ("show", "p.1", "--json"),
        ("show", "c.1", "--json"),
        ("show", "d.1", "--json"),
    ]


def test_reconcile_reports_needs_spec_without_mutation_when_spec_marker_absent():
    """Design sibling closed but no `[work] spec:` note recorded on the
    placeholder -- reported as a finding, no manifest to parse, no mutation."""
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("list",), _list_result()),  # in_progress sweep: none
            ScriptedStep(
                ("list",),
                _list_result(_item_raw("p.1", labels=["impl-placeholder"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("p.1", labels=["impl-placeholder"], parent="c.1")),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("c.1", children=["d.1", "p.1"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("d.1", status="closed", labels=["shape-design"])),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["reconcile"], runner, read_file=fake_reader({}))

    assert exit_code == 0
    assert envelope["data"] == {
        "findings": [{"id": "p.1", "kind": "needs_spec", "repaired": False}]
    }
    assert runner.calls == [
        ("list", "--json", "--status", "in_progress", "--limit", "0"),
        ("list", "--json", "--label", "impl-placeholder", "--limit", "0"),
        ("show", "p.1", "--json"),
        ("show", "c.1", "--json"),
        ("show", "d.1", "--json"),
    ]


def test_reconcile_dry_run_reports_findings_with_zero_mutating_calls():
    """`--dry-run` collects findings across both sweeps but performs no
    `close`/`create`/`label`/`update` calls -- every scripted step is a read
    (`list`/`show`) only."""
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("list",),
                _list_result(_item_raw("x.1", status="in_progress")),
            ),
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw(
                        "x.1",
                        status="in_progress",
                        notes=f"{DELIVERED_MARKER} https://example/pr/1",
                    )
                ),
            ),
            ScriptedStep(
                ("list",),
                _list_result(_item_raw("p.1", labels=["impl-placeholder"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw(
                        "p.1",
                        labels=["impl-placeholder"],
                        parent="c.1",
                        notes=f"{SPEC_MARKER} S",
                    )
                ),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("c.1", children=["d.1", "p.1"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("d.1", status="closed", labels=["shape-design"])),
            ),
        ]
    )

    # No path scripted -- --dry-run must never reach parse_continuations/read_file.
    exit_code, envelope, _ = run_cli_with_runner(
        ["reconcile", "--dry-run"], runner, read_file=fake_reader({})
    )

    assert exit_code == 0
    assert envelope["data"] == {
        "findings": [
            {"id": "x.1", "kind": "interrupted_deliver", "repaired": False},
            {"id": "p.1", "kind": "unreconciled_placeholder", "repaired": False},
        ]
    }
    mutating_prefixes = {"close", "create", "label", "update"}
    assert not any(call[0] in mutating_prefixes for call in runner.calls)
    assert runner.calls == [
        ("list", "--json", "--status", "in_progress", "--limit", "0"),
        ("show", "x.1", "--json"),
        ("list", "--json", "--label", "impl-placeholder", "--limit", "0"),
        ("show", "p.1", "--json"),
        ("show", "c.1", "--json"),
        ("show", "d.1", "--json"),
    ]


# --- design-sibling resolution edge cases -----------------------------------


def test_reconcile_skips_orphan_placeholder_with_no_parent():
    """A parentless placeholder has no container to find a design sibling
    under -- treated as legitimately blocked (skipped), not a crash."""
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("list",), _list_result()),  # in_progress sweep: none
            ScriptedStep(
                ("list",),
                _list_result(_item_raw("p.1", labels=["impl-placeholder"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("p.1", labels=["impl-placeholder"], parent=None)),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["reconcile"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"findings": []}
    assert runner.calls == [
        ("list", "--json", "--status", "in_progress", "--limit", "0"),
        ("list", "--json", "--label", "impl-placeholder", "--limit", "0"),
        ("show", "p.1", "--json"),
    ]


def test_reconcile_skips_own_id_and_non_design_children_before_finding_design_sibling():
    """The container's children include the placeholder's own id (skipped
    without a bd call) and an unrelated child with no `shape-design` label
    (fetched and passed over) before the real design sibling. The `[work]
    spec:` note itself has an unrelated leading line, exercising the note
    scan past a non-matching line too."""
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("list",), _list_result()),  # in_progress sweep: none
            ScriptedStep(
                ("list",),
                _list_result(_item_raw("p.1", labels=["impl-placeholder"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw(
                        "p.1",
                        labels=["impl-placeholder"],
                        parent="c.1",
                        notes=f"unrelated note\n{SPEC_MARKER} S",
                    )
                ),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("c.1", children=["p.1", "junk.1", "d.1"])),
            ),
            ScriptedStep(("show",), _show_result(_item_raw("junk.1"))),  # no shape-design label
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("d.1", status="closed", labels=["shape-design"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(
                    _item_raw(
                        "p.1",
                        labels=["impl-placeholder"],
                        parent="c.1",
                        notes=f"unrelated note\n{SPEC_MARKER} S",
                    )
                ),
            ),
            ScriptedStep(("update",), _OK),  # set_type
            ScriptedStep(("update",), _OK),  # set_fields title
            ScriptedStep(("update",), _OK),  # set_acceptance
            ScriptedStep(("label", "remove"), _OK),  # impl-placeholder
            ScriptedStep(("label", "add"), _OK),  # shape-feat
            ScriptedStep(("label", "add"), _OK),  # spec-ready
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["reconcile"], runner, read_file=fake_reader({"S": _MANIFEST_SINGLE})
    )

    assert exit_code == 0
    assert envelope["data"] == {
        "findings": [{"id": "p.1", "kind": "unreconciled_placeholder", "repaired": True}]
    }
    assert runner.calls == [
        ("list", "--json", "--status", "in_progress", "--limit", "0"),
        ("list", "--json", "--label", "impl-placeholder", "--limit", "0"),
        ("show", "p.1", "--json"),
        ("show", "c.1", "--json"),
        ("show", "junk.1", "--json"),
        ("show", "d.1", "--json"),
        ("show", "p.1", "--json"),
        ("update", "p.1", "--type", "feature"),
        ("update", "p.1", "--title", "Widget X"),
        ("update", "p.1", "--acceptance", "it works"),
        ("label", "remove", "p.1", "impl-placeholder"),
        ("label", "add", "p.1", "shape-feat"),
        ("label", "add", "p.1", "spec-ready"),
    ]


def test_reconcile_skips_placeholder_when_no_design_sibling_found_at_all():
    """The container's children carry no `shape-design` label anywhere (a
    corrupted/incomplete container) -- the sibling search exhausts and the
    placeholder is skipped, not reconciled against a nonexistent design
    gate."""
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("list",), _list_result()),  # in_progress sweep: none
            ScriptedStep(
                ("list",),
                _list_result(_item_raw("p.1", labels=["impl-placeholder"])),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("p.1", labels=["impl-placeholder"], parent="c.1")),
            ),
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("c.1", children=["p.1", "other.1"])),
            ),
            ScriptedStep(("show",), _show_result(_item_raw("other.1"))),  # no shape-design label
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["reconcile"], runner, read_file=fake_reader({}))

    assert exit_code == 0
    assert envelope["data"] == {"findings": []}
    assert runner.calls == [
        ("list", "--json", "--status", "in_progress", "--limit", "0"),
        ("list", "--json", "--label", "impl-placeholder", "--limit", "0"),
        ("show", "p.1", "--json"),
        ("show", "c.1", "--json"),
        ("show", "other.1", "--json"),
    ]
