"""The Idea primitive, the storage seam, and the ObjectiveCreator port.

These three types are the Holding Place's public vocabulary:

- `Idea` — a raw thought worth preserving but not yet committed to work
  (see `CONTEXT.md > Idea`). Distinct from an Objective.
- `IdeaStorage` — the storage seam. The MVP backend is filesystem
  (`FilesystemIdeaStorage`); future backends (Dolt, SQLite, cloud KV) swap
  by configuration, parallel to the Orchestrator's WorkTracker adapter.
- `ObjectiveCreator` — the *outbound* port the Holding Place needs to
  fulfil `promote`. It is owned here, not imported from `pdlc`: the
  consumer defines the interface it depends on (dependency-inversion), so
  the peer boundary stays a contract rather than a code-level coupling.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Idea:
    """A captured Idea living in the Holding Place.

    `ready_for_promote` is the Holding-Place-side signal that grooming and
    shaping are complete — the tracer seeds it directly, standing in for the
    Idea Curator's judgment. `promoted_objective_id` records the Objective a
    successful `promote` created, making `promote` idempotent: a second call
    returns the same id rather than minting a duplicate Objective.
    `decomposition_of`, when set, marks an Idea spawned by a Container's
    Decomposition (the `create_idea` path).
    """

    id: str
    title: str
    body: str
    ready_for_promote: bool = False
    decomposition_of: str | None = None
    promoted_objective_id: str | None = None

    def with_promotion(self, objective_id: str) -> Idea:
        """Return a copy stamped with the Objective this Idea promoted into."""
        return replace(self, promoted_objective_id=objective_id)


@runtime_checkable
class IdeaStorage(Protocol):
    """Persistence seam for Ideas. The MVP backend is filesystem; the
    Protocol is what lets a future backend swap in by configuration."""

    def get(self, idea_id: str) -> Idea: ...  # pragma: no cover
    def put(self, idea: Idea) -> None: ...  # pragma: no cover
    def exists(self, idea_id: str) -> bool: ...  # pragma: no cover


@runtime_checkable
class ObjectiveCreator(Protocol):
    """The outbound port `promote` depends on — "something that can create an
    Objective in the work tracker." Owned by the Holding Place; the PDLC
    WorkTracker satisfies it structurally. `originating_idea_id` propagates
    the provenance backreference onto the created Objective so the work
    tracker can correlate it to its originating Idea."""

    def create_objective(  # pragma: no cover
        self,
        *,
        parent_id: str | None,
        objective_type: str,
        title: str,
        body: str,
        originating_idea_id: str | None,
    ) -> str: ...
