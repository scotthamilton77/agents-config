"""Orchestrator-owned Objective state.

`Provenance` and `ObjectiveLifecycleState` are the slices of the Objective
primitive that live in the Orchestrator's own store (NOT the tracker), per
the State Ownership boundary. The tracker owns identity, structure, and the
coarse lifecycle_status projection; everything here — strike counters, the
transition log, frozen-branch refs — is orchestrator-canonical.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pdlc.lifecycle import LifecycleStage
from pdlc.transition_log import TransitionEntry


@dataclass(frozen=True, slots=True)
class Provenance:
    """Nullable backreferences recording where an Objective came from. For
    the tracer only `originating_idea_id` is populated (set at promotion)."""

    originating_idea_id: str | None = None
    decomposition_of: str | None = None
    discovered_from: str | None = None
    autopsy_route: str | None = None


@dataclass(slots=True)
class ObjectiveLifecycleState:
    """The Orchestrator's per-Objective mutable state. `strike_counts` is the
    input to the 3-Strike Circuit Breaker (all zero on the happy path);
    `transition_log` is the append-only audit of stage advances."""

    strike_counts: dict[LifecycleStage, int] = field(default_factory=dict)
    transition_log: list[TransitionEntry] = field(default_factory=list)
    frozen_branch_ref: str | None = None
    terminal_disposition: str | None = None
    needs_reconcile: bool = False
