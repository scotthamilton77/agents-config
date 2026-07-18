"""`work triggers`: extraction pressure/eligibility evaluation (track spec §5, criterion 13)."""

from __future__ import annotations

from argparse import Namespace

from tests.conftest import run_cli
from tests.fake_backend import FakeBackend
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError
from workcli.model import DepEdge
from workcli.verbs.report import triggers

CONFIG = TrackLayerConfig(
    names=("alpha", "beta", "gamma", "org-only"),
    organizing_only=("org-only",),
    enforcement="advisory",
    milestone_wip_cap=None,
    wip_exempt_milestones=(),
    extraction_max_track_backlog=2,
    extraction_external_consumer_tracks=("beta",),
    extraction_independent_release_tracks=(),
    extraction_max_cross_track_edges=3,
)


def _args(config: TrackLayerConfig = CONFIG) -> Namespace:
    return Namespace(load_config=lambda: config)


def _fixture() -> FakeBackend:
    """Exercises all three statuses, an organizing-only track, and bidirectional
    cross-track edge counting with a closed-endpoint edge excluded."""
    backend = FakeBackend()

    # alpha: over backlog cap (3 > 2) -> pressure; 1 cross-track edge to beta
    # (both directions counted independently) -> eligible (1 <= 3).
    backend.add("alpha-1", labels=["track:alpha"])
    backend.add("alpha-2", labels=["track:alpha"])
    backend.add(
        "alpha-3",
        labels=["track:alpha"],
        deps=[DepEdge(id="beta-1", type="blocks", status="open")],
    )

    # beta: declared external-consumer -> pressure; receives the alpha->beta
    # edge above (1) plus an edge to a CLOSED bead (excluded) -> total 1,
    # eligible.
    backend.add(
        "beta-1",
        labels=["track:beta"],
        deps=[DepEdge(id="closed-gamma", type="blocks", status="closed")],
    )
    backend.add("closed-gamma", status="closed", labels=["track:gamma"])

    # gamma: no backlog pressure, not declared -> no-pressure regardless of edges.
    backend.add("gamma-1", labels=["track:gamma"])

    # org-only: organizing-only track, present in backlog_counts, absent from statuses.
    backend.add("org-1", labels=["track:org-only"])

    return backend


def test_backlog_counts_cover_every_configured_track() -> None:
    report = triggers(_fixture(), _args())
    assert isinstance(report, dict)
    counts = report["backlog_counts"]
    assert counts == {"alpha": 3, "beta": 1, "gamma": 1, "org-only": 1}


def test_organizing_only_track_excluded_from_statuses() -> None:
    report = triggers(_fixture(), _args())
    statuses = report["statuses"]
    assert isinstance(statuses, dict)
    assert "org-only" not in statuses
    assert set(statuses) == {"alpha", "beta", "gamma"}


def test_pressured_eligible_from_backlog_pressure() -> None:
    report = triggers(_fixture(), _args())
    statuses = report["statuses"]
    assert isinstance(statuses, dict)
    assert statuses["alpha"] == "pressured-eligible"


def test_pressured_eligible_from_declared_external_consumer() -> None:
    report = triggers(_fixture(), _args())
    statuses = report["statuses"]
    assert isinstance(statuses, dict)
    assert statuses["beta"] == "pressured-eligible"


def test_no_pressure_track() -> None:
    report = triggers(_fixture(), _args())
    statuses = report["statuses"]
    assert isinstance(statuses, dict)
    assert statuses["gamma"] == "no-pressure"


def test_pressured_ineligible_when_edges_exceed_ceiling() -> None:
    config = TrackLayerConfig(
        names=("alpha", "beta"),
        organizing_only=(),
        enforcement="advisory",
        milestone_wip_cap=None,
        wip_exempt_milestones=(),
        extraction_max_track_backlog=0,
        extraction_external_consumer_tracks=(),
        extraction_independent_release_tracks=(),
        extraction_max_cross_track_edges=0,
    )
    backend = FakeBackend()
    backend.add(
        "alpha-1",
        labels=["track:alpha"],
        deps=[DepEdge(id="beta-1", type="blocks", status="open")],
    )
    backend.add("beta-1", labels=["track:beta"])

    report = triggers(backend, _args(config))
    statuses = report["statuses"]
    assert isinstance(statuses, dict)
    assert statuses["alpha"] == "pressured-ineligible"


def test_unconfigured_ceiling_never_yields_eligible() -> None:
    # Fail-safe: max-cross-track-edges omitted -> eligibility can never be
    # proven, so even a track with zero cross-track edges stays ineligible.
    config = TrackLayerConfig(
        names=("alpha",),
        organizing_only=(),
        enforcement="advisory",
        milestone_wip_cap=None,
        wip_exempt_milestones=(),
        extraction_max_track_backlog=0,
        extraction_external_consumer_tracks=(),
        extraction_independent_release_tracks=(),
        extraction_max_cross_track_edges=None,
    )
    backend = FakeBackend()
    backend.add("alpha-1", labels=["track:alpha"])

    report = triggers(backend, _args(config))
    statuses = report["statuses"]
    assert isinstance(statuses, dict)
    assert statuses["alpha"] == "pressured-ineligible"


