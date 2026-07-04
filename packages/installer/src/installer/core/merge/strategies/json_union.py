"""Deep union-merge strategy for ``(SETTINGS_JSON, *)`` collisions.

When two ``settings.json`` payloads (e.g. a tool's and a plugin's) collide at
the same destination they are not a conflict — they are combined into a single
semantic deep-merge:

- dict + dict at a shared key -> recurse (deep merge);
- array + array at a shared key -> concatenate, then dedupe by value keeping
  first-seen order;
- scalar conflict at a shared key -> KEEP EXISTING;
- type mismatch at a shared key (dict-vs-scalar, array-vs-scalar, …)
  -> KEEP EXISTING;
- key only in incoming -> ADD it; key only in existing -> keep it;
- a top-level operand that is not an object -> the result is ``existing`` whole;
- two empty objects merge to ``{}``, never ``null``.

Output is 2-space indent and a single trailing newline. Key order PRESERVES
the existing side: a key carried through or recursed from existing keeps its
original position; a key present only in incoming is appended after, in
incoming's own order. This applies recursively at every nested dict level, so
a user's before/after settings.json diff stays readable rather than being
reshuffled into sorted order.

Irreconcilable input (a ``None`` side, or bytes that are not valid JSON) raises
:class:`CollisionError` naming both source paths, rather than silently
fabricating an empty object.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from installer.core.merge.base import CollisionError
from installer.core.model import StagedItem


def _union_arrays(existing: list[Any], incoming: list[Any]) -> list[Any]:
    """Concatenate two arrays and dedupe by value, preserving first-seen order.

    Equality is Python ``==``, so ``1`` and ``1.0`` collapse to one (first seen
    wins) while distinct values — including unhashable ``dict`` and ``list``
    elements, compared structurally — are each kept once. ``==`` also collapses
    ``True``/``1`` and ``False``/``0`` across the bool/number boundary; accepted
    because settings arrays never mix bare booleans with bare numbers."""
    deduped: list[Any] = []
    for elem in (*existing, *incoming):
        if elem not in deduped:
            deduped.append(elem)
    return deduped


def _deep_merge(existing: Any, incoming: Any) -> Any:
    """Recursively union two JSON values. Only object+object merges; every
    other top-level shape returns ``existing`` whole. At a shared key two dicts
    recurse, two lists union, and anything else (scalar conflict or type
    mismatch) keeps ``existing``; keys present on only one side are carried
    through. Key order PRESERVES existing's order first, then appends keys
    found only in incoming, in incoming's own order — iterating ``existing``
    then ``incoming`` (skipping keys already placed) achieves this without a
    separate sort step."""
    if not (isinstance(existing, dict) and isinstance(incoming, dict)):
        return existing

    merged: dict[str, Any] = {}
    for key in (*existing, *incoming):
        if key in merged:
            continue
        in_existing = key in existing
        in_incoming = key in incoming
        if in_existing and in_incoming:
            ev, iv = existing[key], incoming[key]
            if isinstance(ev, list) and isinstance(iv, list):
                merged[key] = _union_arrays(ev, iv)
            elif isinstance(ev, dict) and isinstance(iv, dict):
                merged[key] = _deep_merge(ev, iv)
            else:
                # scalar conflict OR type mismatch -> keep existing.
                merged[key] = ev
        elif in_existing:
            merged[key] = existing[key]
        else:
            merged[key] = incoming[key]

    return merged


def _parse(content: bytes | None) -> Any:
    """Parse ``content`` as JSON, or raise ``ValueError`` for irreconcilable
    input. ``None`` content raises directly; malformed JSON and non-UTF-8 bytes
    raise ``JSONDecodeError`` / ``UnicodeDecodeError`` (both ``ValueError``
    subclasses). :meth:`JsonUnionStrategy.merge` maps any of these to one
    ``CollisionError`` naming both source paths in canonical order, so the
    failure is reported the same way regardless of which side is unparseable."""
    if content is None:
        raise ValueError
    return json.loads(content)


def _to_bytes(value: Any) -> bytes:
    """Serialise to JSON: 2-space indent, single trailing newline. Key order is
    whatever ``value``'s dict order already is — :func:`_deep_merge` is
    responsible for that order being existing-first, incoming-only-appended;
    this function does not sort or otherwise reorder it."""
    text = json.dumps(value, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def merge_settings_bytes(existing: bytes, incoming: bytes) -> bytes:
    """Deep union-merge two settings.json byte payloads, preserving existing's
    key order.

    The reusable core of the union: parse both, deep-merge (``existing`` wins on a
    scalar conflict, arrays union, keys present on only one side carried through,
    existing's key order preserved with incoming-only keys appended after), and
    serialise. The sync engine uses it to union a staged settings.json into the
    user's existing dest file so user values — and their order, for a readable
    diff — survive an install. Raises ``ValueError`` if either side is not valid
    JSON — the caller decides how to recover.
    """
    return _to_bytes(_deep_merge(json.loads(existing), json.loads(incoming)))


class JsonUnionStrategy:
    """Deep union-merge two colliding JSON payloads.

    Honours the ``MergeStrategy`` protocol structurally. The synthesised item
    preserves the shared key fields (``dest_relpath``, ``kind``, ``namespace``
    — identical on both by definition of the collision), sets ``content`` to
    the merged bytes, and takes ``provenance`` and ``source_path`` from
    ``incoming``.
    """

    def merge(self, existing: StagedItem, incoming: StagedItem) -> StagedItem:
        # None content or unparseable bytes on either side are irreconcilable;
        # surface as one CollisionError naming both paths in canonical order.
        try:
            existing_json = _parse(existing.content)
            incoming_json = _parse(incoming.content)
        except ValueError as exc:
            raise CollisionError(existing.source_path, incoming.source_path) from exc
        merged = _deep_merge(existing_json, incoming_json)
        return replace(incoming, content=_to_bytes(merged))
