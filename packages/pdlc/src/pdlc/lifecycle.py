"""Lifecycle stage constants and the FSM topology.

`LifecycleStage` is the canonical named-English-constant set from the
orchestrator core design's Lifecycle Stage Constants table. `Actor` is the
TransitionLog actor enum. The module-level tables (`HAPPY_PATH_NEXT`,
`WORKER_STAGES`, `TERMINAL_STAGES`, `GATE_ID_BY_STAGE`) are the *topology* of
the machine — pure data, no policy. The orchestrator reads them to decide
where an Objective goes next; reasons and actors (policy) live with the
orchestrator, not here.
"""

from __future__ import annotations

from enum import StrEnum


class LifecycleStage(StrEnum):
    """The Orchestrator-owned position of an Objective in the FSM.

    The full constant set; the happy-path tracer traverses only a subset.
    `CONTAINER_DECOMPOSED`, `PR_HUMAN_HOLD`, `AUTOPSY`, `KILLED`, and `PARKED`
    exist for completeness and are exercised by other scenarios.
    """

    CANDIDATE_UOW = "CANDIDATE_UOW"
    AGENT_WORTHY = "AGENT_WORTHY"
    DECOMPOSE = "DECOMPOSE"
    EXECUTABLE_READY = "EXECUTABLE_READY"
    CONTAINER_DECOMPOSED = "CONTAINER_DECOMPOSED"
    TEST_AUTHORING = "TEST_AUTHORING"
    IMPLEMENTING = "IMPLEMENTING"
    REVIEWING = "REVIEWING"
    PR_VALIDATION = "PR_VALIDATION"
    PR_HUMAN_HOLD = "PR_HUMAN_HOLD"
    MERGING = "MERGING"
    AUTOPSY = "AUTOPSY"
    MERGED = "MERGED"
    KILLED = "KILLED"
    PARKED = "PARKED"


class Actor(StrEnum):
    """Who initiated a TransitionLog event."""

    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"
    SUPERVISOR = "supervisor"
    HUMAN = "human"
    AUTOPSY = "autopsy"


# The single-Objective happy path: each stage's successor. This is the FSM
# engine's transition table for Scenario 1. Container divergence, retries,
# and autopsy routing are added by their own scenarios.
HAPPY_PATH_NEXT: dict[LifecycleStage, LifecycleStage] = {
    LifecycleStage.CANDIDATE_UOW: LifecycleStage.AGENT_WORTHY,
    LifecycleStage.AGENT_WORTHY: LifecycleStage.DECOMPOSE,
    LifecycleStage.DECOMPOSE: LifecycleStage.EXECUTABLE_READY,
    LifecycleStage.EXECUTABLE_READY: LifecycleStage.TEST_AUTHORING,
    LifecycleStage.TEST_AUTHORING: LifecycleStage.IMPLEMENTING,
    LifecycleStage.IMPLEMENTING: LifecycleStage.REVIEWING,
    LifecycleStage.REVIEWING: LifecycleStage.PR_VALIDATION,
    LifecycleStage.PR_VALIDATION: LifecycleStage.MERGING,
    LifecycleStage.MERGING: LifecycleStage.MERGED,
}

# Stages an Objective sits at while a worker Session runs. Entered by an
# advance, exited at REAP once the Session's gate evidence verifies.
WORKER_STAGES: frozenset[LifecycleStage] = frozenset(
    {
        LifecycleStage.TEST_AUTHORING,
        LifecycleStage.IMPLEMENTING,
        LifecycleStage.REVIEWING,
        LifecycleStage.PR_VALIDATION,
    }
)

# Terminal lifecycle stages — no successor; the tick loop leaves them be.
TERMINAL_STAGES: frozenset[LifecycleStage] = frozenset(
    {
        LifecycleStage.MERGED,
        LifecycleStage.KILLED,
        LifecycleStage.PARKED,
    }
)

# Stages the orchestrator advances directly (gate is orchestrator-internal or
# human signoff), as opposed to worker-driven stages reaped via a Session.
ORCHESTRATOR_ADVANCE_STAGES: frozenset[LifecycleStage] = frozenset(
    set(HAPPY_PATH_NEXT) - WORKER_STAGES
)

# The gate each worker stage produces evidence for.
GATE_ID_BY_STAGE: dict[LifecycleStage, str] = {
    LifecycleStage.TEST_AUTHORING: "red-tests",
    LifecycleStage.IMPLEMENTING: "green-gate",
    LifecycleStage.REVIEWING: "reviewer",
    LifecycleStage.PR_VALIDATION: "pr-validation",
}
