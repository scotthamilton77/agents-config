"""BdBackend: the Backend protocol's bd implementation, over a BdRunner.

Task 2 wired the read primitives (`capabilities`, `get`, `batch_get`,
`query`); Task 4 adds the write primitives (`create`, `set_fields`,
`append_note`, `close`, `reopen`) -- relation/sync primitives still land in
Task 5. Every test here drives a `ScriptedBdRunner`, never a real subprocess.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.backend import BdBackend
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode, WorkError
from workcli.model import CreateFields, QueryFilters, UpdateFields

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_capabilities_are_all_true_for_bd():
    backend = BdBackend(ScriptedBdRunner(steps=[]))

    caps = backend.capabilities

    assert caps.supports_ready is True
    assert caps.supports_dep_types is True
    assert caps.supports_sync is True


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
        )
    ]


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
