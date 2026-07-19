"""BdBackend: the Backend protocol's bd implementation, over a BdRunner.

Task 2 wired the read primitives (`capabilities`, `get`, `batch_get`,
`query`); Task 4 added the write primitives (`create`, `set_fields`,
`append_note`, `close`, `reopen`); Task 5 adds the relation/sync primitives
(`dep_mutate`, `dep_list`, `label_mutate`, `labels`, `sync`). Every test here
drives a `ScriptedBdRunner`, never a real subprocess.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.backend import BdBackend
from workcli.adapters.bd.runner import BdResult
from workcli.backend import ReadySupport, SyncSupport
from workcli.envelope import ErrorCode, WorkError
from workcli.model import CreateFields, DepEdge, QueryFilters, UpdateFields

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_capabilities_are_all_native_for_bd():
    backend = BdBackend(ScriptedBdRunner(steps=[]))

    caps = backend.capabilities

    assert caps.ready is ReadySupport.NATIVE
    assert caps.sync is SyncSupport.NATIVE
    assert caps.supports_dep_write is True


def test_get_sends_show_json_and_returns_the_normalized_item():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show", "agents-config-wgclw.9.1", "--json"),
                BdResult(returncode=0, stdout=_read("bd_show_wgclw9.1.json"), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    item = backend.get("agents-config-wgclw.9.1")

    assert item.id == "agents-config-wgclw.9.1"
    assert runner.calls == [("show", "agents-config-wgclw.9.1", "--json")]


def test_get_maps_no_issue_found_stderr_to_not_found_error():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "bogus-id"\n'),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.get("bogus-id")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.NOT_FOUND


def test_get_maps_an_unrecognized_nonzero_exit_to_backend_drift_with_diagnostic_detail():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("show",), BdResult(returncode=2, stdout="", stderr="boom: segfault"))]
    )
    backend = BdBackend(runner)

    try:
        backend.get("x.1")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT
        assert error.detail["returncode"] == 2
        assert "segfault" in error.detail["stderr"]
        assert error.detail["argv"] == ["show", "x.1", "--json"]


def test_batch_get_raises_not_found_when_bd_silently_omits_a_requested_id():
    # Empirically confirmed against the real bd binary: `bd show valid bogus
    # --json` exits 0 and returns only the valid item, logging the miss to
    # stderr rather than failing the whole call -- the facade must not treat
    # that as success (decision 10 needs `data.items` to match the request).
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show", "agents-config-wgclw.9.1", "bogus-id", "--json"),
                BdResult(returncode=0, stdout=_read("bd_show_wgclw9.1.json"), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.batch_get(["agents-config-wgclw.9.1", "bogus-id"])
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.NOT_FOUND
        assert error.detail["missing"] == ["bogus-id"]


def test_batch_get_returns_items_in_the_requested_id_order_even_when_bd_does_not():
    # bd's own `bd show a b --json` output order is not asserted anywhere to
    # match argv order -- batch_get's contract promises request order
    # regardless (Finding 1 remediation), since callers positionally unpack
    # the result (e.g. verbs/relations.py's type-wall pre-check).
    payload = [
        {"id": "b.2", "title": "t2", "issue_type": "task", "status": "open", "priority": 2},
        {"id": "a.1", "title": "t1", "issue_type": "task", "status": "open", "priority": 1},
    ]
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show", "a.1", "b.2", "--json"),
                BdResult(returncode=0, stdout=json.dumps(payload), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    items = backend.batch_get(["a.1", "b.2"])

    assert [item.id for item in items] == ["a.1", "b.2"]


def test_batch_get_maps_a_duplicated_requested_id_to_the_same_item_twice():
    payload = [
        {"id": "a.1", "title": "t1", "issue_type": "task", "status": "open", "priority": 1},
    ]
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


def test_query_defaults_to_limit_zero_meaning_unbounded():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("list", "--json"),
                BdResult(returncode=0, stdout=_read("bd_list_open_limit5.json"), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    items = backend.query(QueryFilters())

    assert len(items) == 5
    assert runner.calls == [("list", "--json", "--limit", "0")]


def test_query_passes_through_a_positive_limit_and_the_status_filter():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("list", "--json"),
                BdResult(returncode=0, stdout="[]", stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    backend.query(QueryFilters(status="open", limit=7))

    assert runner.calls == [("list", "--json", "--status", "open", "--limit", "7")]


def test_query_passes_through_the_label_parent_and_type_filters():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("list", "--json"),
                BdResult(returncode=0, stdout="[]", stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    backend.query(QueryFilters(label="tech-debt", parent="x.1", type="task"))

    assert runner.calls == [
        (
            "list",
            "--json",
            "--label",
            "tech-debt",
            "--parent",
            "x.1",
            "--type",
            "task",
            "--limit",
            "0",
        )
    ]


def test_query_maps_an_unrecognized_nonzero_exit_to_backend_drift():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("list", "--json"),
                BdResult(returncode=1, stdout="", stderr="boom: out of memory"),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.query(QueryFilters())
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT


def test_ready_defaults_to_limit_zero_meaning_unbounded():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("ready", "--json"),
                BdResult(returncode=0, stdout=_read("bd_list_open_limit5.json"), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    items = backend.ready(None)

    assert len(items) == 5
    assert runner.calls == [("ready", "--json", "--limit", "0")]


def test_ready_passes_through_the_label_filter():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("ready", "--json"), BdResult(returncode=0, stdout="[]", stderr=""))]
    )
    backend = BdBackend(runner)

    backend.ready("tech-debt")

    assert runner.calls == [("ready", "--json", "--label", "tech-debt", "--limit", "0")]


def test_ready_maps_an_unrecognized_nonzero_exit_to_backend_drift():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("ready", "--json"),
                BdResult(returncode=1, stdout="", stderr="boom: out of memory"),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.ready(None)
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT


def test_search_sends_the_query_and_returns_normalized_items():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("search", "quarantine", "--json"),
                BdResult(returncode=0, stdout=_read("bd_list_open_limit5.json"), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    items = backend.search("quarantine")

    assert len(items) == 5
    assert runner.calls == [("search", "quarantine", "--json")]


def test_search_maps_an_unrecognized_nonzero_exit_to_backend_drift():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("search",),
                BdResult(returncode=1, stdout="", stderr="boom: out of memory"),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.search("x")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT


def test_create_sends_title_and_json_and_returns_the_new_id():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("create",),
                BdResult(
                    returncode=0,
                    stdout=json.dumps({"id": "x.5", "schema_version": 3, "title": "T"}),
                    stderr="",
                ),
            )
        ]
    )
    backend = BdBackend(runner)

    new_id = backend.create(CreateFields(title="T"))

    assert new_id == "x.5"
    assert runner.calls == [("create", "--json", "--title", "T")]


def test_create_includes_description_type_priority_and_parent_when_provided():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("create",),
                BdResult(returncode=0, stdout=json.dumps({"id": "x.6"}), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    backend.create(
        CreateFields(title="T", description="D", type="bug", priority="P1", parent="parent.1")
    )

    assert runner.calls == [
        (
            "create",
            "--json",
            "--title",
            "T",
            "--description",
            "D",
            "--type",
            "bug",
            "--priority",
            "P1",
            "--parent",
            "parent.1",
            "--no-inherit-labels",
        )
    ]


def test_create_disables_bd_label_inheritance_only_for_parented_creates():
    # bd copies the parent's current labels onto a --parent child by default
    # (verified against bd 1.0.3), which leaked transient handles like
    # `creating-spec` onto spec children (wgclw.9.8). The Backend contract is
    # "the created item carries exactly the requested labels", so every
    # parented create opts out; an unparented create has nothing to inherit
    # and stays flag-free.
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("create",),
                BdResult(returncode=0, stdout=json.dumps({"id": "x.8"}), stderr=""),
            ),
            ScriptedStep(
                ("create",),
                BdResult(returncode=0, stdout=json.dumps({"id": "x.9"}), stderr=""),
            ),
        ]
    )
    backend = BdBackend(runner)

    backend.create(CreateFields(title="kid", parent="parent.1", labels=("only",)))
    backend.create(CreateFields(title="solo", labels=("only",)))

    parented, unparented = runner.calls
    assert "--no-inherit-labels" in parented
    assert "--no-inherit-labels" not in unparented


def test_create_joins_labels_into_one_comma_separated_labels_flag():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("create",),
                BdResult(returncode=0, stdout=json.dumps({"id": "x.7"}), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    backend.create(CreateFields(title="T", labels=("a", "b", "c")))

    assert runner.calls == [("create", "--json", "--title", "T", "--labels", "a,b,c")]


def test_create_maps_no_issue_found_stderr_to_not_found_error():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("create",),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "p.1"\n'),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.create(CreateFields(title="T", parent="p.1"))
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.NOT_FOUND


def test_create_maps_an_unrecognized_nonzero_exit_to_backend_drift():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("create",), BdResult(returncode=1, stdout="", stderr="boom"))]
    )
    backend = BdBackend(runner)

    try:
        backend.create(CreateFields(title="T"))
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT


def test_create_raises_backend_drift_when_the_json_payload_has_no_id():
    # bd create --json emits a single object, not an array -- a payload
    # missing `id` (or that isn't an object at all) is the same alarm class
    # as any other unrecognized bd shape, never a silent empty-string id.
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("create",),
                BdResult(returncode=0, stdout=json.dumps({"schema_version": 3}), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.create(CreateFields(title="T"))
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT


def test_create_raises_backend_drift_when_the_json_payload_is_an_array():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("create",),
                BdResult(returncode=0, stdout=json.dumps([{"id": "x.1"}]), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.create(CreateFields(title="T"))
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT


def test_create_raises_backend_drift_when_stdout_is_not_json_at_all():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("create",),
                BdResult(returncode=0, stdout="not json at all", stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.create(CreateFields(title="T"))
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT


def test_set_fields_sends_only_the_provided_replace_flags():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("update",), BdResult(returncode=0, stdout="", stderr=""))]
    )
    backend = BdBackend(runner)

    backend.set_fields("x.1", UpdateFields(title="New title", priority="P0"))

    assert runner.calls == [("update", "x.1", "--title", "New title", "--priority", "P0")]


def test_set_fields_sends_description_when_provided():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("update",), BdResult(returncode=0, stdout="", stderr=""))]
    )
    backend = BdBackend(runner)

    backend.set_fields("x.1", UpdateFields(description="New description"))

    assert runner.calls == [("update", "x.1", "--description", "New description")]


def test_set_fields_maps_no_issue_found_stderr_to_not_found_error():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("update",),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "x.1"\n'),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.set_fields("x.1", UpdateFields(title="T"))
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.NOT_FOUND


def test_append_note_sends_the_append_notes_flag_never_the_bare_replace_flag():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("update",), BdResult(returncode=0, stdout="", stderr=""))]
    )
    backend = BdBackend(runner)

    backend.append_note("x.1", "some progress")

    assert runner.calls == [("update", "x.1", "--append-notes", "some progress")]


def test_append_note_maps_no_issue_found_stderr_to_not_found_error():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("update",),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "x.1"\n'),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.append_note("x.1", "text")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.NOT_FOUND


def test_close_sends_close_with_all_ids_in_one_call():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("close",), BdResult(returncode=0, stdout="", stderr=""))]
    )
    backend = BdBackend(runner)

    backend.close(["a.1", "a.2", "a.3"])

    assert runner.calls == [("close", "a.1", "a.2", "a.3")]


def test_close_maps_no_issue_found_stderr_to_not_found_error():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("close",),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "a.1"\n'),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.close(["a.1"])
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.NOT_FOUND


def test_reopen_sends_reopen_with_the_id():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("reopen",), BdResult(returncode=0, stdout="", stderr=""))]
    )
    backend = BdBackend(runner)

    backend.reopen("a.1")

    assert runner.calls == [("reopen", "a.1")]


def test_reopen_maps_no_issue_found_stderr_to_not_found_error():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("reopen",),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "a.1"\n'),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.reopen("a.1")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.NOT_FOUND


def test_dep_mutate_add_sends_dep_add_with_from_to_and_type():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("dep", "add"), BdResult(returncode=0, stdout="", stderr=""))]
    )
    backend = BdBackend(runner)

    backend.dep_mutate("add", "x.1", "x.2", "blocks")

    assert runner.calls == [("dep", "add", "x.1", "x.2", "--type", "blocks")]


def test_dep_mutate_remove_sends_dep_remove_with_no_type_flag():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("dep", "remove"), BdResult(returncode=0, stdout="", stderr=""))]
    )
    backend = BdBackend(runner)

    backend.dep_mutate("remove", "x.1", "x.2", "blocks")

    assert runner.calls == [("dep", "remove", "x.1", "x.2")]


def test_dep_mutate_rejects_an_invalid_op_and_records_no_bd_invocation():
    # Finding 2: an `op` outside {"add", "remove"} must fail loud, never
    # silently fall through to the destructive `dep remove` branch.
    runner = ScriptedBdRunner(steps=[])
    backend = BdBackend(runner)

    try:
        backend.dep_mutate("bogus", "x.1", "x.2", "blocks")  # type: ignore[arg-type]
        raise AssertionError("expected ValueError")
    except ValueError as error:
        assert "bogus" in str(error)
    assert runner.calls == []


def test_dep_mutate_maps_a_cycle_stderr_to_dep_cycle():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("dep", "add"),
                BdResult(
                    returncode=1, stdout="", stderr="adding dependency would create a cycle\n"
                ),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.dep_mutate("add", "x.1", "x.2", "blocks")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.DEP_CYCLE


def test_dep_mutate_maps_a_type_wall_stderr_to_type_wall():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("dep", "add"),
                BdResult(
                    returncode=1, stdout="", stderr="epics can only block other epics, not tasks\n"
                ),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.dep_mutate("add", "x.1", "x.2", "blocks")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.TYPE_WALL


def test_dep_list_sends_down_then_up_and_maps_into_depends_on_and_dependents():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("dep", "list", "agents-config-wgclw.9.1", "--json"),
                BdResult(
                    returncode=0,
                    stdout=_read("bd_dep_list_down.json"),
                    stderr="",
                ),
            ),
            ScriptedStep(
                ("dep", "list", "agents-config-wgclw.9.1", "--direction", "up", "--json"),
                BdResult(
                    returncode=0,
                    stdout=_read("bd_dep_list_up.json"),
                    stderr="",
                ),
            ),
        ]
    )
    backend = BdBackend(runner)

    listing = backend.dep_list("agents-config-wgclw.9.1")

    assert listing.depends_on == [
        DepEdge(id="agents-config-wgclw.9", type="parent-child", status="open")
    ]
    assert listing.dependents == [
        DepEdge(id="agents-config-wgclw.9.2", type="blocks", status="open")
    ]
    assert runner.calls == [
        ("dep", "list", "agents-config-wgclw.9.1", "--json"),
        ("dep", "list", "agents-config-wgclw.9.1", "--direction", "up", "--json"),
    ]


def test_dep_list_maps_an_unrecognized_nonzero_exit_on_the_down_call_to_backend_drift():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("dep", "list"), BdResult(returncode=1, stdout="", stderr="boom"))]
    )
    backend = BdBackend(runner)

    try:
        backend.dep_list("x.1")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT


def test_dep_list_maps_an_unrecognized_nonzero_exit_on_the_up_call_to_backend_drift():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("dep", "list", "x.1", "--json"), BdResult(returncode=0, stdout="[]", stderr="")
            ),
            ScriptedStep(
                ("dep", "list", "x.1", "--direction", "up", "--json"),
                BdResult(returncode=1, stdout="", stderr="boom"),
            ),
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.dep_list("x.1")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT


def test_label_mutate_add_sends_one_bd_call_per_label():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("label", "add"), BdResult(returncode=0, stdout="", stderr="")),
            ScriptedStep(("label", "add"), BdResult(returncode=0, stdout="", stderr="")),
        ]
    )
    backend = BdBackend(runner)

    backend.label_mutate("add", "x.1", ["a", "b"])

    assert runner.calls == [("label", "add", "x.1", "a"), ("label", "add", "x.1", "b")]


def test_label_mutate_remove_sends_one_bd_call_per_label():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("label", "remove"), BdResult(returncode=0, stdout="", stderr=""))]
    )
    backend = BdBackend(runner)

    backend.label_mutate("remove", "x.1", ["stale"])

    assert runner.calls == [("label", "remove", "x.1", "stale")]


def test_label_mutate_maps_no_issue_found_stderr_to_not_found_error():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("label", "add"),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "x.1"\n'),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.label_mutate("add", "x.1", ["a"])
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.NOT_FOUND


def test_label_mutate_wraps_a_mid_sequence_failure_with_partial_progress():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("label", "add"), BdResult(returncode=0, stdout="", stderr="")),
            ScriptedStep(("label", "add"), BdResult(returncode=1, stdout="", stderr="boom")),
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.label_mutate("add", "x.1", ["a", "b", "c"])
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.detail["partial_progress"] == {
            "operation": "label_mutate",
            "steps_total": 3,
            "completed": ["a"],
            "failed": "b",
            "remaining": ["c"],
        }


def test_label_mutate_wraps_retry_exhaustion_with_partial_progress():
    # Codex review finding on PR #319: run_with_retry itself raises WorkError
    # on retry exhaustion (E_LOCK_CONTENTION/E_TIMEOUT) rather than returning
    # a BdResult -- that path bypassed the `returncode != 0` branch entirely,
    # so a label already applied before it went unreported.
    locked = BdResult(returncode=1, stdout="", stderr="database is locked")
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("label", "add"), BdResult(returncode=0, stdout="", stderr="")),
            ScriptedStep(("label", "add"), locked),
            ScriptedStep(("label", "add"), locked),
            ScriptedStep(("label", "add"), locked),
        ]
    )
    backend = BdBackend(runner, sleep=lambda _seconds: None)

    try:
        backend.label_mutate("add", "x.1", ["a", "b", "c"])
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.LOCK_CONTENTION
        assert error.detail["partial_progress"] == {
            "operation": "label_mutate",
            "steps_total": 3,
            "completed": ["a"],
            "failed": "b",
            "remaining": ["c"],
        }


def test_label_mutate_failing_on_the_first_label_carries_no_partial_progress():
    # AC 9: "absence means atomic" applies even to the first sub-step of a
    # multi-step op when nothing preceded it.
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("label", "add"), BdResult(returncode=1, stdout="", stderr="boom"))]
    )
    backend = BdBackend(runner)

    try:
        backend.label_mutate("add", "x.1", ["a", "b"])
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert "partial_progress" not in error.detail


def test_label_mutate_reinvocation_after_partial_failure_heals_and_completes():
    # Retry-from-top after a partial failure: label "a" is re-applied (bd
    # absorbs the already-present case) and "b"/"c" succeed this time.
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("label", "add"),
                BdResult(returncode=1, stdout="", stderr="issue x.1 already has label a\n"),
            ),
            ScriptedStep(("label", "add"), BdResult(returncode=0, stdout="", stderr="")),
            ScriptedStep(("label", "add"), BdResult(returncode=0, stdout="", stderr="")),
        ]
    )
    backend = BdBackend(runner)

    backend.label_mutate("add", "x.1", ["a", "b", "c"])  # must not raise

    assert runner.calls == [
        ("label", "add", "x.1", "a"),
        ("label", "add", "x.1", "b"),
        ("label", "add", "x.1", "c"),
    ]


def test_label_mutate_add_absorbs_already_present_stderr_as_success():
    # Marker text is speculative (live-verified against bd 1.0.3 as currently
    # unreachable -- a repeat `label add` exits 0 with no stderr; see the
    # marker constant's comment). Proves the absorption mechanism works if a
    # future bd version ever does error on this outcome.
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("label", "add"),
                BdResult(returncode=1, stdout="", stderr="issue x.1 already has label a\n"),
            )
        ]
    )
    backend = BdBackend(runner)

    backend.label_mutate("add", "x.1", ["a"])  # must not raise

    assert runner.calls == [("label", "add", "x.1", "a")]


def test_label_mutate_remove_absorbs_absent_stderr_as_success():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("label", "remove"),
                BdResult(returncode=1, stdout="", stderr="issue x.1 does not have label stale\n"),
            )
        ]
    )
    backend = BdBackend(runner)

    backend.label_mutate("remove", "x.1", ["stale"])  # must not raise

    assert runner.calls == [("label", "remove", "x.1", "stale")]


def test_set_status_failure_carries_no_partial_progress():
    # AC 9: a single-call primitive's WorkError never carries partial_progress.
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("update",), BdResult(returncode=1, stdout="", stderr="boom"))]
    )
    backend = BdBackend(runner)

    try:
        backend.set_status("x.1", "closed")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert "partial_progress" not in error.detail


def test_labels_sends_label_list_json_and_returns_the_flat_array():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("label", "list", "agents-config-wgclw.9.1", "--json"),
                BdResult(
                    returncode=0,
                    stdout=_read("bd_label_list_wgclw9.1.json"),
                    stderr="",
                ),
            )
        ]
    )
    backend = BdBackend(runner)

    labels = backend.labels("agents-config-wgclw.9.1")

    assert labels == ["implementation-ready", "shape-feat", "vision-85-5-10"]
    assert runner.calls == [("label", "list", "agents-config-wgclw.9.1", "--json")]


def test_labels_maps_an_unrecognized_nonzero_exit_to_backend_drift():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("label", "list"), BdResult(returncode=1, stdout="", stderr="boom"))]
    )
    backend = BdBackend(runner)

    try:
        backend.labels("x.1")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT


def test_sync_commits_then_pushes_and_returns_push_mode():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("dolt", "commit"), BdResult(returncode=0, stdout="", stderr="")),
            ScriptedStep(("dolt", "push"), BdResult(returncode=0, stdout="", stderr="")),
        ]
    )
    backend = BdBackend(runner)

    result = backend.sync(pull=False)

    assert result.synced is True
    assert result.mode == "push"
    assert runner.calls == [("dolt", "commit"), ("dolt", "push")]


def test_sync_commit_nothing_to_commit_still_pushes():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("dolt", "commit"),
                BdResult(returncode=1, stdout="", stderr="nothing to commit\n"),
            ),
            ScriptedStep(("dolt", "push"), BdResult(returncode=0, stdout="", stderr="")),
        ]
    )
    backend = BdBackend(runner)

    result = backend.sync(pull=False)

    assert result.synced is True
    assert runner.calls == [("dolt", "commit"), ("dolt", "push")]


def test_sync_commit_failure_with_unrecognized_stderr_raises_backend_drift():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("dolt", "commit"), BdResult(returncode=1, stdout="", stderr="boom"))]
    )
    backend = BdBackend(runner)

    try:
        backend.sync(pull=False)
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT


def test_sync_push_failure_raises_backend_drift():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("dolt", "commit"), BdResult(returncode=0, stdout="", stderr="")),
            ScriptedStep(("dolt", "push"), BdResult(returncode=1, stdout="", stderr="boom")),
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.sync(pull=False)
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT


def test_sync_push_failure_wraps_with_partial_progress_commit_completed():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("dolt", "commit"), BdResult(returncode=0, stdout="", stderr="")),
            ScriptedStep(("dolt", "push"), BdResult(returncode=1, stdout="", stderr="boom")),
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.sync(pull=False)
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.detail["partial_progress"] == {
            "operation": "sync",
            "steps_total": 2,
            "completed": ["commit"],
            "failed": "push",
            "remaining": [],
        }


def test_sync_wraps_push_retry_exhaustion_with_partial_progress():
    # Codex review finding on PR #319: run_with_retry itself raises WorkError
    # on retry exhaustion rather than returning a BdResult -- that path
    # bypassed the `returncode != 0` branch, leaving out `completed:["commit"]`
    # even though the commit had already succeeded.
    locked = BdResult(returncode=1, stdout="", stderr="database is locked")
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("dolt", "commit"), BdResult(returncode=0, stdout="", stderr="")),
            ScriptedStep(("dolt", "push"), locked),
            ScriptedStep(("dolt", "push"), locked),
            ScriptedStep(("dolt", "push"), locked),
        ]
    )
    backend = BdBackend(runner, sleep=lambda _seconds: None)

    try:
        backend.sync(pull=False)
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.LOCK_CONTENTION
        assert error.detail["partial_progress"] == {
            "operation": "sync",
            "steps_total": 2,
            "completed": ["commit"],
            "failed": "push",
            "remaining": [],
        }


def test_sync_commit_failure_carries_no_partial_progress():
    # AC 9: a multi-step primitive failing on step 1 (nothing completed) also
    # carries no partial_progress key.
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("dolt", "commit"), BdResult(returncode=1, stdout="", stderr="boom"))]
    )
    backend = BdBackend(runner)

    try:
        backend.sync(pull=False)
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert "partial_progress" not in error.detail


def test_sync_reinvocation_after_push_failure_completes():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("dolt", "commit"), BdResult(returncode=1, stdout="", stderr="nothing to commit\n")
            ),
            ScriptedStep(("dolt", "push"), BdResult(returncode=0, stdout="", stderr="")),
        ]
    )
    backend = BdBackend(runner)

    result = backend.sync(pull=False)  # must not raise: re-commit is a no-op, push succeeds

    assert result.synced is True


def test_sync_pull_sends_dolt_pull_and_returns_pull_mode():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("dolt", "pull"), BdResult(returncode=0, stdout="", stderr=""))]
    )
    backend = BdBackend(runner)

    result = backend.sync(pull=True)

    assert result.synced is True
    assert result.mode == "pull"
    assert runner.calls == [("dolt", "pull")]


def test_sync_pull_with_dirty_working_set_raises_sync_behind():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("dolt", "pull"),
                BdResult(returncode=1, stdout="", stderr="cannot merge with uncommitted changes\n"),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.sync(pull=True)
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.SYNC_BEHIND


def test_sync_pull_maps_an_unrecognized_nonzero_exit_to_backend_drift():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("dolt", "pull"), BdResult(returncode=1, stdout="", stderr="boom"))]
    )
    backend = BdBackend(runner)

    try:
        backend.sync(pull=True)
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT
