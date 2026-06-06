"""Unit tests for installer.core.merge.strategies.append_rules (E.2).

Each test pins a coded decision in the append-merge contract for
``(NAMESPACED_MD, namespace="rules")`` collisions:

- The two rule bodies join with the EXACT separator ``b"\\n---\\n"``.
- Order is ``existing`` THEN ``incoming`` (deterministic, append-only).
- The synthesised item carries merged bytes but takes ``provenance`` and
  ``source_path`` from ``incoming`` while preserving the shared key fields.
- Empty-content edges never emit a doubled/stray separator or a trailing
  blank-line artefact.

Tests that would only verify Python/stdlib semantics (bytes concatenation,
frozen-dataclass immutability) are deliberately absent.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.merge.base import MergeStrategy
from installer.core.merge.strategies.append_rules import AppendRulesStrategy
from installer.core.model import FileKind, Provenance, StagedItem

_SEP = b"\n---\n"


def _item(
    source: str,
    content: bytes | None,
    *,
    dest: str = "rules/foo.md",
    provenance: Provenance | None = None,
) -> StagedItem:
    return StagedItem(
        source_path=Path(source),
        dest_relpath=Path(dest),
        kind=FileKind.NAMESPACED_MD,
        namespace="rules",
        provenance=provenance or Provenance(kind="tool", name="claude"),
        content=content,
    )


def test_strategy_satisfies_merge_strategy_protocol() -> None:
    """AppendRulesStrategy structurally honours the MergeStrategy contract."""
    strategy: MergeStrategy = AppendRulesStrategy()
    assert isinstance(strategy, MergeStrategy)


def test_non_empty_bodies_join_existing_then_incoming_with_separator() -> None:
    """Both bodies present: result is existing + separator + incoming, in that
    order, with the separator EXACTLY b"\\n---\\n"."""
    existing = _item("/src/a/foo.md", b"alpha")
    incoming = _item("/src/b/foo.md", b"beta")

    merged = AppendRulesStrategy().merge(existing, incoming)

    assert merged.content == b"alpha" + _SEP + b"beta"


def test_separator_is_emitted_exactly_once_between_two_bodies() -> None:
    """A single separator joins two non-empty bodies — no doubling."""
    existing = _item("/src/a/foo.md", b"one")
    incoming = _item("/src/b/foo.md", b"two")

    merged = AppendRulesStrategy().merge(existing, incoming)

    assert merged.content is not None
    assert merged.content.count(_SEP) == 1


def test_empty_existing_yields_incoming_without_leading_separator() -> None:
    """When existing has no body, the result is just incoming — no stray
    leading separator or blank-line artefact."""
    existing = _item("/src/a/foo.md", b"")
    incoming = _item("/src/b/foo.md", b"beta")

    merged = AppendRulesStrategy().merge(existing, incoming)

    assert merged.content == b"beta"


def test_empty_incoming_yields_existing_without_trailing_separator() -> None:
    """When incoming has no body, the result is just existing — no stray
    trailing separator."""
    existing = _item("/src/a/foo.md", b"alpha")
    incoming = _item("/src/b/foo.md", b"")

    merged = AppendRulesStrategy().merge(existing, incoming)

    assert merged.content == b"alpha"


def test_both_empty_yields_empty_content() -> None:
    """Two empty bodies collapse to empty content — no separator at all."""
    existing = _item("/src/a/foo.md", b"")
    incoming = _item("/src/b/foo.md", b"")

    merged = AppendRulesStrategy().merge(existing, incoming)

    assert merged.content == b""


def test_none_content_is_treated_as_empty_edge() -> None:
    """A None body (defensive: NAMESPACED_MD is normally bytes) is handled as
    the empty-content edge, not concatenated as a literal — existing=None
    collapses to incoming alone."""
    existing = _item("/src/a/foo.md", None)
    incoming = _item("/src/b/foo.md", b"beta")

    merged = AppendRulesStrategy().merge(existing, incoming)

    assert merged.content == b"beta"


def test_merged_item_takes_provenance_and_source_from_incoming() -> None:
    """The synthesised item attributes the merge to the incoming source:
    provenance and source_path come from incoming."""
    existing = _item("/src/a/foo.md", b"alpha", provenance=Provenance(kind="tool", name="claude"))
    incoming = _item("/src/b/foo.md", b"beta", provenance=Provenance(kind="plugin", name="beads"))

    merged = AppendRulesStrategy().merge(existing, incoming)

    assert merged.provenance == Provenance(kind="plugin", name="beads")
    assert merged.source_path == Path("/src/b/foo.md")


def test_merged_item_preserves_shared_key_fields() -> None:
    """dest_relpath, kind and namespace are identical on both by definition of
    the collision and survive onto the merged item unchanged."""
    existing = _item("/src/a/foo.md", b"alpha")
    incoming = _item("/src/b/foo.md", b"beta")

    merged = AppendRulesStrategy().merge(existing, incoming)

    assert merged.dest_relpath == Path("rules/foo.md")
    assert merged.kind == FileKind.NAMESPACED_MD
    assert merged.namespace == "rules"
