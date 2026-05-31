"""The TransitionLog event schema.

`OrchestratorStateRepo.TransitionLog` is append-only; one `TransitionEntry`
records one lifecycle event. Fields mirror the orchestrator core design's
"Transition log event schema" table. `ts` is a logical clock (a monotonic
integer the orchestrator stamps), not wall-clock — deterministic and enough
for ordering; a real timestamp is an implementation-child concern.
"""

from __future__ import annotations

from dataclasses import dataclass

from pdlc.lifecycle import Actor, LifecycleStage


@dataclass(frozen=True, slots=True)
class TransitionEntry:
    """One append-only event in an Objective's lifecycle.

    `from_stage` is None for a creation event; `to_stage` is None for a
    non-advance event (neither occurs on the happy path, where every entry is
    a stage advance). `gate_evidence_ref` points at the gate-evidence YAML for
    worker-reap advances and is None otherwise.
    """

    ts: int
    objective_id: str
    from_stage: LifecycleStage | None
    to_stage: LifecycleStage | None
    reason: str
    actor: Actor
    config_hash: str
    session_id: str | None = None
    gate_evidence_ref: str | None = None
