"""list --track filters on DERIVED Item.track, not raw label presence (criterion 8)."""

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
from workcli.verbs.read import list_

CONFIG = TrackLayerConfig(
    names=("alpha", "beta"),
    organizing_only=(),
    enforcement="advisory",
    milestone_wip_cap=None,
    wip_exempt_milestones=(),
    backlog_groom_nag_days=None,
    groom_state_bead=None,
    extraction_max_track_backlog=None,
    extraction_external_consumer_tracks=(),
    extraction_independent_release_tracks=(),
    extraction_max_cross_track_edges=None,
)


def _list_args(track: str | None, load_config: object) -> Namespace:
    return Namespace(
        status=None,
        label=None,
        parent=None,
        type=None,
        limit=None,
        track=track,
        load_config=load_config,
    )


def _backend() -> FakeBackend:
    backend = FakeBackend()
    backend.add("w-1", labels=["track:alpha"])
    backend.add("w-2", labels=["track:beta"])
    backend.add("w-3", labels=[])  # untracked -> null
    backend.add("w-4", labels=["track:alpha", "track:beta"])  # multi -> null
    return backend


def test_filters_on_derived_track_value() -> None:
    data = list_(_backend(), _list_args("alpha", lambda: CONFIG))
    assert isinstance(data, dict)
    items = data["items"]
    assert isinstance(items, list)
    ids = [item["id"] for item in items if isinstance(item, dict)]
    # w-4 carries a track:alpha LABEL but derives to null -> must not match.
    assert ids == ["w-1"]


def test_unknown_track_name_fails_naming_vocabulary() -> None:
    with pytest.raises(WorkError) as exc_info:
        list_(_backend(), _list_args("gamma", lambda: CONFIG))
    assert exc_info.value.code is ErrorCode.UNKNOWN_TRACK
    assert "alpha" in exc_info.value.message  # names the configured vocabulary


def test_no_track_flag_never_loads_config() -> None:
    def explode() -> TrackLayerConfig:
        raise AssertionError("plain list must not load config")

    data = list_(_backend(), _list_args(None, explode))
    assert isinstance(data, dict)
    items = data["items"]
    assert isinstance(items, list)
    assert len(items) == 4


def test_unconfigured_repo_fails_track_flag_with_e_not_configured() -> None:
    def not_configured() -> TrackLayerConfig:
        raise WorkError(ErrorCode.NOT_CONFIGURED, "track layer not configured: nope")

    with pytest.raises(WorkError) as exc_info:
        list_(_backend(), _list_args("alpha", not_configured))
    assert exc_info.value.code is ErrorCode.NOT_CONFIGURED


def test_limit_applies_after_track_filtering() -> None:
    # REGRESSION PIN: a bd-side --limit truncates the candidate set BEFORE
    # the track filter -- here the first bead is on another track, so a
    # pre-filter limit of 1 would return zero alpha beads.
    backend = FakeBackend()
    backend.add("w-1", labels=["track:beta"])
    backend.add("w-2", labels=["track:alpha"])
    backend.add("w-3", labels=["track:alpha"])
    args = _list_args("alpha", lambda: CONFIG)
    args.limit = 1
    data = list_(backend, args)
    assert isinstance(data, dict)
    items = data["items"]
    assert isinstance(items, list)
    ids = [item["id"] for item in items if isinstance(item, dict)]
    assert ids == ["w-2"]


def test_limit_zero_is_the_unbounded_sentinel() -> None:
    # REGRESSION PIN (Codex finding): the bd adapter sends "--limit 0" for
    # both an omitted limit and an explicit `--limit 0`, so 0 is the
    # existing unbounded sentinel repo-wide -- it must not slice the
    # track-filtered set down to zero items.
    backend = FakeBackend()
    backend.add("w-1", labels=["track:alpha"])
    backend.add("w-2", labels=["track:alpha"])
    args = _list_args("alpha", lambda: CONFIG)
    args.limit = 0
    data = list_(backend, args)
    assert isinstance(data, dict)
    items = data["items"]
    assert isinstance(items, list)
    ids = [item["id"] for item in items if isinstance(item, dict)]
    assert ids == ["w-1", "w-2"]


def test_limit_negative_is_also_unbounded() -> None:
    # REGRESSION PIN (Codex finding): argparse accepts negative ints, and
    # Python's items[:-1] silently drops the last element rather than
    # erroring -- a negative --limit must mean unbounded here too, same as 0.
    backend = FakeBackend()
    backend.add("w-1", labels=["track:alpha"])
    backend.add("w-2", labels=["track:alpha"])
    args = _list_args("alpha", lambda: CONFIG)
    args.limit = -1
    data = list_(backend, args)
    assert isinstance(data, dict)
    items = data["items"]
    assert isinstance(items, list)
    ids = [item["id"] for item in items if isinstance(item, dict)]
    assert ids == ["w-1", "w-2"]


def test_config_flag_reaches_the_loader_verbatim() -> None:
    # main()'s seam threads --config through to the loader untouched;
    # list --track is the first surface that triggers a load.
    seen: list[str | None] = []

    def recording_loader(explicit_path: str | None) -> TrackLayerConfig:
        seen.append(explicit_path)
        return CONFIG

    step = ScriptedStep(
        ("list",),
        BdResult(returncode=0, stdout=json.dumps([]), stderr=""),
    )
    exit_code, _, _ = run_cli(
        ["--config", "/etc/custom.toml", "list", "--track", "alpha"],
        [step],
        config_loader=recording_loader,
    )
    assert exit_code == 0
    assert seen == ["/etc/custom.toml"]
