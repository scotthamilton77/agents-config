from __future__ import annotations

from workcli.lifecycle.manifest import Manifest, deserialize_manifest
from workcli.lifecycle.nouns import IMPL_CONTAINER_LABEL
from workcli.model import Item

DELIVERED_MARKER = "[work] delivered:"  # leaf note prefix; full: "[work] delivered: <evidence>"
SPEC_MARKER = "[work] spec:"  # placeholder note prefix; full: "[work] spec: <path>"
MANIFEST_MARKER = (
    "[work] manifest:"  # placeholder note; full: "[work] manifest: <serialized-manifest>"
)
ORPHAN_MARKER = "[work] orphan-by-choice"  # item note (exact)

_CONTAINER_SHAPE_LABELS = frozenset({"shape-spec", "shape-epic", IMPL_CONTAINER_LABEL})
_CONTAINER_TYPES = frozenset({"epic", "milestone"})  # legacy/unstamped fallback


def has_marker(notes: str, prefix: str) -> bool:
    return any(line.strip().startswith(prefix) for line in notes.splitlines())


def _first_marker_payload(notes: str, prefix: str) -> str | None:
    """The stripped payload after the first line matching `prefix`, or None."""
    for line in notes.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return None


def spec_path(notes: str) -> str | None:
    """The path recorded after the first `[work] spec:` marker, or None.

    Used by `deliver`'s drift guard to validate a re-run's `--spec` against the
    path recorded at first delivery. `reconcile` no longer reads it -- it replays
    toward the in-band `[work] manifest:` snapshot instead of re-reading the spec.
    """
    return _first_marker_payload(notes, SPEC_MARKER)


def manifest_snapshot(notes: str) -> Manifest | None:
    """The parsed manifest recorded after the first `[work] manifest:` marker, or None.

    Recovery replays toward this frozen snapshot and never re-reads the spec
    file, so a post-delivery edit cannot silently drop or alter a committed unit.
    """
    payload = _first_marker_payload(notes, MANIFEST_MARKER)
    if payload is None:
        return None
    return deserialize_manifest(payload)


def is_container(item: Item) -> bool:
    """Declared-state container test -- never child-count (spec §5/invariant 5)."""
    if _CONTAINER_SHAPE_LABELS & set(item.labels):
        return True
    return item.type in _CONTAINER_TYPES
