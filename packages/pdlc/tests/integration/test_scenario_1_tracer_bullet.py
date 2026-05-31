"""Scenario 1 — happy-path Idea -> Promote -> MERGED. The architectural tracer.

This single integration test drives one Objective through every real seam of
the orchestrator skeleton — Holding Place promote, the WorkTracker port, the
FSM engine, the JobSupervisor session lifecycle, gate-evidence on disk, the
TransitionLog, and the DISCOVER -> RECONCILE -> REAP -> DISPATCH -> PERSIST
tick loop — with stubbed interiors (canned-pass gates, no real worker fork).

The expected transition sequence below is the *contract*. It is written as a
literal here, independent of the production code, so this test pins behaviour
rather than mirroring the implementation. Per the locked tracer decisions the
log assertion is "full-sequence strict-on-essence": exact 9-entry sequence;
strict on ``from_stage`` / ``to_stage`` / ``reason`` / ``actor``; flexible on
``ts`` / ``config_hash``. Gate-bearing entries are checked structurally only
(pointer non-null + file exists + parseable YAML) — never on content, which
would be brittle against the still-unresolved worker-report seam.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from holding_place import FilesystemIdeaStorage, HoldingPlace, Idea

from pdlc import (
    Actor,
    InMemoryWorkTracker,
    JobSupervisor,
    LifecycleStage,
    Orchestrator,
    OrchestratorStateRepo,
)

# The contract: (from_stage, to_stage, reason, actor, gate_bearing).
# Nine stage-advances; the 10-state happy path skips CONTAINER_DECOMPOSED,
# PR_HUMAN_HOLD, AUTOPSY, KILLED, PARKED by definition of "happy path".
# Stage/Actor aliased locally to keep the contract table readable.
_S = LifecycleStage
_A = Actor
EXPECTED_SEQUENCE = [
    (_S.CANDIDATE_UOW, _S.AGENT_WORTHY, "signoff-received", _A.HUMAN, False),
    (_S.AGENT_WORTHY, _S.DECOMPOSE, "agent-worthy-gate-pass", _A.ORCHESTRATOR, False),
    (_S.DECOMPOSE, _S.EXECUTABLE_READY, "sizing-gate-sized", _A.ORCHESTRATOR, False),
    (_S.EXECUTABLE_READY, _S.TEST_AUTHORING, "dispatch-worker", _A.ORCHESTRATOR, False),
    (_S.TEST_AUTHORING, _S.IMPLEMENTING, "gate-pass", _A.ORCHESTRATOR, True),
    (_S.IMPLEMENTING, _S.REVIEWING, "gate-pass", _A.ORCHESTRATOR, True),
    (_S.REVIEWING, _S.PR_VALIDATION, "gate-pass", _A.ORCHESTRATOR, True),
    (_S.PR_VALIDATION, _S.MERGING, "gate-pass", _A.ORCHESTRATOR, True),
    (_S.MERGING, _S.MERGED, "merge-complete", _A.ORCHESTRATOR, False),
]

MAX_TICKS = 12


@pytest.fixture
def tracer(tmp_path: Path) -> Iterator[tuple[Orchestrator, str, InMemoryWorkTracker]]:
    """Wire the two peer subsystems and promote one ready Idea.

    Yields the orchestrator, the promoted ``objective_id``, and the work
    tracker so the test can assert against the tracker's projected state.
    """
    storage = FilesystemIdeaStorage(tmp_path / "holding-place")
    storage.put(
        Idea(
            id="idea-1",
            title="Tracer-bullet objective",
            body="Drive one Objective end-to-end through the FSM skeleton.",
            ready_for_promote=True,
        )
    )

    work_tracker = InMemoryWorkTracker()
    _counter = iter(range(1, 1_000_000))
    holding_place = HoldingPlace(
        storage,
        work_tracker,
        id_factory=lambda: f"idea-{next(_counter)}",
    )

    # Promote: real on both sides — Holding Place calls the WorkTracker port,
    # which mints an Objective carrying originating_idea_id provenance.
    objective_id = holding_place.promote("idea-1")

    orchestrator = Orchestrator(
        work_tracker=work_tracker,
        state_repo=OrchestratorStateRepo(),
        supervisor=JobSupervisor(root=tmp_path / "pdlc"),
        config_hash="tracer-config-v1",
        root=tmp_path / "pdlc",
    )
    # Canned human signoff — the tracer's stand-in for the CANDIDATE_UOW
    # human signoff gate, analogous to ready_for_promote bypassing the Curator.
    orchestrator.record_signoff(objective_id)

    yield orchestrator, objective_id, work_tracker


def _run_to_terminal(orchestrator: Orchestrator, objective_id: str) -> None:
    for _ in range(MAX_TICKS):
        orchestrator.tick()
        if orchestrator.is_terminal(objective_id):
            return
    pytest.fail(f"Objective {objective_id} did not reach a terminal stage within {MAX_TICKS} ticks")


def test_promote_propagates_originating_idea_id(
    tracer: tuple[Orchestrator, str, InMemoryWorkTracker],
) -> None:
    """The Objective minted by promote carries its originating Idea's id —
    the provenance fingerprint the WorkTracker correlates back to."""
    _orchestrator, objective_id, work_tracker = tracer
    record = work_tracker.get_objective(objective_id)
    assert record.originating_idea_id == "idea-1"
    assert record.lifecycle_status == "open"


def test_traverses_full_happy_path_to_merged(
    tracer: tuple[Orchestrator, str, InMemoryWorkTracker],
) -> None:
    """The Objective reaches MERGED via exactly the nine contracted advances."""
    orchestrator, objective_id, _work_tracker = tracer

    _run_to_terminal(orchestrator, objective_id)

    log = orchestrator.transition_log_for(objective_id)
    assert len(log) == len(EXPECTED_SEQUENCE), (
        f"expected {len(EXPECTED_SEQUENCE)} transitions, got {len(log)}: "
        f"{[(e.from_stage, e.to_stage) for e in log]}"
    )

    for entry, expected in zip(log, EXPECTED_SEQUENCE, strict=True):
        from_stage, to_stage, reason, actor, _gate = expected
        assert entry.from_stage == from_stage
        assert entry.to_stage == to_stage
        assert entry.reason == reason
        assert entry.actor == actor

    assert log[-1].to_stage == LifecycleStage.MERGED


def test_gate_bearing_transitions_have_valid_evidence(
    tracer: tuple[Orchestrator, str, InMemoryWorkTracker],
) -> None:
    """Each worker-reap advance points at a real, parseable gate-evidence
    YAML; each non-worker advance carries no evidence pointer."""
    orchestrator, objective_id, _work_tracker = tracer

    _run_to_terminal(orchestrator, objective_id)

    log = orchestrator.transition_log_for(objective_id)
    for entry, expected in zip(log, EXPECTED_SEQUENCE, strict=True):
        gate_bearing = expected[4]
        if gate_bearing:
            assert entry.gate_evidence_ref is not None
            evidence_path = Path(entry.gate_evidence_ref)
            assert evidence_path.exists(), f"missing gate evidence: {evidence_path}"
            parsed = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
            assert isinstance(parsed, dict)  # structural only — no content assertion
        else:
            assert entry.gate_evidence_ref is None


def test_no_strikes_charged_on_happy_path(
    tracer: tuple[Orchestrator, str, InMemoryWorkTracker],
) -> None:
    """The happy path passes every gate first try — no cognition strikes."""
    orchestrator, objective_id, _work_tracker = tracer

    _run_to_terminal(orchestrator, objective_id)

    strike_counts = orchestrator.strike_counts_for(objective_id)
    assert sum(strike_counts.values()) == 0


def test_every_entry_carries_config_hash_and_monotonic_ts(
    tracer: tuple[Orchestrator, str, InMemoryWorkTracker],
) -> None:
    """``config_hash`` and ``ts`` are flexible in value but must be present
    and well-ordered on every entry."""
    orchestrator, objective_id, _work_tracker = tracer

    _run_to_terminal(orchestrator, objective_id)

    log = orchestrator.transition_log_for(objective_id)
    assert all(entry.config_hash for entry in log)
    timestamps = [entry.ts for entry in log]
    assert timestamps == sorted(timestamps)


def test_tracker_reflects_merge_and_cleanup_is_idempotent(
    tracer: tuple[Orchestrator, str, InMemoryWorkTracker],
) -> None:
    """On MERGED the tracker shows the Objective closed; worktree cleanup is
    safe to call again (idempotent), per Integration Stage C discipline."""
    orchestrator, objective_id, work_tracker = tracer

    _run_to_terminal(orchestrator, objective_id)

    assert work_tracker.get_objective(objective_id).lifecycle_status == "closed"
    # Cleanup already ran at MERGING->MERGED; calling again must not raise.
    orchestrator.cleanup_worktree(objective_id)
    orchestrator.cleanup_worktree(objective_id)
