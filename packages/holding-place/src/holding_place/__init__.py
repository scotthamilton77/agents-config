"""Holding Place — the peer subsystem that owns the Idea pipeline.

Per ADR-0001 the Holding Place is a **peer** of the PDLC Orchestrator, not
owned by it. It
holds the `Idea` primitive and exposes exactly two orchestrator-facing
operations — `promote(idea_id) -> objective_id` and
`create_idea(decomposition_of=...)` — across a documented contract.

This package imports nothing from `pdlc`. The one outbound dependency it
needs — "something that can create an Objective" — is expressed as the
`ObjectiveCreator` port it *owns* (dependency-inversion). The orchestrator's
WorkTracker satisfies that port structurally; the seam is the contract, not
a shared import.
"""

from holding_place.idea import (
    Idea,
    IdeaStorage,
    ObjectiveCreator,
)
from holding_place.service import (
    HoldingPlace,
    NotReadyForPromoteError,
)
from holding_place.storage import FilesystemIdeaStorage

__all__ = [
    "FilesystemIdeaStorage",
    "HoldingPlace",
    "Idea",
    "IdeaStorage",
    "NotReadyForPromoteError",
    "ObjectiveCreator",
]
