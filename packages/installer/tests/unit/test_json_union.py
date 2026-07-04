"""Unit tests for installer.core.merge.strategies.json_union.

Each test pins a coded decision in the semantic deep-union-merge contract for
``(SETTINGS_JSON, *)`` collisions:

- dict + dict at a shared key -> recurse (deep merge);
- array + array at a shared key -> concatenate, dedupe by value, keep
  first-seen order;
- scalar conflict at a shared key -> KEEP EXISTING;
- type mismatch at a shared key (dict-vs-scalar, array-vs-scalar, etc.)
  -> KEEP EXISTING;
- key only in incoming -> ADD it; key only in existing -> keep it;
- top-level non-object operand -> the result is ``existing`` whole;
- two empty objects merge to ``{}`` (not null);
- output bytes are 2-space indent, single trailing newline, and PRESERVE
  the existing side's key order — keys only in incoming are appended after,
  in incoming order — recursively at every nested dict level;
- the synthesised item takes provenance + source_path from incoming and
  preserves the shared key fields.

Tests that would only verify Python/stdlib semantics (``json.loads`` round
trips, frozen-dataclass immutability) are deliberately absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from installer.core.merge.base import CollisionError
from installer.core.merge.strategies.json_union import JsonUnionStrategy, merge_settings_bytes
from installer.core.model import FileKind, Provenance, StagedItem


def _item(
    obj: object | None,
    *,
    source: str = "/src/a/settings.json",
    dest: str = "settings.json",
    provenance: Provenance | None = None,
    raw: bytes | None = None,
) -> StagedItem:
    """Build a SETTINGS_JSON StagedItem. ``obj`` is serialised to bytes;
    pass ``raw`` to inject deliberately malformed bytes instead."""
    if raw is not None:
        content: bytes | None = raw
    elif obj is None:
        content = None
    else:
        content = json.dumps(obj).encode("utf-8")
    return StagedItem(
        source_path=Path(source),
        dest_relpath=Path(dest),
        kind=FileKind.SETTINGS_JSON,
        namespace=None,
        provenance=provenance or Provenance(kind="tool", name="claude"),
        content=content,
    )


def _merge(existing_obj: object, incoming_obj: object) -> object:
    """Run the strategy and parse the merged bytes back to a Python object."""
    merged = JsonUnionStrategy().merge(_item(existing_obj), _item(incoming_obj))
    assert merged.content is not None
    return json.loads(merged.content)


# --- key presence rules ---------------------------------------------------


def test_key_only_in_incoming_is_added() -> None:
    """A key present only in incoming is added to the merged object."""
    assert _merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_key_only_in_existing_is_kept() -> None:
    """A key present only in existing survives the merge."""
    assert _merge({"a": 1}, {"b": 2})["a"] == 1


# --- scalar / type-mismatch rules (KEEP EXISTING) -------------------------


def test_scalar_conflict_keeps_existing() -> None:
    """When both sides have a scalar at the same key, existing wins."""
    assert _merge({"a": 1}, {"a": 99}) == {"a": 1}


def test_string_scalar_conflict_keeps_existing() -> None:
    """Scalar-keep-existing applies to strings, not just numbers."""
    assert _merge({"a": "old"}, {"a": "new"}) == {"a": "old"}


def test_type_mismatch_dict_vs_scalar_keeps_existing_dict() -> None:
    """Existing dict vs incoming scalar at the same key: keep the dict."""
    assert _merge({"x": {"deep": 1}}, {"x": 5}) == {"x": {"deep": 1}}


def test_type_mismatch_array_vs_scalar_keeps_existing_array() -> None:
    """Existing array vs incoming scalar at the same key: keep the array."""
    assert _merge({"x": [1, 2]}, {"x": "str"}) == {"x": [1, 2]}


def test_type_mismatch_scalar_vs_dict_keeps_existing_scalar() -> None:
    """Existing scalar vs incoming dict at the same key: keep the scalar
    (the recurse/union branches require BOTH sides to match type)."""
    assert _merge({"x": 5}, {"x": {"deep": 1}}) == {"x": 5}


def test_null_is_a_scalar_kept_on_conflict() -> None:
    """null is treated as an ordinary scalar: existing null beats incoming 2,
    and existing 1 beats incoming null."""
    assert _merge({"x": None, "y": 1}, {"x": 2, "y": None}) == {"x": None, "y": 1}


# --- recursion rule (dict + dict) -----------------------------------------


def test_nested_dicts_recurse_and_union_keys() -> None:
    """Two dicts at the same key deep-merge: shared scalar keeps existing,
    disjoint keys from both sides are unioned."""
    result = _merge({"n": {"x": 1, "y": 2}}, {"n": {"y": 99, "z": 3}})
    assert result == {"n": {"x": 1, "y": 2, "z": 3}}


def test_deeply_nested_dicts_recurse() -> None:
    """Recursion is unbounded: a scalar conflict three levels deep still
    keeps existing while sibling keys union."""
    result = _merge(
        {"a": {"b": {"c": 1, "keep": "old"}}},
        {"a": {"b": {"c": 9, "add": "new"}}},
    )
    assert result == {"a": {"b": {"c": 1, "keep": "old", "add": "new"}}}


# --- array union rule (concatenate + dedupe, first-seen order) ------------


def test_scalar_arrays_union_dedupe_first_seen_order() -> None:
    """Conflicting scalar arrays concatenate, then dedupe by value while
    preserving first-seen order (NOT sorted)."""
    assert _merge({"arr": [3, 1, 2]}, {"arr": [2, 4, 1]}) == {"arr": [3, 1, 2, 4]}


def test_array_union_dedupes_within_a_single_side() -> None:
    """Dedupe collapses duplicates that already exist within one side as well
    as across sides."""
    assert _merge({"x": [1, 1, 2, 2]}, {"x": [2, 3, 3]}) == {"x": [1, 2, 3]}


def test_array_union_dedupes_int_and_float_with_same_value() -> None:
    """Python ``==`` treats 1 and 1.0 as equal, so they dedupe to one — and
    first-seen wins, so the int ``1`` survives."""
    assert _merge({"x": [1]}, {"x": [1.0, 2]}) == {"x": [1, 2]}


def test_array_union_collapses_bool_and_int_accepted_edge() -> None:
    """``==`` dedupe collapses True/1 (and False/0) across the bool/number
    boundary — first-seen wins. Accepted: settings arrays never mix bare
    booleans with bare numbers, so there is no live data-loss path. Pinned so a
    future change to dedupe semantics must confront the trade-off."""
    assert _merge({"x": [1]}, {"x": [True, 2]}) == {"x": [1, 2]}
    assert _merge({"x": [False]}, {"x": [0, 3]}) == {"x": [False, 3]}


def test_array_union_mixed_types_keep_first_seen_order() -> None:
    """A mixed-type array concatenates and dedupes by value, keeping
    first-seen order — no type-rank sorting."""
    result = _merge(
        {"x": [3, "b", True, None]},
        {"x": ["a", False, 2]},
    )
    assert result == {"x": [3, "b", True, None, "a", False, 2]}


def test_array_union_of_objects_dedupe_first_seen() -> None:
    """Arrays of objects concatenate and dedupe by value (==) — unhashable
    dict elements are compared structurally — keeping first-seen order."""
    result = _merge(
        {"perms": [{"k": "v2"}, {"k": "v1"}]},
        {"perms": [{"k": "v1"}, {"k": "v3"}]},
    )
    assert result == {"perms": [{"k": "v2"}, {"k": "v1"}, {"k": "v3"}]}


def test_array_union_of_nested_arrays_dedupe_first_seen() -> None:
    """Nested arrays concatenate and dedupe by value (unhashable list elements
    compared structurally), keeping first-seen order."""
    result = _merge({"x": [[1, 2], [1]]}, {"x": [[1, 2], [1, 2, 0]]})
    assert result == {"x": [[1, 2], [1], [1, 2, 0]]}


# --- empty-container edges ------------------------------------------------


def test_empty_arrays_union_to_empty_array() -> None:
    """Two empty arrays at a key union to an empty array, not null."""
    assert _merge({"x": []}, {"x": []}) == {"x": []}


def test_empty_array_unions_with_populated_array() -> None:
    """An empty array on one side contributes nothing; the other side's
    elements survive in first-seen order."""
    assert _merge({"x": []}, {"x": [2, 1]}) == {"x": [2, 1]}


def test_disjoint_empty_containers_are_preserved() -> None:
    """Keys carrying empty {} / [] that appear on only one side pass through
    unchanged (no collision occurs, so no merge rule fires)."""
    result = _merge({"a": {}, "c": 1}, {"b": [], "d": 2})
    assert result == {"a": {}, "b": [], "c": 1, "d": 2}


def test_merging_two_empty_objects_yields_empty_object() -> None:
    """Two empty objects merge to an empty object ``{}`` — the semantic
    deep-merge does NOT reproduce jq's ``[] | add == null`` wart."""
    merged = JsonUnionStrategy().merge(_item({}), _item({}))
    assert merged.content is not None
    assert json.loads(merged.content) == {}


