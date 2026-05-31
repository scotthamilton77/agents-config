"""PDLC Orchestrator — deterministic FSM engine for the product lifecycle.

Drives Objectives from `CANDIDATE_UOW` to a terminal lifecycle stage via a
CLI-driven tick. This package owns the FSM, the WorkTracker port (the seam to
the work-management system), the Session/JobSupervisor worker lifecycle, the
TransitionLog, and the in-memory OrchestratorStateRepo. The Holding Place is a
peer subsystem reached only across the WorkTracker port — see ADR-0001.
"""

from pdlc.gate_evidence import GateEvidence, GateEvidenceError, read_and_validate, write_evidence
from pdlc.lifecycle import (
    GATE_ID_BY_STAGE,
    HAPPY_PATH_NEXT,
    TERMINAL_STAGES,
    WORKER_STAGES,
    Actor,
    LifecycleStage,
)
from pdlc.objective import ObjectiveLifecycleState, Provenance
from pdlc.orchestrator import Orchestrator
from pdlc.session import Session, SessionStatus
from pdlc.state_repo import ObjectiveRuntime, OrchestratorStateRepo
from pdlc.supervisor import JobSupervisor, SupervisorLease, TerminalStatus
from pdlc.transition_log import TransitionEntry
from pdlc.worktracker import (
    InMemoryWorkTracker,
    ObjectiveNotFoundError,
    ObjectiveRecord,
    WorkTracker,
)

__all__ = [
    "GATE_ID_BY_STAGE",
    "HAPPY_PATH_NEXT",
    "TERMINAL_STAGES",
    "WORKER_STAGES",
    "Actor",
    "GateEvidence",
    "GateEvidenceError",
    "InMemoryWorkTracker",
    "JobSupervisor",
    "LifecycleStage",
    "ObjectiveLifecycleState",
    "ObjectiveNotFoundError",
    "ObjectiveRecord",
    "ObjectiveRuntime",
    "Orchestrator",
    "OrchestratorStateRepo",
    "Provenance",
    "Session",
    "SessionStatus",
    "SupervisorLease",
    "TerminalStatus",
    "TransitionEntry",
    "WorkTracker",
    "read_and_validate",
    "write_evidence",
]
