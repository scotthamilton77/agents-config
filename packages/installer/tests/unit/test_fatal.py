"""Unit tests for installer.core.merge.strategies.fatal.

``FatalStrategy`` resolves the irreconcilable collisions — ``NAMESPACED_MD``
in the ``commands`` / ``skills`` / ``agents`` namespaces, and ``DIR`` — by
*always* raising :class:`CollisionError`. It never returns a ``StagedItem``.

Each test pins a coded decision:

- ``merge`` raises ``CollisionError`` rather than returning (the whole point
  of the strategy).
- The raised error names BOTH colliding source paths (the operator must be
  able to locate each side of the conflict).
- The error carries both paths as structured attributes (callers assert on
  data, not prose) — and they come from the two *inputs*, in the right slots.
- ``FatalStrategy`` structurally satisfies the ``MergeStrategy`` protocol
  (the contract is method-shape, not inheritance).

Tests that would only verify Python/stdlib semantics are deliberately absent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.merge.base import CollisionError, MergeStrategy
from installer.core.merge.strategies.fatal import FatalStrategy
from installer.core.model import FileKind, Provenance, StagedItem


def _item(
    source: str,
    *,
    dest: str = "commands/foo.md",
    kind: FileKind = FileKind.NAMESPACED_MD,
    namespace: str | None = "commands",
) -> StagedItem:
    return StagedItem(
        source_path=Path(source),
        dest_relpath=Path(dest),
        kind=kind,
        namespace=namespace,
        provenance=Provenance(kind="tool", name="claude"),
        content=b"x",
    )


def test_merge_raises_collision_error() -> None:
    """The fatal strategy NEVER returns a StagedItem — merge always raises
    CollisionError for the irreconcilable kinds it owns."""
    strategy = FatalStrategy()
    existing = _item("/src/a/foo.md")
    incoming = _item("/src/b/foo.md")

    with pytest.raises(CollisionError):
        strategy.merge(existing, incoming)


def test_merge_error_names_both_source_paths() -> None:
    """The raised error's message names BOTH colliding source paths so an
    operator can locate each side of the conflict (HLD lines 70, 180)."""
    strategy = FatalStrategy()
    existing = _item("/src/a/foo.md")
    incoming = _item("/src/b/foo.md")

    with pytest.raises(CollisionError) as exc_info:
        strategy.merge(existing, incoming)

    text = str(exc_info.value)
    assert "/src/a/foo.md" in text
    assert "/src/b/foo.md" in text


def test_merge_error_carries_input_source_paths_in_order() -> None:
    """The error's structured attributes come from the two inputs, with
    ``existing`` from the existing item and ``incoming`` from the incoming
    item — not swapped, not the dest paths."""
    strategy = FatalStrategy()
    existing = _item("/src/a/foo.md")
    incoming = _item("/src/b/foo.md")

    with pytest.raises(CollisionError) as exc_info:
        strategy.merge(existing, incoming)

    assert exc_info.value.existing == Path("/src/a/foo.md")
    assert exc_info.value.incoming == Path("/src/b/foo.md")


def test_merge_raises_for_dir_kind() -> None:
    """DIR collisions are fatal too — the strategy is namespace-agnostic and
    raises for the DIR kind exactly as it does for namespaced markdown."""
    strategy = FatalStrategy()
    existing = _item("/src/a/skills/x", dest="skills/x", kind=FileKind.DIR, namespace=None)
    incoming = _item("/src/b/skills/x", dest="skills/x", kind=FileKind.DIR, namespace=None)

    with pytest.raises(CollisionError) as exc_info:
        strategy.merge(existing, incoming)

    assert exc_info.value.existing == Path("/src/a/skills/x")
    assert exc_info.value.incoming == Path("/src/b/skills/x")


def test_fatal_strategy_satisfies_merge_strategy_protocol() -> None:
    """FatalStrategy structurally satisfies the MergeStrategy protocol — the
    contract is method-shape, not inheritance."""
    strategy: MergeStrategy = FatalStrategy()
    assert isinstance(strategy, MergeStrategy)
