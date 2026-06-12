"""Pure markdown patch engine (core/md_patch.py).

Behavioural tests for ``apply_patch``: each test pins a section-resolution or
verb-placement decision from the phzj.4 spec (R3-R5), asserted byte-exact on
the returned text — never on parser internals.
"""

from __future__ import annotations

from installer.core.md_patch import Precision, apply_patch


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