def test_parent_child_edges_not_counted_as_cross_track() -> None:
    # A synthesized parent-child edge must never inflate the cross-track
    # count -- only raw `item.deps` entries count (spec §5).
    config = TrackLayerConfig(
        names=("alpha", "beta"),
        organizing_only=(),
        enforcement="advisory",
        milestone_wip_cap=None,
        wip_exempt_milestones=(),
        extraction_max_track_backlog=0,
        extraction_external_consumer_tracks=(),
        extraction_independent_release_tracks=(),
        extraction_max_cross_track_edges=0,
    )
    backend = FakeBackend()
    backend.add("alpha-1", labels=["track:alpha"])
    backend.add("beta-1", labels=["track:beta"], parent="alpha-1")

    report = triggers(backend, _args(config))
    statuses = report["statuses"]
    assert isinstance(statuses, dict)
    # No raw dep edges anywhere -> both tracks report pressured but eligible
    # (0 cross-track edges <= ceiling 0).
    assert statuses["alpha"] == "pressured-eligible"
    assert statuses["beta"] == "pressured-eligible"


def test_same_track_dep_edge_not_counted_as_cross_track() -> None:
    config = TrackLayerConfig(
        names=("alpha",),
        organizing_only=(),
        enforcement="advisory",
        milestone_wip_cap=None,
        wip_exempt_milestones=(),
        extraction_max_track_backlog=0,
        extraction_external_consumer_tracks=(),
        extraction_independent_release_tracks=(),
        extraction_max_cross_track_edges=0,
    )
    backend = FakeBackend()
    backend.add(
        "alpha-1",
        labels=["track:alpha"],
        deps=[DepEdge(id="alpha-2", type="blocks", status="open")],
    )
    backend.add("alpha-2", labels=["track:alpha"])

    report = triggers(backend, _args(config))
    statuses = report["statuses"]
    assert isinstance(statuses, dict)
    # Same-track edge contributes 0 -> eligible against ceiling 0.
    assert statuses["alpha"] == "pressured-eligible"


def test_untracked_dep_source_contributes_no_edges() -> None:
    config = TrackLayerConfig(
        names=("alpha",),
        organizing_only=(),
        enforcement="advisory",
        milestone_wip_cap=None,
        wip_exempt_milestones=(),
        extraction_max_track_backlog=0,
        extraction_external_consumer_tracks=(),
        extraction_independent_release_tracks=(),
        extraction_max_cross_track_edges=0,
    )
    backend = FakeBackend()
    # No track label -> derive_track is None -> its deps never contribute.
    backend.add(
        "untracked-1",
        labels=[],
        deps=[DepEdge(id="alpha-1", type="blocks", status="open")],
    )
    backend.add("alpha-1", labels=["track:alpha"])

    report = triggers(backend, _args(config))
    statuses = report["statuses"]
    assert isinstance(statuses, dict)
    assert statuses["alpha"] == "pressured-eligible"


def test_repeated_dep_target_resolved_once_via_cache() -> None:
    config = TrackLayerConfig(
        names=("alpha", "beta"),
        organizing_only=(),
        enforcement="advisory",
        milestone_wip_cap=None,
        wip_exempt_milestones=(),
        extraction_max_track_backlog=0,
        extraction_external_consumer_tracks=(),
        extraction_independent_release_tracks=(),
        extraction_max_cross_track_edges=5,
    )
    backend = FakeBackend()
    # Two alpha beads both dep on the same out-of-sweep (closed) target --
    # the resolver's cache must be consulted for the second lookup.
    backend.add(
        "alpha-1",
        labels=["track:alpha"],
        deps=[DepEdge(id="closed-target", type="blocks", status="closed")],
    )
    backend.add(
        "alpha-2",
        labels=["track:alpha"],
        deps=[DepEdge(id="closed-target", type="blocks", status="closed")],
    )
    backend.add("closed-target", status="closed", labels=["track:beta"])

    report = triggers(backend, _args(config))
    statuses = report["statuses"]
    assert isinstance(statuses, dict)
    # Both edges point at a closed bead -> excluded entirely.
    assert statuses["alpha"] == "pressured-eligible"


def test_review_question_present_and_echoes_declared_lists() -> None:
    report = triggers(_fixture(), _args())
    question = report["review_question"]
    assert isinstance(question, str)
    assert "beta" in question


def test_review_question_present_even_with_empty_declared_lists() -> None:
    config = TrackLayerConfig(
        names=("alpha",),
        organizing_only=(),
        enforcement="advisory",
        milestone_wip_cap=None,
        wip_exempt_milestones=(),
        extraction_max_track_backlog=None,
        extraction_external_consumer_tracks=(),
        extraction_independent_release_tracks=(),
        extraction_max_cross_track_edges=None,
    )
    backend = FakeBackend()
    backend.add("alpha-1", labels=["track:alpha"])

    report = triggers(backend, _args(config))
    assert isinstance(report["review_question"], str)
    assert report["review_question"] != ""


def _not_configured_loader(_explicit_path: str | None) -> TrackLayerConfig:
    raise WorkError(
        ErrorCode.NOT_CONFIGURED,
        "track layer not configured: no project-config.toml",
        detail={"reason": "not-found"},
    )


def test_triggers_without_config_is_e_not_configured() -> None:
    exit_code, envelope, _ = run_cli(["triggers"], [], config_loader=_not_configured_loader)
    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == "E_NOT_CONFIGURED"
