"""Contract tests for the in-memory reference WorkTracker adapter.

A miniature of the "fixture-test corpus" the core design spec requires of
every adapter. These pin the *behaviours* a `bd`/Jira/GitHub adapter must also
satisfy — marker advancement, provenance propagation, full-population
enumeration, hierarchy walks, audit-note accumulation — not the literal
storage shape.
"""

from __future__ import annotations

import pytest

from pdlc.worktracker import InMemoryWorkTracker, ObjectiveNotFoundError


def test_create_assigns_distinct_ids_and_propagates_originating_idea() -> None:
    tracker = InMemoryWorkTracker()
    first = tracker.create_objective(
        parent_id=None, objective_type="task", title="A", body="a", originating_idea_id="idea-7"
    )
    second = tracker.create_objective(parent_id=None, objective_type="task", title="B", body="b")

    assert first != second
    assert tracker.get_objective(first).originating_idea_id == "idea-7"
    assert tracker.get_objective(second).originating_idea_id is None


def test_discover_since_returns_only_changes_after_the_marker() -> None:
    tracker = InMemoryWorkTracker()
    objective_id = tracker.create_objective(
        parent_id=None, objective_type="task", title="A", body="a"
    )

    first_batch, marker = tracker.discover_since(None)
    assert [r.id for r in first_batch] == [objective_id]

    # Nothing changed since the marker -> empty delta, marker holds.
    empty_batch, same_marker = tracker.discover_since(marker)
    assert empty_batch == []
    assert same_marker == marker

    # A mutation bumps the version, so the same marker now surfaces it again.
    tracker.set_lifecycle_status(objective_id, "in_progress", "claimed")
    after_batch, _ = tracker.discover_since(marker)
    assert [r.id for r in after_batch] == [objective_id]


def test_list_all_ids_enumerates_every_status_not_just_open() -> None:
    # The full-reconcile correctness primitive: closed objectives must still
    # enumerate, or drift across the full population goes undetected.
    tracker = InMemoryWorkTracker()
    open_id = tracker.create_objective(parent_id=None, objective_type="task", title="O", body="o")
    closed_id = tracker.create_objective(parent_id=None, objective_type="task", title="C", body="c")
    tracker.set_lifecycle_status(closed_id, "closed", "merged")

    assert set(tracker.list_all_ids()) == {open_id, closed_id}


def test_bulk_get_returns_records_for_requested_ids() -> None:
    tracker = InMemoryWorkTracker()
    a = tracker.create_objective(parent_id=None, objective_type="task", title="A", body="a")
    b = tracker.create_objective(parent_id=None, objective_type="task", title="B", body="b")

    records = tracker.bulk_get([a, b])
    assert [r.id for r in records] == [a, b]


def test_reparent_updates_children_and_parent_chain() -> None:
    tracker = InMemoryWorkTracker()
    old_parent = tracker.create_objective(
        parent_id=None, objective_type="epic", title="P0", body=""
    )
    new_parent = tracker.create_objective(
        parent_id=None, objective_type="epic", title="P1", body=""
    )
    child = tracker.create_objective(
        parent_id=old_parent, objective_type="task", title="C", body=""
    )

    assert tracker.list_children(old_parent) == [child]
    assert tracker.walk_parent_chain(child) == [old_parent]

    tracker.reparent(child, new_parent, "regrouped")

    assert tracker.list_children(old_parent) == []
    assert tracker.list_children(new_parent) == [child]
    assert tracker.walk_parent_chain(child) == [new_parent]


def test_lifecycle_mutations_accumulate_audit_notes_with_reasons() -> None:
    tracker = InMemoryWorkTracker()
    objective_id = tracker.create_objective(
        parent_id=None, objective_type="task", title="A", body="a"
    )

    tracker.set_lifecycle_status(objective_id, "in_progress", "claimed")
    tracker.append_audit_note(objective_id, "freeform note")
    tracker.update_spec(objective_id, "new spec body", "spec refined")

    record = tracker.get_objective(objective_id)
    assert "status=in_progress: claimed" in record.audit_notes
    assert "freeform note" in record.audit_notes
    assert "spec-updated: spec refined" in record.audit_notes
    assert tracker.get_spec(objective_id) == "new spec body"


def test_set_killed_maps_to_closed_with_killed_disposition() -> None:
    tracker = InMemoryWorkTracker()
    objective_id = tracker.create_objective(
        parent_id=None, objective_type="task", title="A", body="a"
    )

    tracker.set_killed(objective_id, "not worth pursuing")

    record = tracker.get_objective(objective_id)
    assert record.lifecycle_status == "closed"
    assert record.terminal_disposition == "killed"


def test_set_terminal_disposition_records_disposition() -> None:
    tracker = InMemoryWorkTracker()
    objective_id = tracker.create_objective(
        parent_id=None, objective_type="task", title="A", body="a"
    )

    tracker.set_terminal_disposition(objective_id, "superseded", "replaced by newer work")

    assert tracker.get_objective(objective_id).terminal_disposition == "superseded"


def test_decomposition_provenance_recorded_as_audit_note() -> None:
    tracker = InMemoryWorkTracker()
    objective_id = tracker.create_objective(
        parent_id=None, objective_type="task", title="C", body="", decomposition_of="container-1"
    )

    assert "decomposition_of=container-1" in tracker.get_objective(objective_id).audit_notes


def test_unknown_id_raises_objective_not_found() -> None:
    tracker = InMemoryWorkTracker()
    with pytest.raises(ObjectiveNotFoundError):
        tracker.get_objective("nope")
