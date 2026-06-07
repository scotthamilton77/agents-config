"""Append-merge strategy for ``(NAMESPACED_MD, namespace="rules")`` collisions.

Two same-name rule files from different sources (e.g. a tool's ``rules/foo.md``
and a plugin's ``rules/foo.md``) are not a conflict — they are additive. This
strategy concatenates both bodies into one, ``existing`` THEN ``incoming``,
joined by the canonical rules separator ``b"\\n---\\n"`` (mirroring the
ALL-RULES join in ``core/templates.py``).

Empty-body edges are handled so the result never carries a stray leading or
trailing separator: a missing side is simply dropped from the join rather than
emitting ``b"\\n---\\n"`` against empty bytes.
"""

from __future__ import annotations

from dataclasses import replace

from installer.core.model import StagedItem

_SEPARATOR = b"\n---\n"


class AppendRulesStrategy:
    """Concatenate two colliding rule bodies, ``existing`` then ``incoming``.

    Honours the ``MergeStrategy`` protocol structurally. The synthesised item
    preserves the shared key fields (``dest_relpath``, ``kind``, ``namespace``
    — identical on both by definition of the collision), sets ``content`` to
    the joined bytes, and takes ``provenance`` and ``source_path`` from
    ``incoming``.
    """

    def merge(self, existing: StagedItem, incoming: StagedItem) -> StagedItem:
        sides = [side for side in (existing.content, incoming.content) if side]
        merged = _SEPARATOR.join(sides)
        return replace(
            incoming,
            content=merged,
        )
