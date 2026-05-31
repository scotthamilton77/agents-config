"""Contract tests for the Holding Place service and its filesystem storage.

These pin the Promote contract's happy-path semantics — idempotency
(returns-existing, no duplicate Objective), provenance propagation, and the
ready-for-promote precondition — plus the storage round-trip. The
`ObjectiveCreator` is a Fake (a working in-memory creator), not a mock: we
assert on the Objectives that come to exist, not on which methods were called.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from holding_place import (
    FilesystemIdeaStorage,
    HoldingPlace,
    Idea,
    NotReadyForPromoteError,
)
from holding_place.storage import IdeaNotFoundError


@dataclass
class _CreatedObjective:
    objective_id: str
    title: str
    body: str
    originating_idea_id: str | None


class _FakeObjectiveCreator:
    """In-memory `ObjectiveCreator`. Mints sequential ids and remembers every
    Objective created so tests can assert on resulting state."""

    def __init__(self) -> None:
        self.created: list[_CreatedObjective] = []

    def create_objective(
        self,
        *,
        parent_id: str | None,
        objective_type: str,
        title: str,
        body: str,
        originating_idea_id: str | None,
    ) -> str:
        del parent_id, objective_type  # part of the port; unused by these tests
        objective_id = f"obj-{len(self.created) + 1}"
        self.created.append(
            _CreatedObjective(objective_id, title, body, originating_idea_id)
        )
        return objective_id


def _holding_place(tmp_path: Path, creator: _FakeObjectiveCreator) -> HoldingPlace:
    counter = iter(range(1, 1_000_000))
    return HoldingPlace(
        FilesystemIdeaStorage(tmp_path / "hp"),
        creator,
        id_factory=lambda: f"idea-{next(counter)}",
    )


def test_promote_creates_objective_carrying_originating_idea_id(tmp_path: Path) -> None:
    storage = FilesystemIdeaStorage(tmp_path / "hp")
    storage.put(Idea(id="idea-1", title="T", body="B", ready_for_promote=True))
    creator = _FakeObjectiveCreator()
    holding_place = HoldingPlace(storage, creator, id_factory=lambda: "unused")

    objective_id = holding_place.promote("idea-1")

    assert objective_id == "obj-1"
    assert len(creator.created) == 1
    assert creator.created[0].originating_idea_id == "idea-1"
    # The Idea is stamped with its promotion so the link survives.
    assert storage.get("idea-1").promoted_objective_id == "obj-1"


def test_promote_is_idempotent_and_mints_no_duplicate(tmp_path: Path) -> None:
    storage = FilesystemIdeaStorage(tmp_path / "hp")
    storage.put(Idea(id="idea-1", title="T", body="B", ready_for_promote=True))
    creator = _FakeObjectiveCreator()
    holding_place = HoldingPlace(storage, creator, id_factory=lambda: "unused")

    first = holding_place.promote("idea-1")
    second = holding_place.promote("idea-1")

    assert first == second
    # Idempotent: the second call returns the existing Objective, not a new one.
    assert len(creator.created) == 1


def test_promote_rejects_an_idea_not_ready(tmp_path: Path) -> None:
    storage = FilesystemIdeaStorage(tmp_path / "hp")
    storage.put(Idea(id="idea-1", title="T", body="B", ready_for_promote=False))
    creator = _FakeObjectiveCreator()
    holding_place = HoldingPlace(storage, creator, id_factory=lambda: "unused")

    with pytest.raises(NotReadyForPromoteError):
        holding_place.promote("idea-1")
    assert creator.created == []


def test_create_idea_spawns_unready_idea_with_decomposition_provenance(tmp_path: Path) -> None:
    storage = FilesystemIdeaStorage(tmp_path / "hp")
    creator = _FakeObjectiveCreator()
    holding_place = _holding_place(tmp_path, creator)

    idea_id = holding_place.create_idea(
        decomposition_of="container-1", title="slice", body="a decomposed sub-unit"
    )

    spawned = storage.get(idea_id)
    assert spawned.decomposition_of == "container-1"
    assert spawned.ready_for_promote is False
    # A decomposed child is an Idea, not an Objective — nothing minted yet.
    assert creator.created == []


def test_filesystem_storage_round_trips_an_idea(tmp_path: Path) -> None:
    storage = FilesystemIdeaStorage(tmp_path / "hp")
    idea = Idea(id="idea-9", title="T", body="B", ready_for_promote=True, decomposition_of="c-1")

    assert storage.exists("idea-9") is False
    storage.put(idea)
    assert storage.exists("idea-9") is True
    assert storage.get("idea-9") == idea


def test_filesystem_storage_get_unknown_raises(tmp_path: Path) -> None:
    storage = FilesystemIdeaStorage(tmp_path / "hp")
    with pytest.raises(IdeaNotFoundError):
        storage.get("absent")