def test_nested_two_empty_objects_yield_empty_object_at_that_key() -> None:
    """A key holding {} on both sides recurses to an empty object, not null —
    the wart does not propagate through recursion either."""
    assert _merge({"x": {}}, {"x": {}}) == {"x": {}}


# --- top-level type-mismatch rule -----------------------------------------


def test_top_level_existing_object_incoming_array_keeps_existing() -> None:
    """The deep_merge guard requires BOTH operands to be objects; when
    incoming is a non-object the whole existing value is returned."""
    merged = JsonUnionStrategy().merge(_item({"a": 1}), _item([1, 2, 3]))
    assert merged.content is not None
    assert json.loads(merged.content) == {"a": 1}


def test_top_level_existing_array_incoming_object_keeps_existing_array() -> None:
    """When existing itself is a non-object, deep_merge returns it whole
    regardless of incoming being an object."""
    merged = JsonUnionStrategy().merge(_item([1, 2, 3]), _item({"a": 1}))
    assert merged.content is not None
    assert json.loads(merged.content) == [1, 2, 3]


# --- output formatting (order-preserving JSON bytes) -----------------------


def test_output_is_two_space_indented_with_trailing_newline() -> None:
    """Merged bytes are 2-space indent, exactly one trailing newline."""
    merged = JsonUnionStrategy().merge(_item({"b": 1, "a": 2}), _item({"c": 3}))
    assert merged.content == b'{\n  "b": 1,\n  "a": 2,\n  "c": 3\n}\n'


