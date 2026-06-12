"""Pure markdown patch engine (core/md_patch.py).

Behavioural tests for ``apply_patch``: each test pins a section-resolution or
verb-placement decision from the phzj.4 spec (R3-R5), asserted byte-exact on
the returned text — never on parser internals.
"""

from __future__ import annotations

import pytest

from installer.core.md_patch import PatchError, Precision, apply_patch


def test_append_lands_directly_after_last_body_line() -> None:
    """R4 worked example 1: no trailing blanks."""
    out = apply_patch(
        "## Foo\nbody\n## Next\n", section="Foo", precision=Precision.APPEND, content="X"
    )
    assert out == "## Foo\nbody\nX\n## Next\n"


def test_append_preserves_trailing_blank_lines_after_inserted_content() -> None:
    """R4 worked example 2: original trailing blanks stay AFTER the insertion."""
    out = apply_patch(
        "## Foo\nbody\n\n\n## Next\n", section="Foo", precision=Precision.APPEND, content="X"
    )
    assert out == "## Foo\nbody\nX\n\n\n## Next\n"


def test_append_multiline_content() -> None:
    """R4 worked example 3."""
    out = apply_patch(
        "## Foo\nbody\n## Next\n", section="Foo", precision=Precision.APPEND, content="X\nY"
    )
    assert out == "## Foo\nbody\nX\nY\n## Next\n"


def test_append_into_empty_section_lands_directly_under_header() -> None:
    """No non-blank body line exists; insertion point falls back to just
    below the header (spec-silent edge; pinned here as the coded decision)."""
    out = apply_patch("## Foo\n## Next\n", section="Foo", precision=Precision.APPEND, content="X")
    assert out == "## Foo\nX\n## Next\n"


def test_insert_before_places_content_above_the_header() -> None:
    out = apply_patch(
        "intro\n## Foo\nbody\n", section="Foo", precision=Precision.INSERT_BEFORE, content="X"
    )
    assert out == "intro\nX\n## Foo\nbody\n"


def test_insert_after_places_content_below_header_before_existing_body() -> None:
    out = apply_patch(
        "## Foo\nbody\n", section="Foo", precision=Precision.INSERT_AFTER, content="X"
    )
    assert out == "## Foo\nX\nbody\n"


def test_prepend_is_physically_identical_to_insert_after() -> None:
    """R4: intentionally redundant verbs — same physical position."""
    doc = "## Foo\nbody\n## Next\n"
    via_prepend = apply_patch(doc, section="Foo", precision=Precision.PREPEND, content="X\nY")
    via_insert = apply_patch(doc, section="Foo", precision=Precision.INSERT_AFTER, content="X\nY")
    assert via_prepend == via_insert == "## Foo\nX\nY\nbody\n## Next\n"


def test_replace_swaps_body_and_preserves_both_boundary_headers() -> None:
    out = apply_patch(
        "## Foo\nold1\nold2\n## Next\nkeep\n",
        section="Foo",
        precision=Precision.REPLACE,
        content="new",
    )
    assert out == "## Foo\nnew\n## Next\nkeep\n"


def test_replace_keeps_nested_subsection_inside_the_replaced_range() -> None:
    """A depth D+1 header does NOT terminate the section — it is part of the
    body and is consumed by replace (R4 boundary: next header at depth <= D)."""
    out = apply_patch(
        "## Foo\nbody\n### Sub\nsub-body\n## Next\n",
        section="Foo",
        precision=Precision.REPLACE,
        content="new",
    )
    assert out == "## Foo\nnew\n## Next\n"


def test_replace_on_last_section_runs_to_eof_and_terminates_with_newline() -> None:
    """No next-section boundary: body extends to EOF; replacement content is
    newline-terminated if not already (R4)."""
    out = apply_patch("## Foo\nold\n", section="Foo", precision=Precision.REPLACE, content="new")
    assert out == "## Foo\nnew\n"


