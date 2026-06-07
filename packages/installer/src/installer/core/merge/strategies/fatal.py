"""Fatal-collision strategy: refuse to merge irreconcilable kinds.

Some collisions cannot be resolved by synthesising a merged item — two
distinct ``commands`` / ``skills`` / ``agents`` markdown files, or two
directory units, at the same destination represent a genuine conflict the
installer must surface rather than silently pick a winner.

:class:`FatalStrategy` is the registry's answer for those keys
(``(NAMESPACED_MD, {"commands", "skills", "agents"})`` and
``FileKind.DIR``). Its :meth:`~FatalStrategy.merge` ALWAYS raises
:class:`CollisionError` naming both colliding source paths — it never
returns a :class:`StagedItem`.
"""

from __future__ import annotations

from typing import NoReturn

from installer.core.merge.base import CollisionError
from installer.core.model import StagedItem


class FatalStrategy:
    """Resolve an irreconcilable collision by raising.

    Structurally a :class:`~installer.core.merge.base.MergeStrategy`, but it
    never produces a merged item: every call raises
    :class:`CollisionError` carrying both colliding source paths.
    """

    def merge(self, existing: StagedItem, incoming: StagedItem) -> NoReturn:
        """Raise :class:`CollisionError` naming both source paths.

        The ``-> NoReturn`` return annotation documents that this method
        never yields a value; it widens to the ``MergeStrategy`` protocol's
        ``-> StagedItem`` because ``NoReturn`` is a subtype of every type.
        """
        raise CollisionError(existing.source_path, incoming.source_path)
