from __future__ import annotations

from workcli.model import Item

DELIVERED_MARKER = "[work] delivered:"  # leaf note prefix; full: "[work] delivered: <evidence>"
SPEC_MARKER = "[work] spec:"  # placeholder note prefix; full: "[work] spec: <path>"
ORPHAN_MARKER = "[work] orphan-by-choice"  # item note (exact)

_CONTAINER_SHAPE_LABELS = frozenset({"shape-spec", "shape-epic"})
_CONTAINER_TYPES = frozenset({"epic", "milestone"})  # legacy/unstamped fallback


def has_marker(notes: str, prefix: str) -> bool:
    return any(line.strip().startswith(prefix) for line in notes.splitlines())


def is_container(item: Item) -> bool:
    """Declared-state container test -- never child-count (spec §5/invariant 5)."""
    if _CONTAINER_SHAPE_LABELS & set(item.labels):
        return True
    return item.type in _CONTAINER_TYPES
