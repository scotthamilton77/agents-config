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
