"""work track set: validated label swap; cascade in Task 10 (criteria 6-7)."""

from __future__ import annotations

from argparse import Namespace

import pytest

from tests.fake_backend import FakeBackend
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError
from workcli.verbs.tracks import track

CONFIG = TrackLayerConfig(
    names=("alpha", "beta"),
    organizing_only=(),
    enforcement="advisory",
    milestone_wip_cap=None,
    wip_exempt_milestones=(),
    extraction_max_track_backlog=None,
    extraction_external_consumer_tracks=(),
    extraction_independent_release_tracks=(),
    extraction_max_cross_track_edges=None,
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


def _tree_backend() -> FakeBackend:
    """root(alpha) -> child-same(alpha), child-other(beta), child-untracked;
    child-other -> grandchild-same(alpha) [cross-track subtrees still traversed]."""
    backend = FakeBackend()
    backend.add("root", labels=["track:alpha"])
    backend.add("child-same", parent="root", labels=["track:alpha"])
    backend.add("child-other", parent="root", labels=["track:beta"])
    backend.add("child-untracked", parent="root", labels=[])
    backend.add("grandchild-same", parent="child-other", labels=["track:alpha"])
    return backend


def test_cascade_relabels_matching_and_untracked_skips_other_tracks() -> None:
    backend = _tree_backend()
    data = track(backend, _track_args("root", "beta", cascade=True))
    assert _track_labels(backend, "child-same") == ["track:beta"]
    assert _track_labels(backend, "child-untracked") == ["track:beta"]
    assert _track_labels(backend, "grandchild-same") == ["track:beta"]
    assert _track_labels(backend, "child-other") == ["track:beta"]  # already the target
    assert isinstance(data, dict)
    assert data["relabeled"] == 3
    assert data["skipped"] == 1
    assert data["skipped_ids"] == ["child-other"]


def test_cascade_skips_and_reports_descendants_on_a_third_track() -> None:
    backend = FakeBackend()
    backend.add("root", labels=["track:alpha"])
    backend.add("child-loyal", parent="root", labels=["track:beta"])
    data = track(
        backend,
        Namespace(
            action="set",
            id="root",
            name="alpha",
            cascade=True,
            load_config=lambda: CONFIG,
        ),
    )
    # Deliberately-cross-track child is never clobbered, only reported.
    assert _track_labels(backend, "child-loyal") == ["track:beta"]
    assert isinstance(data, dict)
    assert data["relabeled"] == 0
    assert data["skipped"] == 1
    assert data["skipped_ids"] == ["child-loyal"]


def test_without_cascade_descendants_are_untouched() -> None:
    backend = _tree_backend()
    track(backend, _track_args("root", "beta"))
    assert _track_labels(backend, "child-same") == ["track:alpha"]
    assert _track_labels(backend, "child-untracked") == []
