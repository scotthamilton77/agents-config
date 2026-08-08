"""Unit tests for installer.core.merge.strategies.append_rules.

Each test pins a coded decision in the append-merge contract for
``(NAMESPACED_MD, namespace="rules")`` collisions:

- The two rule bodies join with the EXACT separator ``b"\\n---\\n"``.
- Order is ``existing`` THEN ``incoming`` (deterministic, append-only).
- The synthesised item carries merged bytes but takes ``provenance`` and
  ``source_path`` from ``incoming`` while preserving the shared key fields.
- Each side is recorded as a ``Contribution``, so the destination stays
  decomposable: the admission bar judges one authored file at a time.
- Empty-content edges never emit a doubled/stray separator or a trailing
  blank-line artefact.

Tests that would only verify Python/stdlib semantics (bytes concatenation,
frozen-dataclass immutability) are deliberately absent.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.merge.strategies.append_rules import AppendRulesStrategy
from installer.core.model import Contribution, FileKind, Provenance, StagedItem

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


def test_each_side_is_recorded_as_a_contribution_in_content_order() -> None:
    """The merged bytes are one blob, and every later reader of a rule's front
    matter is asking about one authored file. Recording each side is what lets the
    admission bar judge them separately instead of judging whichever leads."""
    existing = _item("/src/a/foo.md", b"alpha")
    incoming = _item("/src/b/foo.md", b"beta")

    merged = AppendRulesStrategy().merge(existing, incoming)

    assert merged.contributions == (
        Contribution(source_path=Path("/src/a/foo.md"), content=b"alpha"),
        Contribution(source_path=Path("/src/b/foo.md"), content=b"beta"),
    )


def test_a_chained_merge_flattens_into_one_contribution_per_file() -> None:
    """Three rules colliding merge pairwise. The result names three authored
    files in content order, not a nested pair — a reader of the list wants the
    files, not the shape of the merge tree that produced them."""
    strategy = AppendRulesStrategy()

    first_two = strategy.merge(_item("/src/first.md", b"first"), _item("/src/second.md", b"second"))
    all_three = strategy.merge(first_two, _item("/src/third.md", b"third"))

    assert [part.source_path for part in all_three.contributions] == [
        Path("/src/first.md"),
        Path("/src/second.md"),
        Path("/src/third.md"),
    ]


def test_a_side_that_contributed_no_bytes_contributes_no_identity() -> None:
    """An empty rule adds nothing to the merged content, so listing it as a
    contributor would put a file with no bytes on the admission bar's report and
    fail the destination over a record nothing needed."""
    merged = AppendRulesStrategy().merge(
        _item("/src/a/empty.md", b""), _item("/src/b/foo.md", b"beta")
    )

    assert merged.contributions == (
        Contribution(source_path=Path("/src/b/foo.md"), content=b"beta"),
    )
