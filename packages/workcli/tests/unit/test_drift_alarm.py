"""The drift alarm (spec test-plan item 9): whenever bd's actual output shape
no longer matches what the parser expects, the facade raises
`WorkError(BACKEND_DRIFT)` naming exactly what broke -- never a silent
best-effort guess.

This file covers both the parse-level core (malformed/renamed/missing shape)
and the end-to-end case: a scripted `show` response driving the `show` verb
all the way through the real CLI to an `E_BACKEND_DRIFT` envelope, exit 1.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import run_cli
from tests.fakes import ScriptedStep
from workcli.adapters.bd.parse import parse_dep_edges, parse_items, parse_labels
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode, WorkError


def test_missing_required_key_raises_backend_drift_naming_the_key():
    raw_item = {"id": "x.1", "title": "t", "issue_type": "task", "priority": 2}
    # `status` is missing entirely.

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["missing_keys"] == ["status"]


def test_renamed_required_key_raises_backend_drift_naming_the_key():
    # If bd renames `issue_type` -> `type` in some future release, that is
    # indistinguishable from "the field went missing" to this parser -- and
    # it must be caught, not silently defaulted.
    raw_item = {"id": "x.1", "title": "t", "type": "task", "status": "open", "priority": 2}

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    assert exc_info.value.detail["missing_keys"] == ["issue_type"]


def test_non_array_show_payload_raises_backend_drift():
    # The real not-found shape bd emits on stdout when a lookup fails
    # entirely (`{"error": ..., "schema_version": 1}`) -- a JSON object,
    # not the expected array. Nonzero-exit not-found is mapped from stderr
    # before parsing is ever reached (BdBackend.get, Task 2 below); this
    # covers any other case where bd's stdout is an object instead of a list.
    payload = json.dumps(
        {"error": "no issues found matching the provided IDs", "schema_version": 1}
    )

    with pytest.raises(WorkError) as exc_info:
        parse_items(payload)

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "not_an_array"


def test_non_json_stdout_raises_backend_drift_with_raw_excerpt():
    with pytest.raises(WorkError) as exc_info:
        parse_items("not json at all {{{")

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "invalid_json"
    assert "not json at all" in error.detail["raw_excerpt"]


def test_non_integer_priority_raises_backend_drift():
    # bd's real schema always emits priority as an int (0-4); a string like
    # "P2" would silently produce a mangled "PP2" priority if not caught.
    raw_item = {"id": "x.1", "title": "t", "issue_type": "task", "status": "open", "priority": "P2"}

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "unexpected_priority_type"


def test_array_element_that_is_not_an_object_raises_backend_drift():
    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps(["not-an-object"]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "element_not_an_object"


def test_explicit_null_dependencies_field_raises_backend_drift_not_a_raw_type_error():
    # bd emitting `"dependencies": null` where the facade's model says array
    # is itself model drift -- must never surface as a raw AssertionError/
    # TypeError from an unguarded `isinstance` check (Finding 2).
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "dependencies": None,
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "null_field"
    assert error.detail["field"] == "dependencies"


def test_explicit_null_dependents_field_raises_backend_drift_not_a_raw_type_error():
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "dependents": None,
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "null_field"
    assert error.detail["field"] == "dependents"


def test_explicit_null_labels_field_raises_backend_drift_not_a_raw_type_error():
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "labels": None,
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "null_field"
    assert error.detail["field"] == "labels"


def test_explicit_null_title_field_raises_backend_drift_not_the_literal_string_none():
    # Codex review finding on PR #314: title/issue_type are required scalars
    # that shared the same unguarded `str(raw["title"])` gap the null-vs-
    # absent discipline was meant to close everywhere.
    raw_item = {
        "id": "x.1",
        "title": None,
        "issue_type": "task",
        "status": "open",
        "priority": 2,
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "null_field"
    assert error.detail["field"] == "title"


def test_explicit_null_issue_type_field_raises_backend_drift_not_the_literal_string_none():
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": None,
        "status": "open",
        "priority": 2,
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "null_field"
    assert error.detail["field"] == "issue_type"


def test_explicit_null_dependency_edge_status_raises_backend_drift_not_the_literal_string_none():
    # Codex review finding on PR #314: the show-shape dependency edge's
    # `status` field went through an unguarded `str(entry.get("status", ""))`
    # that coerced an explicit null to the literal string "None".
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "dependencies": [{"id": "x.2", "dependency_type": "blocks", "status": None}],
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "null_field"
    assert error.detail["field"] == "status"


def test_explicit_null_status_field_raises_backend_drift_not_the_literal_string_none():
    # bd emitting `"status": null` must never silently become the literal
    # string "None" via an unguarded `str(raw["status"])` -- same null-vs-
    # absent discipline as `_list_field`, extended to scalar fields.
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "task",
        "status": None,
        "priority": 2,
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "null_field"
    assert error.detail["field"] == "status"


def test_explicit_null_description_field_raises_backend_drift_not_the_literal_string_none():
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "description": None,
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "null_field"
    assert error.detail["field"] == "description"


def test_missing_description_field_defaults_to_empty_string_not_drift():
    # Absent is NOT the same as explicit null: an absent `description` key
    # keeps its "" default, same as `_list_field`'s absent-key behavior.
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
    }

    items = parse_items(json.dumps([raw_item]))

    assert items[0].description == ""


def test_explicit_null_notes_field_raises_backend_drift_not_the_literal_string_none():
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "notes": None,
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "null_field"
    assert error.detail["field"] == "notes"


def test_explicit_null_dependency_type_field_raises_backend_drift_not_the_literal_string_none():
    # The show-shape dependency edge's `dependency_type` field going explicitly
    # null must alarm, never silently coerce to the literal string "None" via
    # an unguarded `str(entry.get(...))`.
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "dependencies": [{"id": "x.2", "status": "open", "dependency_type": None}],
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "null_field"
    assert error.detail["field"] == "dependency_type"


def test_explicit_null_type_field_fallback_raises_backend_drift_not_the_literal_string_none():
    # The list-shape edge row's `type` field (used as `dependency_type`'s
    # fallback when the key is absent, not when it's explicitly null) going
    # null must alarm the same way.
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "dependencies": [{"issue_id": "x.1", "depends_on_id": "x.2", "type": None}],
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "null_field"
    assert error.detail["field"] == "type"


def test_non_string_label_element_raises_backend_drift_not_a_silent_coercion():
    # bd emitting a non-string element in `labels` (a number, an object, ...)
    # where the normalized contract says `string[]` is model drift -- it must
    # alarm, never be silently coerced to a string via `str()` (spec test-plan
    # item 9), matching parse_labels' discipline for the `label list` command.
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "labels": ["real-label", 42],
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "non_string_list_element"
    assert error.detail["field"] == "labels"


def test_non_list_dependencies_field_raises_backend_drift_naming_the_field():
    # Neither absent (defaults to []) nor null (its own drift case above) --
    # bd handing back some other non-array shape (e.g. a single object) for
    # `dependencies` is the same alarm class.
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "dependencies": {"unexpected": "shape"},
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "unexpected_field_type"
    assert error.detail["field"] == "dependencies"


def test_label_list_element_that_is_not_a_string_raises_backend_drift():
    with pytest.raises(WorkError) as exc_info:
        parse_labels(json.dumps([1, 2]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "label_not_a_string"


def test_dep_list_element_that_is_not_an_object_raises_backend_drift():
    with pytest.raises(WorkError) as exc_info:
        parse_dep_edges(json.dumps(["not-an-object"]), self_id="x.1")

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "element_not_an_object"


def test_dep_list_element_missing_dependency_type_raises_backend_drift():
    # A dep-list record without `dependency_type` is bd emitting the
    # list-shape raw edge row for a command that's only ever produced the
    # show-shape in the golden fixtures -- catch it rather than guess.
    raw_entry = {"id": "x.2", "status": "open"}

    with pytest.raises(WorkError) as exc_info:
        parse_dep_edges(json.dumps([raw_entry]), self_id="x.1")

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "missing_required_keys"


def test_dep_list_explicit_null_dependency_type_raises_backend_drift():
    # `parse_dep_edges` (the `work dep list` path) builds its `DepEdge.type`
    # straight from `_dep_edge_from_raw` without going through `parse_item`'s
    # filtering `_dep_type` call -- an explicit null here must still alarm,
    # not silently coerce to the literal string "None" via an unguarded
    # `str(entry["dependency_type"])`.
    raw_entry = {"id": "x.2", "status": "open", "dependency_type": None}

    with pytest.raises(WorkError) as exc_info:
        parse_dep_edges(json.dumps([raw_entry]), self_id="x.1")

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "null_field"
    assert error.detail["field"] == "dependency_type"


def test_show_shape_dependency_edge_missing_id_raises_backend_drift():
    # A `dependencies[]` entry carrying `dependency_type` (show-shape) but no
    # `id` for the other end would raise a raw KeyError -> E_INTERNAL from
    # `_dep_edge_from_raw`'s direct indexing. It must alarm as BACKEND_DRIFT
    # like every other unmappable shape (spec test-plan item 9).
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "dependencies": [{"dependency_type": "blocks"}],  # no `id` for the other end
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "missing_edge_keys"
    assert error.detail["missing_keys"] == ["id"]


def test_list_shape_dependency_edge_missing_edge_key_raises_backend_drift():
    # A list-shape raw edge row (no `dependency_type`) missing `depends_on_id`
    # would raise a raw KeyError -> E_INTERNAL from the ternary's direct
    # indexing. It must alarm as BACKEND_DRIFT, naming the missing key.
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "dependencies": [{"type": "blocks", "issue_id": "x.1"}],  # no `depends_on_id`
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "missing_edge_keys"
    assert error.detail["missing_keys"] == ["depends_on_id"]


def test_parent_child_dependent_missing_id_raises_backend_drift():
    # A `dependents[]` parent-child record (the shape that becomes `children`)
    # carrying `dependency_type` but no `id` for the other end would raise a
    # raw KeyError -> E_INTERNAL from `children`'s direct indexing. It must
    # alarm as BACKEND_DRIFT like the `dependencies[]` show-shape edge does
    # (spec test-plan item 9).
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "epic",
        "status": "open",
        "priority": 2,
        "dependents": [{"dependency_type": "parent-child"}],  # no `id` for the child
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "missing_edge_keys"
    assert error.detail["missing_keys"] == ["id"]


def test_non_object_dependency_entry_raises_backend_drift_not_a_silent_drop():
    # A `dependencies[]` entry that isn't a JSON object (e.g. a bare string)
    # was previously filtered out silently by `isinstance(entry, dict)` and
    # continued with a partially-mangled Item -- that is bd shape drift, not
    # something to drop and carry on from (spec test-plan item 9).
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "dependencies": ["not-an-object"],
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "element_not_an_object"
    assert error.detail["field"] == "dependencies"


def test_non_object_dependent_entry_raises_backend_drift_not_a_silent_drop():
    # Same discipline for `dependents[]` -- the source of `children` -- as
    # `dependencies[]` above.
    raw_item = {
        "id": "x.1",
        "title": "t",
        "issue_type": "epic",
        "status": "open",
        "priority": 2,
        "dependents": [42],
    }

    with pytest.raises(WorkError) as exc_info:
        parse_items(json.dumps([raw_item]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "element_not_an_object"
    assert error.detail["field"] == "dependents"


def test_show_verb_end_to_end_surfaces_backend_drift_envelope_on_garbage_shape():
    # A garbage `show` shape (missing every required key) drives the CLI's
    # own catch: `handler -> WorkError(BACKEND_DRIFT) -> emit_failure`, not
    # `E_INTERNAL` -- the parser's own typed error, not an unhandled crash.
    exit_code, envelope, stderr_text = run_cli(
        ["show", "x.1"],
        steps=[
            ScriptedStep(
                ("show",),
                BdResult(returncode=0, stdout=json.dumps([{"unexpected": "shape"}]), stderr=""),
            )
        ],
    )

    assert exit_code == 1
    assert stderr_text == ""
    assert envelope["ok"] is False
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.BACKEND_DRIFT)
