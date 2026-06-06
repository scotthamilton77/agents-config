"""Unit tests for installer.core.merge.strategies.json_union.

Each test pins a coded decision in the deep-union-merge contract for
``(SETTINGS_JSON, *)`` collisions. The behavioural spec is the jq program
at ``scripts/install.sh:431-456``; these tests were authored by probing the
real ``jq-1.8.1`` against the same inputs, so they pin jq-parity, not the
Python stdlib.

The jq rules being pinned:

- dict + dict at a shared key -> recurse (deep merge);
- array + array at a shared key -> concatenate, jq-``unique`` (sort by jq's
  total order, then dedupe by value);
- scalar conflict at a shared key -> KEEP EXISTING;
- type mismatch at a shared key (dict-vs-scalar, array-vs-scalar, etc.)
  -> KEEP EXISTING;
- key only in incoming -> ADD it; key only in existing -> keep it;
- top-level non-object operand -> the result is ``existing`` whole;
- the empty-object quirk: merging two objects whose key-merge yields no
  keys produces JSON ``null`` (jq ``[] | add == null``);
- output bytes are canonical ``jq .`` formatting: 2-space indent, single
  trailing newline, and key order that matches ``jq .`` (which does NOT
  sort) — the deep-merge skeleton it CONSTRUCTS is sorted, but objects it
  PASSES THROUGH verbatim keep insertion order;
- the synthesised item takes provenance + source_path from incoming and
  preserves the shared key fields.

jq total order pinned in the array-union tests:
``null < false < true < number < string < array < object``.

Tests that would only verify Python/stdlib semantics (``json.loads`` round
trips, frozen-dataclass immutability) are deliberately absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from installer.core.merge.base import CollisionError, MergeStrategy
from installer.core.merge.strategies.json_union import JsonUnionStrategy
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


# --- protocol conformance -------------------------------------------------


def test_strategy_satisfies_merge_strategy_protocol() -> None:
    """JsonUnionStrategy structurally honours the MergeStrategy contract."""
    strategy: MergeStrategy = JsonUnionStrategy()
    assert isinstance(strategy, MergeStrategy)


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


# --- array union rule (concatenate + jq unique) ---------------------------


def test_scalar_arrays_union_sort_and_dedupe() -> None:
    """Conflicting scalar arrays concatenate, then jq-``unique`` sorts
    ascending and removes duplicates."""
    assert _merge({"arr": [3, 1, 2]}, {"arr": [2, 4, 1]}) == {"arr": [1, 2, 3, 4]}


def test_array_union_dedupes_within_a_single_side() -> None:
    """jq-``unique`` collapses duplicates that already exist within one side
    as well as across sides."""
    assert _merge({"x": [1, 1, 2, 2]}, {"x": [2, 3, 3]}) == {"x": [1, 2, 3]}


def test_array_union_dedupes_int_and_float_with_same_value() -> None:
    """jq treats 1 and 1.0 as the same number, so they dedupe to one."""
    assert _merge({"x": [1]}, {"x": [1.0, 2]}) == {"x": [1, 2]}


def test_array_union_handles_int_too_large_for_float() -> None:
    """A 400-digit integer is valid JSON but overflows ``float()``; the jq
    sort key falls back to +inf for ordering, so the union neither crashes nor
    loses the value — the exact integer survives in the merged output."""
    huge = 10**400
    assert _merge({"x": [huge]}, {"x": [1]}) == {"x": [1, huge]}


def test_array_union_jq_total_order_across_types() -> None:
    """jq's total order ranks types null < false < true < number < string
    < array < object; ``unique`` sorts the unioned array by that order."""
    result = _merge(
        {"x": [3, "b", True, None]},
        {"x": ["a", False, 2]},
    )
    assert result == {"x": [None, False, True, 2, 3, "a", "b"]}


def test_array_union_of_objects_sorts_by_keys_then_values() -> None:
    """Arrays of objects union + dedupe; jq orders objects by sorted-key
    array first, then by values in key order."""
    result = _merge(
        {"perms": [{"k": "v2"}, {"k": "v1"}]},
        {"perms": [{"k": "v1"}, {"k": "v3"}]},
    )
    assert result == {"perms": [{"k": "v1"}, {"k": "v2"}, {"k": "v3"}]}


def test_array_union_object_keyset_tiebreak() -> None:
    """jq object order compares the sorted key-set first: {"a":2} precedes
    {"a":1,"b":2} (key-set ["a"] < ["a","b"]) which precedes {"b":1}."""
    result = _merge(
        {"x": [{"a": 1, "b": 2}, {"a": 2}]},
        {"x": [{"b": 1}, {"a": 1}]},
    )
    assert result == {"x": [{"a": 1}, {"a": 2}, {"a": 1, "b": 2}, {"b": 1}]}


def test_array_union_of_nested_arrays_lexicographic_order() -> None:
    """Nested arrays sort element-wise with a length tiebreak (prefix is
    less), matching jq's recursive array comparison."""
    result = _merge({"x": [[1, 2], [1]]}, {"x": [[1, 2], [1, 2, 0]]})
    assert result == {"x": [[1], [1, 2], [1, 2, 0]]}


# --- empty-container edges ------------------------------------------------


def test_empty_arrays_union_to_empty_array() -> None:
    """Two empty arrays at a key union to an empty array, not null."""
    assert _merge({"x": []}, {"x": []}) == {"x": []}


def test_empty_array_unions_with_populated_array() -> None:
    """An empty array on one side contributes nothing; the other side's
    elements survive, sorted and deduped."""
    assert _merge({"x": []}, {"x": [2, 1]}) == {"x": [1, 2]}