def test_output_preserves_existing_key_order_incoming_only_keys_appended_in_incoming_order() -> (
    None
):
    """Existing key order is preserved as-is; keys present only in incoming are
    appended after, in incoming's own order — no sorting of either group."""
    merged = JsonUnionStrategy().merge(_item({"B": 1, "a": 2, "10": 3, "2": 4}), _item({"A": 5}))
    assert merged.content is not None
    text = merged.content.decode("utf-8")
    assert list(json.loads(text).keys()) == ["B", "a", "10", "2", "A"]
    assert text.index('"B"') < text.index('"a"') < text.index('"10"')
    assert text.index('"10"') < text.index('"2"') < text.index('"A"')


# --- output key order (existing side's order preserved recursively) --------
#
# The merge preserves the EXISTING side's key order at every level — whether
# the object is constructed by the deep-merge or carried through unchanged
# from one side. Keys only in incoming append after, in incoming order.


def test_one_side_only_nested_object_preserves_its_own_order() -> None:
    """A nested object present on only ONE side is serialised in its own
    original key order — no sorting, no reordering."""
    merged = JsonUnionStrategy().merge(
        _item({"env": {"Z": 1, "A": 2, "M": 3}}),
        _item({"other": 1}),
    )
    assert merged.content is not None
    text = merged.content.decode("utf-8")
    assert text.index('"Z"') < text.index('"A"') < text.index('"M"')


def test_object_inside_array_preserves_its_own_order() -> None:
    """An object nested inside an array keeps its own key order — arrays are
    carried through by identity (not reconstructed key-by-key), so there is no
    sorting opportunity either way."""
    merged = JsonUnionStrategy().merge(
        _item({"arr": [{"z": 1, "a": 2}]}),
        _item({"other": 1}),
    )
    assert merged.content is not None
    text = merged.content.decode("utf-8")
    assert text.index('"z"') < text.index('"a"')


def test_deep_merge_preserves_existing_order_at_every_level() -> None:
    """Existing key order is preserved at every recursion level: a nested
    object merged on BOTH sides keeps existing's order with incoming-only keys
    appended after, and so do the top-level keys."""
    merged = JsonUnionStrategy().merge(
        _item({"n": {"z": 1, "a": 2}, "shared": 1}),
        _item({"n": {"m": 3, "a": 99, "b": 4}, "extra": 2}),
    )
    assert merged.content is not None
    text = merged.content.decode("utf-8")
    # top-level: existing order (n, shared) then incoming-only (extra) appended.
    assert text.index('"n"') < text.index('"shared"') < text.index('"extra"')
    # nested: existing order (z, a) then incoming-only (m, b) appended in
    # incoming's order.
    assert text.index('"z"') < text.index('"a"') < text.index('"m"') < text.index('"b"')


# --- synthesis contract (provenance / source_path / shared key fields) ----


