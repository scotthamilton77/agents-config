"""The Orchestrator — the CLI-driven tick that drives Objectives through the FSM.

One `tick()` runs the fixed phase sequence DISCOVER -> RECONCILE -> REAP ->
DISPATCH -> PERSIST and advances each Objective by at most one stage. The same
loop, ticked repeatedly, carries the tracer Objective from `CANDIDATE_UOW` to
`MERGED`.

Reasons and actors (the *policy* the TransitionLog records) live here, keyed
off the stage being left. Orchestrator-internal gates (signoff, agent-worthy,
sizing) advance in DISPATCH; worker-driven stages are entered in DISPATCH and
exited in REAP once their gate evidence verifies.
"""

from __future__ import annotations

from pathlib import Path

from pdlc.gate_evidence import read_and_validate
from pdlc.lifecycle import (
    HAPPY_PATH_NEXT,
    ORCHESTRATOR_ADVANCE_STAGES,
    TERMINAL_STAGES,
    WORKER_STAGES,
    Actor,
    LifecycleStage,
)
from pdlc.session import Session, SessionStatus
from pdlc.state_repo import ObjectiveRuntime, OrchestratorStateRepo
from pdlc.supervisor import JobSupervisor
from pdlc.transition_log import TransitionEntry
from pdlc.worktracker import WorkTracker

# Policy: the machine-tag reason and the initiating actor for each
# orchestrator-internal advance, keyed by the stage being left.
_ADVANCE_REASON: dict[LifecycleStage, str] = {
    LifecycleStage.CANDIDATE_UOW: "signoff-received",
    LifecycleStage.AGENT_WORTHY: "agent-worthy-gate-pass",
    LifecycleStage.DECOMPOSE: "sizing-gate-sized",
    LifecycleStage.EXECUTABLE_READY: "dispatch-worker",
    LifecycleStage.MERGING: "merge-complete",
}
# The CANDIDATE_UOW exit is the human signoff gate; every other
# orchestrator-internal advance is mechanical.
_ADVANCE_ACTOR: dict[LifecycleStage, Actor] = {
    LifecycleStage.CANDIDATE_UOW: Actor.HUMAN,
}
_WORKER_REAP_REASON = "gate-pass"
_NO_LEASE = "running session {} has no supervisor lease"


