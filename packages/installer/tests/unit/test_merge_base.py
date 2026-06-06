"""Unit tests for installer.core.merge.base.

Each test pins a coded decision in the merge contract:

- ``CollisionError`` names BOTH colliding source paths in its message so the
  fatal strategy can surface an actionable error.
- A trivial dummy strategy structurally satisfies the ``MergeStrategy``
  protocol (the contract is method-shape, not inheritance).

Tests that would only verify Python/stdlib semantics (e.g. that a frozen
dataclass rejects attribute writes) are deliberately absent.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.merge.base import CollisionError, MergeStrategy
from installer.core.model import FileKind, Provenance, StagedItem


def _item(source: str, dest: str = "rules/foo.md") -> StagedItem:
    return StagedItem(
        source_path=Path(source),
        dest_relpath=Path(dest),
        kind=FileKind.NAMESPACED_MD,
        namespace="rules",
        provenance=Provenance(kind="tool", name="claude"),
        content=b"x",
    )


def test_collision_error_message_names_both_source_paths() -> None:
    """The constructor takes the two colliding source paths and the message
    must name BOTH so an operator can locate each side of the conflict."""
    existing = Path("/src/a/foo.md")
    incoming = Path("/src/b/foo.md")

    err = CollisionError(existing, incoming)

    text = str(err)
    assert str(existing) in text
    assert str(incoming) in text


def test_collision_error_exposes_both_paths_as_attributes() -> None:
    """Structured attributes (not just the message string) so callers and
    tests assert on data rather than parsing prose."""
    existing = Path("/src/a/foo.md")
    incoming = Path("/src/b/foo.md")

    err = CollisionError(existing, incoming)

    assert err.existing == existing
    assert err.incoming == incoming


def test_collision_error_is_runtime_error() -> None:
    """CollisionError is a RuntimeError subclass — the shared fatal-collision
    signal, distinct from the registry's lookup-miss error."""
    assert issubclass(CollisionError, RuntimeError)


def test_dummy_strategy_satisfies_merge_strategy_protocol() -> None:
    """A class with a structurally-correct ``merge`` method is a
    ``MergeStrategy`` — the contract is method-shape, not inheritance."""

    class DummyStrategy:
        def merge(
            self,
            existing: StagedItem,  # noqa: ARG002  # inert stub
            incoming: StagedItem,
        ) -> StagedItem:
            return incoming

    strategy: MergeStrategy = DummyStrategy()
    existing = _item("/src/a/foo.md")
    incoming = _item("/src/b/foo.md")

    assert strategy.merge(existing, incoming) is incoming
