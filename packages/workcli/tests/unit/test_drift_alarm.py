"""The drift alarm (spec test-plan item 9): whenever bd's actual output shape
no longer matches what the parser expects, the facade raises
`WorkError(BACKEND_DRIFT)` naming exactly what broke -- never a silent
best-effort guess.

This file covers the parse-level core (malformed/renamed/missing shape).
Task 3 adds the end-to-end case (a scripted `show` response driving the
`show` verb all the way to an `E_BACKEND_DRIFT` envelope).
"""

from __future__ import annotations

import json

import pytest

from workcli.adapters.bd.parse import parse_items, parse_labels
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


def test_label_list_element_that_is_not_a_string_raises_backend_drift():
    with pytest.raises(WorkError) as exc_info:
        parse_labels(json.dumps([1, 2]))

    error = exc_info.value
    assert error.code == ErrorCode.BACKEND_DRIFT
    assert error.detail["reason"] == "label_not_a_string"