def test_merged_item_takes_provenance_and_source_from_incoming() -> None:
    """The synthesised item attributes the merge to the incoming source."""
    existing = _item(
        {"a": 1}, source="/src/a/settings.json", provenance=Provenance(kind="tool", name="claude")
    )
    incoming = _item(
        {"b": 2}, source="/src/b/settings.json", provenance=Provenance(kind="plugin", name="beads")
    )

    merged = JsonUnionStrategy().merge(existing, incoming)

    assert merged.provenance == Provenance(kind="plugin", name="beads")
    assert merged.source_path == Path("/src/b/settings.json")


def test_merged_item_preserves_shared_key_fields() -> None:
    """dest_relpath, kind and namespace survive onto the merged item."""
    merged = JsonUnionStrategy().merge(_item({"a": 1}), _item({"b": 2}))

    assert merged.dest_relpath == Path("settings.json")
    assert merged.kind == FileKind.SETTINGS_JSON
    assert merged.namespace is None


# --- unparseable / missing content (irreconcilable) -----------------------


def test_none_content_raises_collision_error() -> None:
    """SETTINGS_JSON content is meant to be eager bytes; a None side cannot
    be parsed as JSON, so the merge is irreconcilable and raises
    CollisionError naming both source paths."""
    existing = _item(None, source="/src/a/settings.json")
    incoming = _item({"b": 2}, source="/src/b/settings.json")

    with pytest.raises(CollisionError) as excinfo:
        JsonUnionStrategy().merge(existing, incoming)

    assert excinfo.value.existing == Path("/src/a/settings.json")
    assert excinfo.value.incoming == Path("/src/b/settings.json")


# --- merge_settings_bytes key-order contract (existing-wins semantics unchanged) --


def test_merge_settings_bytes_round_trips_existing_key_order() -> None:
    """The user's existing settings.json key order round-trips unchanged
    through merge_settings_bytes when incoming adds no new top-level keys."""
    existing = json.dumps({"zeta": 1, "alpha": 2, "mid": 3}).encode("utf-8")
    incoming = json.dumps({"alpha": 99, "mid": 4}).encode("utf-8")

    merged = merge_settings_bytes(existing=existing, incoming=incoming)

    assert list(json.loads(merged).keys()) == ["zeta", "alpha", "mid"]
    # existing-wins conflict semantics are unchanged by the ordering fix.
    assert json.loads(merged) == {"zeta": 1, "alpha": 2, "mid": 3}


def test_merge_settings_bytes_appends_incoming_only_keys_in_incoming_order() -> None:
    """Keys present only in incoming are appended after the existing side's
    keys, in incoming's own order — not sorted, not prepended."""
    existing = json.dumps({"b": 1, "a": 2}).encode("utf-8")
    incoming = json.dumps({"z": 3, "a": 99, "y": 4}).encode("utf-8")

    merged = merge_settings_bytes(existing=existing, incoming=incoming)

    assert list(json.loads(merged).keys()) == ["b", "a", "z", "y"]


def test_merge_settings_bytes_preserves_order_in_nested_dicts() -> None:
    """Order preservation recurses into nested dicts the same way as the
    top level: existing order first, incoming-only keys appended after."""
    existing = json.dumps({"outer": {"z": 1, "a": 2}}).encode("utf-8")
    incoming = json.dumps({"outer": {"a": 99, "m": 3}}).encode("utf-8")

    merged = merge_settings_bytes(existing=existing, incoming=incoming)

    assert list(json.loads(merged)["outer"].keys()) == ["z", "a", "m"]


def test_malformed_json_raises_collision_error() -> None:
    """Bytes that are not valid JSON make the merge irreconcilable; the
    strategy raises CollisionError rather than crashing with a JSONDecodeError."""
    existing = _item(None, raw=b"{not valid json", source="/src/a/settings.json")
    incoming = _item({"b": 2}, source="/src/b/settings.json")

    with pytest.raises(CollisionError):
        JsonUnionStrategy().merge(existing, incoming)


def test_incoming_side_unparseable_raises_same_collision_error() -> None:
    """The merge parses BOTH sides; a malformed INCOMING (existing good) is
    equally irreconcilable and raises the SAME CollisionError — with the paths
    still in canonical (existing, incoming) order, NOT swapped because the bad
    side happens to be incoming."""
    existing = _item({"a": 1}, source="/src/a/settings.json")
    incoming = _item(None, raw=b"}{ broken", source="/src/b/settings.json")

    with pytest.raises(CollisionError) as excinfo:
        JsonUnionStrategy().merge(existing, incoming)

    assert excinfo.value.existing == Path("/src/a/settings.json")
    assert excinfo.value.incoming == Path("/src/b/settings.json")
