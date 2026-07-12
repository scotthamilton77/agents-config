from __future__ import annotations

from workcli.model import Item

DELIVERED_MARKER = "[work] delivered:"  # leaf note prefix; full: "[work] delivered: <evidence>"
SPEC_MARKER = "[work] spec:"  # placeholder note prefix; full: "[work] spec: <path>"
ORPHAN_MARKER = "[work] orphan-by-choice"  # item note (exact)

_CONTAINER_SHAPE_LABELS = frozenset({"shape-spec", "shape-epic"})
_CONTAINER_TYPES = frozenset({"epic", "milestone"})  # legacy/unstamped fallback


def has_marker(notes: str, prefix: str) -> bool:
    return any(line.strip().startswith(prefix) for line in notes.splitlines())


def spec_path(notes: str) -> str | None:
    """The path recorded after the first `[work] spec:` marker, or None.

    Shared by `deliver` (to validate a re-run's `--spec` against the recorded
    path) and `reconcile` (to re-parse the manifest of an interrupted
    expansion) so both read the marker through one parser.
    """
    for line in notes.splitlines():
        stripped = line.strip()
        if stripped.startswith(SPEC_MARKER):
            return stripped[len(SPEC_MARKER) :].strip()
    return None


def is_container(item: Item) -> bool:
    """Declared-state container test -- never child-count (spec §5/invariant 5)."""
    if _CONTAINER_SHAPE_LABELS & set(item.labels):
        return True
    return item.type in _CONTAINER_TYPES
