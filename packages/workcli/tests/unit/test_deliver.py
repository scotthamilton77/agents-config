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


# --- deliver (leaf + usage guards) -----------------------------------------
# Design-path reconciliation is covered state-based in test_recovery.py; this
# file keeps the CLI-envelope, usage-guard, evidence, and backend-drift tests.


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


def test_deliver_on_impl_container_is_usage_error_pointing_to_close_walk():
    # A multi-unit reconciled sub-container (`shape-impl-container`, no
    # `shape-design`) completes by close-walk when its children close, never by
    # `deliver`. The guard trips at dispatch, before any evidence check or leaf
    # mutation -- only `show` is called.
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("x.1", status="open", labels=["shape-impl-container"])),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["deliver", "x.1"], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)
    assert runner.calls == [("show", "x.1", "--json")]


def test_deliver_on_spec_container_is_usage_error():
    # The guard is the declared-state container test (`is_container`), not the
    # new label alone: a `shape-spec` container is refused identically.
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("x.1", status="open", labels=["shape-spec"])),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["deliver", "x.1"], runner)

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)
    assert runner.calls == [("show", "x.1", "--json")]


def test_deliver_design_with_leaf_flags_is_usage_error_naming_them():
    # --pr/--items/--trivial belong to leaf delivery; a design child rejects
    # them rather than silently ignoring them (fail fast at the boundary).
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

    exit_code, envelope, _ = run_cli_with_runner(
        ["deliver", "d.1", "--spec", "S", "--pr", "https://example/pr/1", "--trivial"], runner
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)
    assert "--pr" in error["message"]
    assert "--trivial" in error["message"]
    assert runner.calls == [("show", "d.1", "--json")]


def test_deliver_design_with_items_flag_is_usage_error():
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

    exit_code, envelope, _ = run_cli_with_runner(
        ["deliver", "d.1", "--spec", "S", "--items", "a,b"], runner
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)
    assert "--items" in error["message"]
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


# --- deliver (design path) sibling-placeholder drift ------------------------


def test_deliver_design_null_parent_is_backend_drift():
    # A design child with no parent container breaks the spec-shape invariant
    # (`instantiate_spec_shape` always mints it under a container). The drift
    # is detected before any parent fetch, so d.1 is the only show call.
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("d.1", status="open", labels=["shape-design"])),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["deliver", "d.1", "--spec", "S"], runner, read_file=fake_reader({})
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.BACKEND_DRIFT)
    assert error["detail"] == {"design_id": "d.1"}
    assert runner.calls == [("show", "d.1", "--json")]


def test_deliver_design_zero_siblings_is_backend_drift():
    # Container holds only the design child -- no placeholder to reconcile.
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
                _show_result(_item_raw("c.1", status="open", children=["d.1"])),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["deliver", "d.1", "--spec", "S"], runner, read_file=fake_reader({})
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.BACKEND_DRIFT)
    assert error["detail"] == {
        "design_id": "d.1",
        "container_id": "c.1",
        "sibling_ids": [],
    }
    assert runner.calls == [("show", "d.1", "--json"), ("show", "c.1", "--json")]


def test_deliver_design_multiple_siblings_is_backend_drift():
    # Container holds the design child plus two non-design children -- the
    # sibling placeholder is ambiguous, so the id set is surfaced for repair.
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
                _show_result(_item_raw("c.1", status="open", children=["d.1", "p.1", "p.2"])),
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["deliver", "d.1", "--spec", "S"], runner, read_file=fake_reader({})
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.BACKEND_DRIFT)
    assert error["detail"] == {
        "design_id": "d.1",
        "container_id": "c.1",
        "sibling_ids": ["p.1", "p.2"],
    }
    assert runner.calls == [("show", "d.1", "--json"), ("show", "c.1", "--json")]


# --- deliver (design path) recorded-spec drift ------------------------------


def test_deliver_design_spec_mismatch_refuses_before_any_mutation():
    # A partial/previous run already recorded `[work] spec: old` on the
    # placeholder; re-running with a different --spec would reconcile against
    # the new file while leaving the recorded path stale, so later
    # `work reconcile` reads the wrong manifest. Refuse with a USAGE error
    # before parsing the spec or mutating anything.
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
                        labels=["impl-placeholder"],
                        notes=f"{SPEC_MARKER} old.md",
                    )
                ),
            ),
        ]
    )

    # Empty reader: reaching parse_continuations for "new.md" would KeyError,
    # proving the refusal fires before any spec read.
    exit_code, envelope, _ = run_cli_with_runner(
        ["deliver", "d.1", "--spec", "new.md"], runner, read_file=fake_reader({})
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)
    assert "old.md" in error["message"]
    assert "new.md" in error["message"]
    assert error["detail"] == {
        "design_id": "d.1",
        "placeholder_id": "p.1",
        "recorded_spec": "old.md",
        "requested_spec": "new.md",
    }
    assert runner.calls == [
        ("show", "d.1", "--json"),
        ("show", "c.1", "--json"),
        ("show", "p.1", "--json"),
    ]


# --- deliver (leaf path) ----------------------------------------------------


def test_deliver_leaf_with_spec_flag_is_usage_error():
    # --spec belongs to design delivery; a leaf rejects it rather than
    # silently ignoring it. Rejection precedes the already-closed/evidence
    # checks -- flag validation happens at the boundary.
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",), _show_result(_item_raw("x.1", status="open", labels=["shape-feat"]))
            ),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["deliver", "x.1", "--spec", "S", "--pr", "https://example/pr/1"], runner
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)
    assert "--spec" in error["message"]
    assert runner.calls == [("show", "x.1", "--json")]


def test_deliver_leaf_with_pr_appends_delivered_note_then_closes():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",), _show_result(_item_raw("x.1", status="open", labels=["shape-feat"]))
            ),
            ScriptedStep(("update",), _OK),  # delivered note
            ScriptedStep(("close",), _OK),
            # close-walk parent probe (S2-D5): parentless -> nothing walked
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="closed"))),
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
        ("show", "x.1", "--json"),
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


def test_deliver_leaf_already_closed_skips_evidence_but_replays_the_walk():
    # No evidence check on a closed leaf -- but the close-walk re-runs
    # (idempotent): a crash between close and walk must not strand exhausted
    # parents open behind a "successful" replay (S2-D5).
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="closed"))),
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="closed"))),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["deliver", "x.1"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "status": "closed"}
    assert runner.calls == [("show", "x.1", "--json"), ("show", "x.1", "--json")]


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
            # close-walk parent probe (S2-D5): parentless -> nothing walked
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="closed"))),
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
        ("show", "x.1", "--json"),
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
            # close-walk parent probe (S2-D5): parentless -> nothing walked
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="closed"))),
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
        ("show", "x.1", "--json"),
    ]


def test_deliver_leaf_with_trivial_appends_trivial_evidence_then_closes():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",), _show_result(_item_raw("x.1", status="open", labels=["shape-chore"]))
            ),
            ScriptedStep(("update",), _OK),  # delivered note
            ScriptedStep(("close",), _OK),
            # close-walk parent probe (S2-D5): parentless -> nothing walked
            ScriptedStep(("show",), _show_result(_item_raw("x.1", status="closed"))),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["deliver", "x.1", "--trivial"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1", "status": "closed"}
    assert runner.calls == [
        ("show", "x.1", "--json"),
        ("update", "x.1", "--append-notes", f"{DELIVERED_MARKER} trivial"),
        ("close", "x.1"),
        ("show", "x.1", "--json"),
    ]


# --- reconcile_placeholder edge cases reached via replay --------------------
