"""The OrchestratorStateRepo — the orchestrator's own canonical store.

Holds everything orchestrator-owned: per-Objective runtime (current
lifecycle_stage + lifecycle state), Session records, and the discovery
marker. The production store is DoltDB-backed; this in-memory implementation
is the tracer's reference. The append-only TransitionLog lives on each
Objective's `ObjectiveLifecycleState`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pdlc.lifecycle import LifecycleStage
from pdlc.objective import ObjectiveLifecycleState
from pdlc.session import Session, SessionStatus
from pdlc.transition_log import TransitionEntry
from pdlc.worktracker import Marker

_ACTIVE_SESSION_STATUSES = frozenset({SessionStatus.PENDING, SessionStatus.RUNNING})


@dataclass(slots=True)
class ObjectiveRuntime:
    """An Objective's orchestrator-side runtime: where it is in the FSM and
    its accumulated lifecycle state."""

    objective_id: str
    lifecycle_stage: LifecycleStage
    state: ObjectiveLifecycleState = field(default_factory=ObjectiveLifecycleState)


class OrchestratorStateRepo:
    """In-memory orchestrator state. Single-host, single-process — the lease
    discipline that guards concurrent ticks in production is a no-op here."""

    def __init__(self) -> None:
        self._objectives: dict[str, ObjectiveRuntime] = {}
        self._sessions: dict[str, Session] = {}
        self.discovery_marker: Marker | None = None

    # Objectives

    def has_objective(self, objective_id: str) -> bool:
        return objective_id in self._objectives

    def init_objective(self, objective_id: str) -> ObjectiveRuntime:
        """Create runtime for a freshly-discovered Objective at the universal
        entry point, `CANDIDATE_UOW` (Law L6)."""
        runtime = ObjectiveRuntime(
            objective_id=objective_id,
            lifecycle_stage=LifecycleStage.CANDIDATE_UOW,
        )
        self._objectives[objective_id] = runtime
        return runtime

    def get_objective(self, objective_id: str) -> ObjectiveRuntime:
        return self._objectives[objective_id]

    def all_objectives(self) -> list[ObjectiveRuntime]:
        return list(self._objectives.values())

    def set_stage(self, objective_id: str, stage: LifecycleStage) -> None:
        self._objectives[objective_id].lifecycle_stage = stage

    def append_transition(self, objective_id: str, entry: TransitionEntry) -> None:
        self._objectives[objective_id].state.transition_log.append(entry)

    def record_strike(  # pragma: no cover - exercised by the strike / autopsy scenario
        self, objective_id: str, stage: LifecycleStage
    ) -> None:
        counts = self._objectives[objective_id].state.strike_counts
        counts[stage] = counts.get(stage, 0) + 1

    # Sessions

    def put_session(self, session: Session) -> None:
        self._sessions[session.id] = session

    def active_session_for(self, objective_id: str) -> Session | None:
        """The pending/running Session blocking a new dispatch, if any."""
        for session in self._sessions.values():
            if session.objective_id == objective_id and session.status in _ACTIVE_SESSION_STATUSES:
                return session
        return None

    def sessions_awaiting_reap(self) -> list[Session]:
        """Running Sessions whose worker has produced terminal status."""
        return [s for s in self._sessions.values() if s.status == SessionStatus.RUNNING]
