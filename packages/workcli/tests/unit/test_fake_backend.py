"""Sanity checks for `FakeBackend` -- the fidelity properties every recovery
test leans on. Deliberately minimal: this pins the seam behaviors that would
otherwise turn a fake bug into a false green/red in the real tests, not the
fake's every accessor.
"""

from __future__ import annotations

import pytest

from tests.fake_backend import FakeBackend
from workcli.envelope import ErrorCode, WorkError
from workcli.model import CreateFields, QueryFilters


def test_get_reports_children_but_query_is_lean():
    # bd `list` carries no children key, so reconcile re-get()s every
    # candidate; the fake must reproduce that or a children-trusting
    # regression would pass silently.
    backend = FakeBackend()
    backend.add("parent").add("child", parent="parent", labels=["impl-placeholder"])

    assert backend.get("parent").children == ["child"]

    [lean] = backend.query(QueryFilters(label="impl-placeholder"))
    assert lean.id == "child"
    assert lean.children == []
    assert lean.deps == []


def test_create_assigns_id_and_wires_into_parent_children():
    backend = FakeBackend()
    backend.add("container")

    new_id = backend.create(CreateFields(title="minted", type="task", parent="container"))

    assert new_id in backend.get("container").children
    assert backend.get(new_id).title == "minted"


def test_label_and_status_mutations_are_observable_through_get():
    backend = FakeBackend()
    backend.add("x", labels=["impl-placeholder"], status="open")

    backend.label_mutate("add", "x", ["spec-ready"])
    backend.label_mutate("remove", "x", ["impl-placeholder"])
    backend.close(["x"])

    item = backend.get("x")
    assert item.labels == ["spec-ready"]
    assert item.status == "closed"


def test_append_note_is_line_wise_and_missing_item_raises_not_found():
    backend = FakeBackend()
    backend.add("x", notes="first")

    backend.append_note("x", "[work] manifest: {}")
    assert backend.note_lines("x") == ["first", "[work] manifest: {}"]

    with pytest.raises(WorkError) as exc_info:
        backend.get("ghost")
    assert exc_info.value.code == ErrorCode.NOT_FOUND
