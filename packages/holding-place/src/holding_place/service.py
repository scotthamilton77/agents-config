"""The Holding Place service — the two orchestrator-facing operations.

`promote(idea_id) -> objective_id` and `create_idea(...) -> idea_id` are the
*only* operations the orchestrator may call (`CONTEXT.md > Holding Place`).
Everything else about Ideas — capture, grooming, shaping, killing — is
Holding-Place-internal and out of the orchestrator's view.
"""

from __future__ import annotations

from collections.abc import Callable

from holding_place.idea import Idea, IdeaStorage, ObjectiveCreator


class NotReadyForPromoteError(RuntimeError):
    """Raised when `promote` is called on an Idea that has not been groomed
    and shaped to the ready-for-promote bar."""


class HoldingPlace:
    """Owns the Idea pipeline and the two-call contract to the orchestrator.

    The `ObjectiveCreator` is injected — the Holding Place does not know it
    is talking to the PDLC WorkTracker, only that the port can mint an
    Objective. `id_factory` supplies ids for Ideas spawned by `create_idea`;
    it is injected so callers control id-allocation (and tests stay
    deterministic).
    """

    def __init__(
        self,
        storage: IdeaStorage,
        creator: ObjectiveCreator,
        *,
        id_factory: Callable[[], str],
    ) -> None:
        self._storage = storage
        self._creator = creator
        self._id_factory = id_factory

    def promote(self, idea_id: str) -> str:
        """Transition a ready Idea into an Objective and return its id.

        Idempotent: a second `promote` of an already-promoted Idea returns
        the original Objective id without creating a duplicate. The
        Objective is created with `originating_idea_id` set to this Idea, so
        the work tracker can trace the Objective back to its origin.
        """
        idea = self._storage.get(idea_id)
        if idea.promoted_objective_id is not None:
            return idea.promoted_objective_id
        if not idea.ready_for_promote:
            raise NotReadyForPromoteError(idea_id)
        objective_id = self._creator.create_objective(
            parent_id=None,
            objective_type="task",
            title=idea.title,
            body=idea.body,
            originating_idea_id=idea.id,
        )
        self._storage.put(idea.with_promotion(objective_id))
        return objective_id

    def create_idea(self, *, decomposition_of: str, title: str, body: str) -> str:
        """Spawn a fresh Idea for a decomposed sub-unit of a Container.

        Children of an oversized Container re-enter as Ideas here (NOT as
        direct Objectives), so the grooming/shaping pipeline catches them
        before they reach the FSM. Returns the new Idea id.
        """
        idea = Idea(
            id=self._id_factory(),
            title=title,
            body=body,
            ready_for_promote=False,
            decomposition_of=decomposition_of,
        )
        self._storage.put(idea)
        return idea.id
