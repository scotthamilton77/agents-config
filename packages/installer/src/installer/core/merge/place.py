"""Shared collision-resolving placement of a StagedItem into a StagingPlan.

``place_resolved`` is the one primitive both base staging (``staging._add_item``,
Phases 1-5) and plugin overlay (``overlay._place``, Phase 6) use to land an item
at its destination: store it when the slot is free, else resolve the collision
through the merge registry. Callers fetch the existing occupant once and hand it
in, so every path does a single ``plan.items`` lookup.

Overlay's carrier-merge special case (disjoint-DIR file merge for a
``shared_carrier`` directory) is intercepted by ``_place`` *before* this helper;
``place_resolved`` is the non-carrier resolution shared by both callers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from installer.core.merge.registry import MergeRegistry
    from installer.core.model import StagedItem, StagingPlan


def place_resolved(
    plan: StagingPlan,
    incoming: StagedItem,
    existing: StagedItem | None,
    registry: MergeRegistry,
) -> None:
    """Store ``incoming`` at its ``dest_relpath`` in ``plan``.

    When ``existing`` is ``None`` the slot is free and ``incoming`` is stored
    as-is. Otherwise the registry's strategy for ``(incoming.kind,
    incoming.namespace)`` resolves the collision, joining ``existing`` THEN
    ``incoming``; the resulting item replaces the slot. A fatal strategy raises
    instead of returning.
    """
    if existing is None:
        plan.items[incoming.dest_relpath] = incoming
    else:
        plan.items[incoming.dest_relpath] = registry.resolve(
            incoming.kind, incoming.namespace
        ).merge(existing, incoming)