def test_disjoint_empty_containers_are_preserved() -> None:
    """Keys carrying empty {} / [] that appear on only one side pass through
    unchanged (no collision occurs, so no merge rule fires)."""
    result = _merge({"a": {}, "c": 1}, {"b": [], "d": 2})
    assert result == {"a": {}, "b": [], "c": 1, "d": 2}


def test_merging_two_empty_objects_yields_null_quirk() -> None:
    """The jq quirk: deep-merging two objects whose key-merge yields no keys
    runs ``[] | add`` which is null. Two empty top-level objects -> null."""
    merged = JsonUnionStrategy().merge(_item({}), _item({}))
    assert merged.content is not None
    assert json.loads(merged.content) is None


def test_nested_two_empty_objects_yield_null_at_that_key() -> None:
    """The empty-object quirk propagates through recursion: a key holding {}
    on both sides recurses, the inner key-merge is empty, and the value
    becomes null."""
    assert _merge({"x": {}}, {"x": {}}) == {"x": None}


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


# --- output formatting (jq-parity bytes) ----------------------------------


def test_output_is_two_space_indented_with_sorted_keys_and_trailing_newline() -> None:
    """Merged bytes match canonical jq formatting: 2-space indent, exactly one
    trailing newline, and — for keys the deep-merge constructs (as here, where
    every key comes from both operands) — sorted order. The serializer itself
    uses ``sort_keys=False``; sorting comes from skeleton construction, so
    passthrough objects keep insertion order (pinned separately below)."""
    merged = JsonUnionStrategy().merge(_item({"b": 1, "a": 2}), _item({"c": 3}))
    assert merged.content == b'{\n  "a": 2,\n  "b": 1,\n  "c": 3\n}\n'


def test_output_keys_sorted_codepoint_order_digits_upper_lower() -> None:
    """jq key order is Unicode codepoint: digits < uppercase < lowercase."""
    merged = JsonUnionStrategy().merge(_item({"B": 1, "a": 2, "10": 3, "2": 4}), _item({"A": 5}))
    assert merged.content is not None
    text = merged.content.decode("utf-8")
    assert list(json.loads(text).keys()) == ["10", "2", "A", "B", "a"]
    # Bytes must reflect that order, not insertion order.
    assert text.index('"10"') < text.index('"2"') < text.index('"A"')
    assert text.index('"A"') < text.index('"B"') < text.index('"a"')


# --- passthrough key-order rule (jq `.` preserves insertion order) --------
#
# These pin the distinction `jq .` makes between objects the deep-merge
# skeleton CONSTRUCTS (via `keys | unique`, which jq sorts) and objects it
# PASSES THROUGH verbatim (which keep their original insertion order). All
# expectations were probed against the real jq-1.8.1 deep_merge program from
# scripts/install.sh:431-454.


def test_one_side_only_nested_object_keeps_insertion_key_order() -> None:
    """A key present on only ONE side whose value is an object is passed
    through verbatim by jq (branch ``{($k): $a[$k]}`` — no recursion), so its
    nested keys keep INSERTION order, not sorted order. jq emits ``env`` as
    ``Z, A, M``; sorted would be ``A, M, Z``."""
    merged = JsonUnionStrategy().merge(
        _item({"env": {"Z": 1, "A": 2, "M": 3}}),
        _item({"other": 1}),
    )
    assert merged.content is not None
    text = merged.content.decode("utf-8")
    assert text.index('"Z"') < text.index('"A"') < text.index('"M"')


def test_object_inside_array_keeps_insertion_key_order() -> None:
    """An object nested inside an array goes through ``union_arrays`` and is
    never re-serialised key-by-key, so jq keeps its insertion order. jq emits
    ``{z, a}``; sorted would be ``{a, z}``."""
    merged = JsonUnionStrategy().merge(
        _item({"arr": [{"z": 1, "a": 2}]}),
        _item({"other": 1}),
    )
    assert merged.content is not None
    text = merged.content.decode("utf-8")
    assert text.index('"z"') < text.index('"a"')


def test_deep_merge_skeleton_keys_stay_sorted_at_every_level() -> None:
    """The object the deep-merge skeleton CONSTRUCTS (keys merged on both
    sides, via jq ``keys | unique``) is sorted by jq at every recursion level
    — including a nested object present on BOTH sides, which recurses. This
    guards the fix from over-correcting passthrough order onto constructed
    objects."""
    merged = JsonUnionStrategy().merge(
        _item({"n": {"z": 1, "a": 2}, "shared": 1}),
        _item({"n": {"m": 3, "b": 4}, "extra": 2}),
    )
    assert merged.content is not None
    text = merged.content.decode("utf-8")
    # top-level constructed keys sorted: extra, n, shared
    assert text.index('"extra"') < text.index('"n"') < text.index('"shared"')
    # nested object recursed on both sides -> constructed -> keys sorted
    assert text.index('"a"') < text.index('"b"') < text.index('"m"') < text.index('"z"')


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


def test_malformed_json_raises_collision_error() -> None:
    """Bytes that are not valid JSON make the merge irreconcilable; the
    strategy raises CollisionError rather than crashing with a JSONDecodeError."""
    existing = _item(None, raw=b"{not valid json", source="/src/a/settings.json")
    incoming = _item({"b": 2}, source="/src/b/settings.json")

    with pytest.raises(CollisionError):
        JsonUnionStrategy().merge(existing, incoming)
