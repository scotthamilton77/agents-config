"""create track gate (track spec §4; criteria 1-5, 9, 17)."""

from __future__ import annotations

import json
from argparse import Namespace

import pytest

from tests.conftest import run_cli
from tests.fake_backend import FakeBackend
from tests.fakes import ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError
from workcli.lifecycle.create import create_noun, instantiate_spec_shape


def test_create_raw_refuses_track_flag() -> None:
    # --raw is the documented track bypass; a silently-ignored --track would
    # look tracked while creating an untracked bead. E_USAGE, creates nothing.
    exit_code, envelope, _ = run_cli(["create", "--raw", "--title", "T", "--track", "alpha"], [])
    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == "E_USAGE"
    assert "--track" in str(error["message"])


def _config(enforcement: str) -> TrackLayerConfig:
    return TrackLayerConfig(
        names=("alpha", "beta"),
        organizing_only=(),
        enforcement=enforcement,
        milestone_wip_cap=None,
        wip_exempt_milestones=(),
        backlog_groom_nag_days=None,
        groom_state_bead=None,
        extraction_max_track_backlog=None,
        extraction_external_consumer_tracks=(),
        extraction_independent_release_tracks=(),
        extraction_max_cross_track_edges=None,
    )


def _create_args(
    *,
    noun: str = "chore",
    parent: str | None = None,
    track: str | None = None,
    load_config: object,
) -> Namespace:
    return Namespace(
        noun=noun,
        raw=False,
        title="New work",
        description=None,
        type=None,
        priority=None,
        parent=parent,
        label=[],
        orphan=parent is None,
        spec=None,
        trivial=False,
        acceptance=None,
        track=track,
        load_config=load_config,
    )


@pytest.mark.parametrize("enforcement", ["advisory", "required"])
def test_tracked_parent_inherits_track_without_flag(enforcement: str) -> None:
    backend = FakeBackend()
    backend.add("epic-1", type="epic", labels=["track:alpha"])
    data = create_noun(
        backend,
        _create_args(parent="epic-1", load_config=lambda: _config(enforcement)),
    )
    assert isinstance(data, dict)
    new_id = data["id"]
    assert isinstance(new_id, str)
    assert "track:alpha" in backend.labels(new_id)
    assert "warnings" not in data


def test_required_mode_underivable_fails_and_creates_nothing() -> None:
    backend = FakeBackend()
    with pytest.raises(WorkError) as exc_info:
        create_noun(backend, _create_args(load_config=lambda: _config("required")))
    assert exc_info.value.code is ErrorCode.TRACK_REQUIRED
    assert backend.ids() == []


@pytest.mark.parametrize("enforcement", ["advisory"])
def test_advisory_underivable_succeeds_untracked_with_warning(enforcement: str) -> None:
    # Criterion 4's create leg rides on config parsing: an omitted enforcement
    # key already parses to "advisory" (test_config_loading), so this single
    # behavior covers both spellings.
    backend = FakeBackend()
    data = create_noun(backend, _create_args(load_config=lambda: _config(enforcement)))
    assert isinstance(data, dict)
    new_id = data["id"]
    assert isinstance(new_id, str)
    assert all(not label.startswith("track:") for label in backend.labels(new_id))
    warnings = data["warnings"]
    assert isinstance(warnings, list)
    assert any("untracked" in str(warning) for warning in warnings)


def test_unknown_track_flag_fails_with_vocabulary() -> None:
    backend = FakeBackend()
    with pytest.raises(WorkError) as exc_info:
        create_noun(
            backend,
            _create_args(track="gamma", load_config=lambda: _config("advisory")),
        )
    assert exc_info.value.code is ErrorCode.UNKNOWN_TRACK
    assert "alpha" in exc_info.value.message
    assert backend.ids() == []


def test_explicit_track_flag_wins_over_parent() -> None:
    backend = FakeBackend()
    backend.add("epic-1", type="epic", labels=["track:alpha"])
    data = create_noun(
        backend,
        _create_args(parent="epic-1", track="beta", load_config=lambda: _config("required")),
    )
    assert isinstance(data, dict)
    new_id = data["id"]
    assert isinstance(new_id, str)
    assert "track:beta" in backend.labels(new_id)


def _not_found_loader() -> TrackLayerConfig:
    raise WorkError(
        ErrorCode.NOT_CONFIGURED,
        "track layer not configured: no project-config.toml",
        detail={"reason": "not-found"},
    )


