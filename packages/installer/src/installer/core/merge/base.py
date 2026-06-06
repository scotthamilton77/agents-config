"""Merge contract shared by every collision strategy.

Two symbols form the contract:

- :class:`MergeStrategy` — the structural protocol every strategy honours:
  ``merge(existing, incoming) -> StagedItem``. A strategy is invoked when an
  ``incoming`` item collides with an already-staged ``existing`` at the same
  ``dest_relpath`` (so ``dest_relpath``, ``kind``, and ``namespace`` are
  identical on both by definition of the collision).
- :class:`CollisionError` — the shared *fatal-collision* signal, raised by
  the fatal strategy when two sources may not be merged. It is a
  ``RuntimeError`` so it is distinct from the registry's lookup-miss error,
  which is a programmer/wiring error rather than a real file collision.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from installer.core.model import StagedItem


@runtime_checkable
class MergeStrategy(Protocol):
    """Resolve a collision between two items at the same ``dest_relpath``.

    Returns the item to stage. A strategy that synthesises a merged item
    preserves the shared key fields (``dest_relpath``, ``kind``,
    ``namespace`` — identical on both by definition of the collision),
    sets ``content`` to the merged bytes, and takes ``provenance`` and
    ``source_path`` from ``incoming``.
    """

    def merge(
        self, existing: StagedItem, incoming: StagedItem
    ) -> StagedItem: ...  # pragma: no cover


class CollisionError(RuntimeError):
    """Raised when two sources collide at one destination and may not be
    merged. The message names BOTH colliding source paths; structured
    attributes (``existing`` / ``incoming``) let callers and tests assert
    on data rather than parsing the prose."""

    def __init__(self, existing: Path, incoming: Path) -> None:
        super().__init__(
            f"Irreconcilable collision: {existing} and {incoming} "
            f"both target the same destination and cannot be merged."
        )
        self.existing = existing
        self.incoming = incoming
