"""work lint: five advisory invariants over one sweep (criteria 9-11)."""

from __future__ import annotations

import json
from argparse import Namespace

from tests.conftest import run_cli
from tests.fake_backend import FakeBackend
from tests.fakes import ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError
from workcli.verbs.report import lint

CONFIG = TrackLayerConfig(
    names=("alpha", "beta"),
    organizing_only=(),
    enforcement="advisory",
    milestone_wip_cap=1,
    wip_exempt_milestones=("m-exempt",),
    backlog_groom_nag_days=None,
    groom_state_bead=None,
    extraction_max_track_backlog=None,
    extraction_external_consumer_tracks=(),
    extraction_independent_release_tracks=(),
    extraction_max_cross_track_edges=None,
)


def _lint_args(config: TrackLayerConfig = CONFIG) -> Namespace:
    return Namespace(load_config=lambda: config)


def _fixture() -> FakeBackend:
    """One backend exercising every invariant class."""
    backend = FakeBackend()
    # Milestones: two in_progress non-exempt (cap 1 -> breach) + one exempt.
    backend.add("m-1", type="milestone", status="in_progress")
    backend.add("m-2", type="milestone", status="in_progress")
    backend.add("m-exempt", type="milestone", status="in_progress")
    # Invariant 1: missing track / multi track / out-of-vocabulary track
    # (all under a milestone).
    backend.add("no-track", parent="m-1", labels=[])
    backend.add("two-tracks", parent="m-1", labels=["track:alpha", "track:beta"])
    backend.add("ghost-track", parent="m-1", labels=["track:ghost"])
    # Invariant 2: milestone-orphan; and an explicitly exempted orphan.
    backend.add("orphan", labels=["track:alpha"])
    backend.add("orphan-exempt", labels=["track:alpha", "lint-exempt:no-milestone"])
    # Ancestry through a CLOSED intermediate container must still find m-1.
    backend.add("closed-epic", type="epic", status="closed", parent="m-1")
    backend.add("deep-child", parent="closed-epic", labels=["track:alpha"])
    # Invariant 4: one track holding two leases.
    backend.add("lease-1", parent="m-1", status="in_progress", labels=["track:alpha"])
    backend.add("lease-2", parent="m-1", status="in_progress", labels=["track:alpha"])
    # Invariant 5: parent-child mismatch below milestone level.
    backend.add("epic-beta", type="epic", parent="m-1", labels=["track:beta"])
    backend.add("mismatch-child", parent="epic-beta", labels=["track:alpha"])
    # Closed beads are exempt from everything.
    backend.add("closed-untracked", status="closed", labels=[])
    return backend


def test_lint_reports_every_invariant_class() -> None:
    report = lint(_fixture(), _lint_args())
    assert isinstance(report, dict)

    violations = report["track_violations"]
    assert isinstance(violations, list)
    flagged = {entry["id"] for entry in violations if isinstance(entry, dict)}
    # closed + milestones exempt; ghost-track flagged for its unknown name
    assert flagged == {"no-track", "two-tracks", "ghost-track"}
    ghost_entry = next(
        entry for entry in violations if isinstance(entry, dict) and entry["id"] == "ghost-track"
    )
    assert ghost_entry["unknown"] == ["track:ghost"]

    orphans = report["milestone_orphans"]
    assert isinstance(orphans, list)
    assert orphans == ["orphan"]  # exempt label honored; deep-child anchored
    # through its CLOSED epic to m-1

    wip = report["wip"]
    assert isinstance(wip, dict)
    assert wip["breached"] is True
    active = wip["active"]
    assert isinstance(active, list)
    assert sorted(str(m) for m in active) == ["m-1", "m-2"]  # exempt milestones excluded

    leases = report["leases"]
    assert isinstance(leases, dict)
    assert leases["crowded_tracks"] == ["alpha"]
    all_leases = leases["leases"]
    assert isinstance(all_leases, list)
    assert len(all_leases) == 2  # every non-milestone lease listed for triage

    mismatches = report["track_mismatches"]
    assert isinstance(mismatches, list)
    assert mismatches == [
        {
            "child": "mismatch-child",
            "child_track": "alpha",
            "parent": "epic-beta",
            "parent_track": "beta",
        }
    ]


def _not_configured_loader(_explicit_path: str | None) -> TrackLayerConfig:
    raise WorkError(
        ErrorCode.NOT_CONFIGURED,
        "track layer not configured: no project-config.toml",
        detail={"reason": "not-found"},
    )


def test_lint_without_config_is_e_not_configured() -> None:
    exit_code, envelope, _ = run_cli(["lint"], [], config_loader=_not_configured_loader)
    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == "E_NOT_CONFIGURED"


def test_lint_with_violations_still_exits_zero() -> None:
    # The advisory leg: violations live in the envelope, exit stays 0.
    def loader(_explicit_path: str | None) -> TrackLayerConfig:
        return CONFIG

    step = ScriptedStep(
        ("list",),
        BdResult(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "id": "w-1",
                        "title": "T",
                        "issue_type": "task",
                        "status": "open",
                        "priority": 2,
                        "labels": [],
                    }
                ]
            ),
            stderr="",
        ),
    )
    exit_code, envelope, _ = run_cli(["lint"], [step], config_loader=loader)
    assert exit_code == 0
    assert envelope["ok"] is True
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["track_violations"] == [{"id": "w-1", "track_labels": [], "unknown": []}]