def _invalid_loader() -> TrackLayerConfig:
    raise WorkError(
        ErrorCode.NOT_CONFIGURED,
        "track layer not configured: malformed TOML in project-config.toml",
        detail={"reason": "invalid"},
    )


def test_unconfigured_repo_creates_exactly_as_before() -> None:
    backend = FakeBackend()
    data = create_noun(backend, _create_args(load_config=_not_found_loader))
    assert isinstance(data, dict)
    assert "warnings" not in data
    new_id = data["id"]
    assert isinstance(new_id, str)
    assert all(not label.startswith("track:") for label in backend.labels(new_id))


def test_unconfigured_repo_fails_explicit_track_flag() -> None:
    backend = FakeBackend()
    with pytest.raises(WorkError) as exc_info:
        create_noun(backend, _create_args(track="alpha", load_config=_not_found_loader))
    assert exc_info.value.code is ErrorCode.NOT_CONFIGURED
    assert backend.ids() == []


def test_invalid_config_skips_gate_with_warning_never_breaks_create() -> None:
    backend = FakeBackend()
    data = create_noun(backend, _create_args(load_config=_invalid_loader))
    assert isinstance(data, dict)
    new_id = data["id"]
    assert isinstance(new_id, str)
    warnings = data["warnings"]
    assert isinstance(warnings, list)
    assert any("track gate skipped" in str(warning) for warning in warnings)


def test_raw_milestone_create_bypasses_gate_even_in_required_mode() -> None:
    # Milestones are track-exempt (track spec §3) and enter via --raw; the
    # gate must not touch this path regardless of enforcement. The exploding
    # loader proves --raw never even loads config.
    def explode(_explicit_path: str | None) -> TrackLayerConfig:
        raise AssertionError("--raw create must not load config")

    step = ScriptedStep(
        ("create",),
        BdResult(returncode=0, stdout=json.dumps({"id": "w-9"}), stderr=""),
    )
    exit_code, envelope, _ = run_cli(
        ["create", "--raw", "--title", "M9", "--type", "milestone"],
        [step],
        config_loader=explode,
    )
    assert exit_code == 0
    assert envelope["ok"] is True


def test_spec_container_children_inherit_resolved_track() -> None:
    backend = FakeBackend()
    backend.add("epic-1", type="epic", labels=["track:alpha"])
    data = create_noun(
        backend,
        _create_args(noun="spec", parent="epic-1", load_config=lambda: _config("advisory")),
    )
    assert isinstance(data, dict)
    for key in ("id", "design_child", "placeholder"):
        bead_id = data[key]
        assert isinstance(bead_id, str)
        assert "track:alpha" in backend.labels(bead_id)


def test_unknown_parent_track_not_inherited_advisory_warns() -> None:
    backend = FakeBackend()
    backend.add("epic-1", type="epic", labels=["track:ghost"])
    data = create_noun(
        backend, _create_args(parent="epic-1", load_config=lambda: _config("advisory"))
    )
    assert isinstance(data, dict)
    new_id = data["id"]
    assert isinstance(new_id, str)
    assert all(not label.startswith("track:") for label in backend.labels(new_id))
    warnings = data["warnings"]
    assert isinstance(warnings, list)
    assert any("ghost" in str(warning) for warning in warnings)


def test_unknown_parent_track_required_mode_refuses() -> None:
    # required mode must not mint a bead whose track is invisible to
    # list --track and unrepairable via track set.
    backend = FakeBackend()
    backend.add("epic-1", type="epic", labels=["track:ghost"])
    with pytest.raises(WorkError) as exc_info:
        create_noun(backend, _create_args(parent="epic-1", load_config=lambda: _config("required")))
    assert exc_info.value.code is ErrorCode.TRACK_REQUIRED
    assert backend.ids() == ["epic-1"]


def test_replayed_instantiation_on_tracked_container_stamps_children() -> None:
    # The reconcile/promote path calls instantiate_spec_shape with no track;
    # a tracked container's children must inherit its derived track anyway,
    # or an interrupted tracked create replays into lint violations.
    backend = FakeBackend()
    backend.add(
        "cont-1",
        type="feature",
        labels=["shape-spec", "creating-spec", "track:alpha"],
    )
    design_id, placeholder_id = instantiate_spec_shape(backend, "cont-1", "T")
    assert "track:alpha" in backend.labels(design_id)
    assert "track:alpha" in backend.labels(placeholder_id)
