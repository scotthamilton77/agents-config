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

from installer.core.model import StagedItem, contributions_of

SEPARATOR = b"\n---\n"


class AppendRulesStrategy:
    """Concatenate two colliding rule bodies, ``existing`` then ``incoming``.

    Honours the ``MergeStrategy`` protocol structurally. The synthesised item
    preserves the shared key fields (``dest_relpath``, ``kind``, ``namespace``
    — identical on both by definition of the collision), sets ``content`` to
    the joined bytes, and takes ``provenance`` and ``source_path`` from
    ``incoming``.

    It also records each side as a ``Contribution``, so the destination stays
    decomposable after the join. Every later reader of a rule's front matter —
    the admission bar above all — asks a question about one authored file, and
    a merged blob answers it for whichever file happens to be first. Flattening
    a chain of merges into one contribution list rather than nesting keeps that
    list a flat sequence of authored files, which is what those readers want.
    A side that contributed no bytes contributes no identity either: naming an
    empty file as a contributor would put a record-less blank on the gate's
    report with nothing behind it.
    """

    def merge(self, existing: StagedItem, incoming: StagedItem) -> StagedItem:
        parts = tuple(
            part for side in (existing, incoming) for part in contributions_of(side) if part.content
        )
        return replace(
            incoming,
            content=SEPARATOR.join(part.content for part in parts),
            contributions=parts,
        )