def test_append_skips_nested_subsection_boundary_and_lands_at_section_end() -> None:
    """Counterpart pin for append: the D+1 subsection is inside the body, so
    append lands after ITS last non-blank line (AC #3 nested-subsection case)."""
    out = apply_patch(
        "## Foo\nbody\n### Sub\nsub-body\n## Next\n",
        section="Foo",
        precision=Precision.APPEND,
        content="X",
    )
    assert out == "## Foo\nbody\n### Sub\nsub-body\nX\n## Next\n"


def test_header_inside_backtick_fence_is_invisible() -> None:
    """A ``## Heading``-shaped line inside a fence neither matches a target
    nor terminates the enclosing section (R3 + AC #3 fence case)."""
    doc = "## Foo\nbody\n```bash\n## Not A Header\n# also not\n```\ntail\n## Next\n"
    out = apply_patch(doc, section="Foo", precision=Precision.APPEND, content="X")
    assert out == "## Foo\nbody\n```bash\n## Not A Header\n# also not\n```\ntail\nX\n## Next\n"
    with pytest.raises(PatchError, match="not found"):
        apply_patch(doc, section="Not A Header", precision=Precision.APPEND, content="X")


def test_tilde_fence_hides_headers_too() -> None:
    doc = "## Foo\n~~~\n## Hidden\n~~~\n## Next\n"
    with pytest.raises(PatchError, match="not found"):
        apply_patch(doc, section="Hidden", precision=Precision.APPEND, content="X")


def test_fence_closes_only_on_same_char_at_gte_opener_length() -> None:
    """A ```` ```` ```` opener is not closed by ``~~~`` nor by a shorter
    backtick run; a longer run closes it (R3 fence rule)."""
    doc = "## Foo\n````\n~~~\n```\n## Hidden\n`````\n## Real\n"
    with pytest.raises(PatchError, match="not found"):
        apply_patch(doc, section="Hidden", precision=Precision.APPEND, content="X")
    out = apply_patch(doc, section="Real", precision=Precision.APPEND, content="X")
    assert out.endswith("## Real\nX\n")


def test_pseudo_headers_are_not_recognized() -> None:
    """``##NoSpace`` (no space) and ``  ## Indented`` (leading whitespace)
    are not headers (R3) — they neither match nor terminate a section."""
    doc = "## Foo\nbody\n##NoSpace\n  ## Indented\n## Next\n"
    out = apply_patch(doc, section="Foo", precision=Precision.APPEND, content="X")
    assert out == "## Foo\nbody\n##NoSpace\n  ## Indented\nX\n## Next\n"
    for non_header in ("#NoSpace", "Indented"):
        with pytest.raises(PatchError, match="not found"):
            apply_patch(doc, section=non_header, precision=Precision.APPEND, content="X")


def test_trailing_hash_decorations_are_part_of_the_match_text() -> None:
    """``## Title ##`` strips LEADING hashes only: matchable text is
    ``Title ##`` (R2 hash-strip rule)."""
    doc = "## Title ##\nbody\n"
    out = apply_patch(doc, section="Title ##", precision=Precision.APPEND, content="X")
    assert out == "## Title ##\nbody\nX\n"
    with pytest.raises(PatchError, match="not found"):
        apply_patch(doc, section="Title", precision=Precision.APPEND, content="X")


def test_trailing_whitespace_on_header_line_is_stripped_before_comparison() -> None:
    out = apply_patch(
        "## Title   \nbody\n", section="Title", precision=Precision.APPEND, content="X"
    )
    assert out == "## Title   \nbody\nX\n"


def test_match_is_case_sensitive() -> None:
    with pytest.raises(PatchError, match="not found"):
        apply_patch("## Title\nbody\n", section="title", precision=Precision.APPEND, content="X")


def test_ambiguous_section_is_terminal_and_counts_matches() -> None:
    with pytest.raises(PatchError, match=r"appears 2 times; ambiguous"):
        apply_patch(
            "## Dup\na\n## Dup\nb\n", section="Dup", precision=Precision.APPEND, content="X"
        )