class Orchestrator:
    """Drives Objectives through the PDLC FSM, one tick at a time."""

    def __init__(
        self,
        *,
        work_tracker: WorkTracker,
        state_repo: OrchestratorStateRepo,
        supervisor: JobSupervisor,
        config_hash: str,
        root: Path,
    ) -> None:
        self._wt = work_tracker
        self._repo = state_repo
        self._sup = supervisor
        self._config_hash = config_hash
        self._root = root
        self._clock = 0
        self._next_session = 0
        self._signoff: set[str] = set()
        self._session_worktrees: dict[str, list[Path]] = {}
        self._advanced_this_tick: set[str] = set()
        self._pending_marker: int | None = None

    # ── public surface ──

    def record_signoff(self, objective_id: str) -> None:
        """Record the human signoff that satisfies the `CANDIDATE_UOW ->
        AGENT_WORTHY` gate. The tracer's stand-in for the operator's signoff
        annotation."""
        self._signoff.add(objective_id)

    def is_terminal(self, objective_id: str) -> bool:
        return self._repo.get_objective(objective_id).lifecycle_stage in TERMINAL_STAGES

    def transition_log_for(self, objective_id: str) -> list[TransitionEntry]:
        return list(self._repo.get_objective(objective_id).state.transition_log)

    def strike_counts_for(self, objective_id: str) -> dict[LifecycleStage, int]:
        return dict(self._repo.get_objective(objective_id).state.strike_counts)

    def cleanup_worktree(self, objective_id: str) -> None:
        """Idempotently remove every sandbox worktree opened for `objective_id`."""
        for worktree_path in self._session_worktrees.get(objective_id, []):
            self._sup.cleanup_worktree(worktree_path)

    def tick(self) -> None:
        self._advanced_this_tick = set()
        self._discover()
        self._reconcile()
        self._reap()
        self._dispatch()
        self._persist()

    # ── phases ──

    def _discover(self) -> None:
        changed, new_marker = self._wt.discover_since(self._repo.discovery_marker)
        for record in changed:
            if not self._repo.has_objective(record.id):
                # Universal entry point (Law L6); the init itself is not a
                # stage-advance, so no TransitionEntry is logged here.
                self._repo.init_objective(record.id)
        self._pending_marker = new_marker

    def _reconcile(self) -> None:
        # Confirm each known Objective still exists in the tracker. Fingerprint
        # divergence (spec-edit mid-flight) and terminal-disposition mapping are
        # exercised by Scenarios 3-4; the happy path has no divergence.
        for runtime in self._repo.all_objectives():
            self._wt.get_objective(runtime.objective_id)

    def _reap(self) -> None:
        for session in self._repo.sessions_awaiting_reap():
            supervisor_id = session.supervisor_id
            if supervisor_id is None:  # pragma: no cover - a running Session always holds a lease
                raise RuntimeError(_NO_LEASE.format(session.id))
            status = self._sup.terminal_status(supervisor_id)
            # Schema-validate the evidence. Independent gate re-verification
            # (re-running the gate command against the worker's commit) is
            # stubbed for the tracer: a schema-valid pass is a gate pass.
            read_and_validate(status.report_path)
            # RUNNING -> EXITED -> REAPED within one tick: the tracer's worker is
            # synchronous, so it exits and is reaped in the same pass. A real async
            # worker would exit on an earlier tick than the one that reaps it.
            session.status = SessionStatus.EXITED
            runtime = self._repo.get_objective(session.objective_id)
            from_stage = runtime.lifecycle_stage
            self._advance(
                session.objective_id,
                from_stage,
                HAPPY_PATH_NEXT[from_stage],
                reason=_WORKER_REAP_REASON,
                actor=Actor.ORCHESTRATOR,
                session_id=session.id,
                gate_evidence_ref=str(status.report_path),
            )
            session.status = SessionStatus.REAPED

    def _dispatch(self) -> None:
        # Pass A — orchestrator-internal advances (one per Objective per tick).
        for runtime in self._repo.all_objectives():
            stage = runtime.lifecycle_stage
            if (
                stage in ORCHESTRATOR_ADVANCE_STAGES
                and runtime.objective_id not in self._advanced_this_tick
                and self._gate_ready(runtime)
            ):
                self._advance(
                    runtime.objective_id,
                    stage,
                    HAPPY_PATH_NEXT[stage],
                    reason=_ADVANCE_REASON[stage],
                    actor=_ADVANCE_ACTOR.get(stage, Actor.ORCHESTRATOR),
                )
        # Pass B — fork workers for Objectives sitting at a worker stage with
        # no in-flight Session.
        for runtime in self._repo.all_objectives():
            if (
                runtime.lifecycle_stage in WORKER_STAGES
                and self._repo.active_session_for(runtime.objective_id) is None
            ):
                self._dispatch_worker(runtime)

    def _persist(self) -> None:
        # In-memory commit is implicit; the durable step is advancing the
        # discovery marker (CAS against the prior marker in production).
        if self._pending_marker is not None:
            self._repo.discovery_marker = self._pending_marker

    # ── helpers ──

    def _gate_ready(self, runtime: ObjectiveRuntime) -> bool:
        if runtime.lifecycle_stage == LifecycleStage.CANDIDATE_UOW:
            return runtime.objective_id in self._signoff
        # AGENT_WORTHY / DECOMPOSE / EXECUTABLE_READY / MERGING gates are
        # stubbed to pass for the tracer (real gate logic is per-stage work).
        return True

    def _dispatch_worker(self, runtime: ObjectiveRuntime) -> None:
        self._next_session += 1
        session = Session(
            id=f"session-{self._next_session}",
            objective_id=runtime.objective_id,
            lifecycle_stage=runtime.lifecycle_stage,
            attempt_number=1,
            config_hash=self._config_hash,
        )
        self._repo.put_session(session)
        lease = self._sup.lease(session)
        session.supervisor_id = lease.supervisor_id
        session.artifact_dir = lease.artifact_dir
        session.worktree_path = lease.worktree_path
        session.report_path = lease.report_path
        session.status = SessionStatus.RUNNING
        self._session_worktrees.setdefault(runtime.objective_id, []).append(lease.worktree_path)

    def _advance(
        self,
        objective_id: str,
        from_stage: LifecycleStage,
        to_stage: LifecycleStage,
        *,
        reason: str,
        actor: Actor,
        session_id: str | None = None,
        gate_evidence_ref: str | None = None,
    ) -> None:
        self._clock += 1
        self._repo.append_transition(
            objective_id,
            TransitionEntry(
                ts=self._clock,
                objective_id=objective_id,
                from_stage=from_stage,
                to_stage=to_stage,
                reason=reason,
                actor=actor,
                config_hash=self._config_hash,
                session_id=session_id,
                gate_evidence_ref=gate_evidence_ref,
            ),
        )
        self._repo.set_stage(objective_id, to_stage)
        self._advanced_this_tick.add(objective_id)
        if to_stage == LifecycleStage.MERGED:
            self._on_merged(objective_id)

    def _on_merged(self, objective_id: str) -> None:
        # Integration Stage C — merge + cleanup: project the close onto the
        # tracker and idempotently remove the sandbox worktrees.
        self._wt.set_lifecycle_status(objective_id, "closed", "merged")
        self.cleanup_worktree(objective_id)
        # Forget the worktree-tracking entry now its worktrees are gone, so the
        # bookkeeping does not grow unbounded as Objectives accumulate. A later
        # cleanup_worktree() call stays a safe no-op (empty list).
        self._session_worktrees.pop(objective_id, None)
