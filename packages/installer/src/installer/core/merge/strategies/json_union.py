"""Deep union-merge strategy for ``(SETTINGS_JSON, *)`` collisions.

When two ``settings.json`` payloads (e.g. a tool's and a plugin's) collide at
the same destination they are not a conflict — they are combined. This is the
Python port of the jq program at ``scripts/install.sh:431-456``; the bash
installer's observable behaviour is the contract this module matches. The merge
rules and the *structural* output formatting (2-space indent, object key order,
trailing newline) mirror ``jq .``; lexical number normalisation is the one
deliberate exception (quirk 3 below):

- dict + dict at a shared key -> recurse (deep merge);
- array + array at a shared key -> concatenate then jq-``unique`` (sort by
  jq's total order, then dedupe by value);
- scalar conflict at a shared key -> KEEP EXISTING;
- type mismatch at a shared key (dict-vs-scalar, array-vs-scalar, …)
  -> KEEP EXISTING;
- key only in incoming -> ADD it; key only in existing -> keep it;
- a top-level operand that is not an object -> the result is ``existing`` whole.

Two jq quirks are reproduced deliberately rather than "fixed":

1. **Empty-object quirk.** jq builds the merged object with ``… | add``; over
   an empty key-list ``[] | add`` evaluates to ``null``. So deep-merging two
   objects whose key-merge yields no keys produces JSON ``null`` — including
   nested ``{}`` + ``{}`` keys, which become ``null`` at that key.
2. **jq total order.** jq sorts and dedupes arrays by its own total order:
   ``null < false < true < number < string < array < object``, with arrays
   compared element-wise (length tiebreak) and objects compared by their
   sorted key-array first then their values in key order. ``_jq_sort_key``
   reproduces that ordering.

One jq behaviour is deliberately NOT reproduced:

3. **Number lexemes are not byte-preserved.** jq echoes a number's source form
   (``1e3`` stays ``1E+3``, ``1.50`` stays ``1.50``); this port round-trips
   through ``json.loads``/``json.dumps`` and canonicalises them (``1e3`` ->
   ``1000.0``, ``1.50`` -> ``1.5``). Common-case numbers round-trip faithfully
   (``1`` vs ``1.0`` stay distinct; integral floats and big ints keep their
   form). Accepted, not fixed: every ``settings.json`` source is canonical-
   number JSON — no template carries scientific-notation or trailing-zero
   literals — and the golden-master parity suite is the backstop should one
   ever appear.

Output bytes are canonical ``jq .`` formatting: 2-space indent and a single
trailing newline. ``jq .`` does NOT sort object keys — it preserves each
object's insertion order. The bash installer emits the merge with ``jq .``
(``install.sh:456``), not ``jq -S``, so this port matches that: the deep-merge
skeleton is constructed in sorted-key order by :func:`_deep_merge` (mirroring
jq's ``($a|keys)+($b|keys)|unique``, which sorts by Unicode codepoint), while
any object jq passes through verbatim — a key present on only one side whose
value is an object, or an object nested inside an array — keeps its original
insertion order.

Irreconcilable input (a ``None`` side, or bytes that are not valid JSON) raises
:class:`CollisionError` naming both source paths, mirroring jq aborting on bad
input rather than silently fabricating an empty object.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from installer.core.merge.base import CollisionError
from installer.core.model import StagedItem

# jq total-order type ranks. Lower sorts first. ``bool`` is checked before
# ``int`` because ``bool`` is a subclass of ``int`` in Python.
_RANK_NULL = 0
_RANK_BOOL = 1
_RANK_NUMBER = 2
_RANK_STRING = 3
_RANK_ARRAY = 4
_RANK_OBJECT = 5


def _jq_sort_key(value: Any) -> tuple[Any, ...]:
    """Map a JSON value to a sortable key reproducing jq's total order.

    Type rank dominates (``null < bool < number < string < array < object``);
    within a rank values compare naturally. Containers recurse so arrays
    compare element-wise and objects compare by their sorted key-array first,
    then by their values in key order — matching jq's ``sort``/``unique``.
    """
    if value is None:
        return (_RANK_NULL,)
    if isinstance(value, bool):
        # false < true; rely on int(False)=0 < int(True)=1.
        return (_RANK_BOOL, int(value))
    if isinstance(value, (int, float)):
        try:
            return (_RANK_NUMBER, float(value))
        except OverflowError:
            # A Python int too large for a float (valid JSON, e.g. a 400-digit
            # integer literal): jq stores numbers as IEEE doubles, so an
            # out-of-range int collapses to +/-inf. Mirror that here for
            # ordering only — the element's exact value is preserved in the
            # output bytes (json.dumps keeps int precision); just this sort key
            # approximates, which would otherwise crash with OverflowError.
            return (_RANK_NUMBER, float("inf") if value > 0 else float("-inf"))
    if isinstance(value, str):
        return (_RANK_STRING, value)
    if isinstance(value, list):
        return (_RANK_ARRAY, [_jq_sort_key(elem) for elem in value])
    # dict: keys sorted first, then the values in that key order.
    keys = sorted(value.keys())
    return (
        _RANK_OBJECT,
        [_jq_sort_key(k) for k in keys],
        [_jq_sort_key(value[k]) for k in keys],
    )


def _union_arrays(existing: list[Any], incoming: list[Any]) -> list[Any]:
    """jq ``[a, b] | add | unique``: concatenate, sort by jq's total order,
    then drop adjacent duplicates (values with an equal sort key are jq-equal,
    which correctly treats ``1`` and ``1.0`` as one while keeping ``true`` and
    ``1`` distinct)."""
    # Compute each element's sort key once, then sort + dedupe by it. Sort on
    # the key alone (``key=`` on the pair's first item): when two keys tie the
    # raw values must not be compared, since dicts/lists are not orderable.
    keyed = sorted(
        ((_jq_sort_key(elem), elem) for elem in (*existing, *incoming)),
        key=lambda pair: pair[0],
    )
    deduped: list[Any] = []
    last_key: tuple[Any, ...] | None = None
    last_elem: Any = None
    for key, elem in keyed:
        # Dedupe on the sort key, but break ties by Python value equality so a
        # lossy sort key cannot collapse two distinct values. The overflow
        # guard in ``_jq_sort_key`` maps every huge positive int to the same
        # +inf key (and every huge negative int to -inf), so ``10**400`` and
        # ``10**401`` share a key while being distinct, full-precision integers
        # that ``json.dumps`` preserves verbatim. Without the value check the
        # second would be silently dropped, losing data. ``1`` vs ``1.0`` still
        # dedupe because ``1 == 1.0`` in Python, matching jq.
        if key != last_key or elem != last_elem:
            deduped.append(elem)
            last_key = key
            last_elem = elem
    return deduped


def _deep_merge(existing: Any, incoming: Any) -> Any:
    """Port of the jq ``deep_merge`` def. Only object+object recurses; every
    other top-level shape returns ``existing`` whole. The merged object is
    built via ``add`` over per-key fragments, so a key-merge yielding no keys
    collapses to ``None`` (the jq ``[] | add`` quirk)."""
    if not (isinstance(existing, dict) and isinstance(incoming, dict)):
        return existing

    # jq builds the merged object via ``($a|keys)+($b|keys)|unique|map(…)``,
    # and ``keys|unique`` sorts the key-set by Unicode codepoint. Building the
    # dict in sorted-key order here reproduces that: the CONSTRUCTED skeleton
    # is sorted at every recursion level, while objects passed through verbatim
    # (one-side-only object values, objects nested inside arrays) are never
    # rebuilt and so keep their original insertion order — matching ``jq .``,
    # which sorts only what the program constructs. ``_to_jq_bytes`` therefore
    # serialises with ``sort_keys=False``.
    merged: dict[str, Any] = {}
    for key in sorted(set(existing) | set(incoming)):
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

    # jq ``[] | add`` is null: an object that merged to no keys becomes null.
    if not merged:
        return None
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


def _to_jq_bytes(value: Any) -> bytes:
    """Serialise to canonical ``jq .`` formatting: 2-space indent, single
    trailing newline, and — crucially — each object's keys in the order it
    already holds them (``sort_keys=False``). ``jq .`` does NOT sort keys; it
    preserves every object's insertion order. The deep-merge skeleton is built
    in sorted order by :func:`_deep_merge` (mirroring jq's ``keys|unique``), so
    objects jq constructs come out sorted while objects jq passes through
    verbatim keep their original order. Sorting here would wrongly re-order the
    latter (e.g. a one-side-only ``env`` block, or an object inside an array)."""
    text = json.dumps(value, indent=2, sort_keys=False, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


class JsonUnionStrategy:
    """Deep union-merge two colliding JSON payloads, jq-parity.

    Honours the ``MergeStrategy`` protocol structurally. The synthesised item
    preserves the shared key fields (``dest_relpath``, ``kind``, ``namespace``
    — identical on both by definition of the collision), sets ``content`` to
    the canonical merged bytes, and takes ``provenance`` and ``source_path``
    from ``incoming``.
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
        return replace(incoming, content=_to_jq_bytes(merged))
