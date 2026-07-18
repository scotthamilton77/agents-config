"""work track set: validated label swap; cascade in Task 10 (criteria 6-7)."""

from __future__ import annotations

from argparse import Namespace

import pytest
from workcli.verbs.tracks import track

from tests.fake_backend import FakeBackend
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError

CONFIG = TrackLayerConfig(
    names=("alpha", "beta"),
    organizing_only=(),
    enforcement="advisory",
    milestone_wip_cap=None,
    wip_exempt_milestones=(),
)


def _track_args(item_id: str, name: str, *, cascade: bool = False) -> Namespace:
    return Namespace(
        action="set",
        id=item_id,
        name=name,
        cascade=cascade,
        load_config=lambda: CONFIG,
    )


def _track_labels(backend: FakeBackend, item_id: str) -> list[str]:
    return [label for label in backend.labels(item_id) if label.startswith("track:")]


def test_set_swaps_to_exactly_one_track_label() -> None:
    backend = FakeBackend()
    backend.add("w-1", labels=["planned", "track:alpha"])
    data = track(backend, _track_args("w-1", "beta"))
    assert _track_labels(backend, "w-1") == ["track:beta"]
    assert "planned" in backend.labels(backend.ids()[0])
    assert isinstance(data, dict)
    assert data["previous"] == "alpha"


def test_set_on_untracked_bead_is_a_pure_add() -> None:
    backend = FakeBackend()
    backend.add("w-1", labels=["planned"])
    data = track(backend, _track_args("w-1", "alpha"))
    assert _track_labels(backend, "w-1") == ["track:alpha"]
    assert isinstance(data, dict)
    assert data["previous"] is None


def test_set_heals_a_multi_label_bead_to_exactly_one() -> None:
    backend = FakeBackend()
    backend.add("w-1", labels=["track:alpha", "track:beta"])
    track(backend, _track_args("w-1", "alpha"))
    assert _track_labels(backend, "w-1") == ["track:alpha"]


def test_unknown_name_fails_and_mutates_nothing() -> None:
    backend = FakeBackend()
    backend.add("w-1", labels=["track:alpha"])
    with pytest.raises(WorkError) as exc_info:
        track(backend, _track_args("w-1", "gamma"))
    assert exc_info.value.code is ErrorCode.UNKNOWN_TRACK
    assert _track_labels(backend, "w-1") == ["track:alpha"]


def test_missing_bead_is_not_found() -> None:
    with pytest.raises(WorkError) as exc_info:
        track(FakeBackend(), _track_args("ghost", "alpha"))
    assert exc_info.value.code is ErrorCode.NOT_FOUND
