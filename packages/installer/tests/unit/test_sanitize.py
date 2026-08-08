"""Deploy-time rewriting of front matter, both removals.

Pins the tool-independent sanitization (governance front-matter keys,
provenance comment) and the per-tool capability projection, and — just as
importantly — what must survive each: every other front-matter key, byte for
byte, and any comment that is content rather than bookkeeping.
"""

from __future__ import annotations

import pytest

from installer.core.sanitize import (
    governance_findings,
    project_capabilities,
    sanitize_bytes,
    sanitize_text,
)

_RECORD = "admission:\n  prevents: p\n  cost: c\n  remove_when: r\n"
_FLAGGED = "---\nname: handoff\ndisable-model-invocation: true\n---\nbody\n"


def test_admission_block_is_removed() -> None:
    text = f"---\nname: grilling\n{_RECORD}---\nbody\n"
    assert sanitize_text(text) == "---\nname: grilling\n---\nbody\n"


def test_claims_block_is_removed() -> None:
    text = f"---\nname: a\n{_RECORD}claims:\n  pr-review: verdict\n---\nbody\n"
    assert sanitize_text(text) == "---\nname: a\n---\nbody\n"


def test_surviving_keys_are_byte_identical() -> None:
    # A long quoted description with colons and trailing spaces is exactly the
    # kind of value a YAML round-trip would reflow. It must not be touched.
    description = 'description: "Use when: X, Y; or Z — see the notes"'
    text = f"---\nname: a\n{description}\n{_RECORD}---\nbody\n"
    assert sanitize_text(text) == f"---\nname: a\n{description}\n---\nbody\n"


def test_key_order_is_preserved_when_record_sits_first() -> None:
    text = f"---\n{_RECORD}name: a\ndescription: d\n---\nbody\n"
    assert sanitize_text(text) == "---\nname: a\ndescription: d\n---\nbody\n"


def test_blank_lines_inside_the_record_do_not_leak() -> None:
    text = "---\nname: a\nadmission:\n  prevents: p\n\n  cost: c\n  remove_when: r\n---\nbody\n"
    assert sanitize_text(text) == "---\nname: a\n---\nbody\n"


def test_fence_is_dropped_when_only_governance_keys_existed() -> None:
    text = f"---\n{_RECORD}---\n\nbody\n"
    assert sanitize_text(text) == "body\n"


def test_provenance_comment_is_removed() -> None:
    text = (
        f"---\nname: a\n{_RECORD}---\n\n"
        "<!--\nSource: oss-snapshots/pocock/skills/grilling/\n"
        "Upstream: https://example.invalid/skills\n"
        "Drift policy: local-fork\n-->\n\nbody\n"
    )
    assert sanitize_text(text) == "---\nname: a\n---\n\nbody\n"


def test_single_line_provenance_comment_is_removed() -> None:
    text = "<!-- Source: oss-snapshots/x/ -->\n\nbody\n"
    assert sanitize_text(text) == "body\n"


def test_content_comment_without_a_marker_survives() -> None:
    text = "<!-- TODO: rewrite this section -->\n\nbody\n"
    assert sanitize_text(text) == text


def test_comment_after_prose_survives() -> None:
    # Only a *leading* comment is bookkeeping; one below prose is content.
    text = "body\n\n<!--\nSource: somewhere\n-->\n"
    assert sanitize_text(text) == text


def test_unterminated_comment_is_left_alone() -> None:
    text = "<!--\nSource: somewhere\n\nbody\n"
    assert sanitize_text(text) == text


def test_text_without_front_matter_is_untouched_apart_from_provenance() -> None:
    assert sanitize_text("# heading\n\nbody\n") == "# heading\n\nbody\n"


def test_unparseable_front_matter_is_not_treated_as_front_matter() -> None:
    # split_frontmatter refuses it, so there is no record to strip and the
    # text passes through — the same safe default the admission bar takes.
    text = "---\n: : :\n---\nbody\n"
    assert sanitize_text(text) == text


def test_malformed_record_still_loses_the_key() -> None:
    # A non-indented line ends the drop, so only the key itself is lost.
    text = "---\nadmission: \nname: a\n---\nbody\n"
    assert sanitize_text(text) == "---\nname: a\n---\nbody\n"


def test_key_named_like_a_governance_key_but_nested_survives() -> None:
    text = "---\nmeta:\n  admission: internal\nname: a\n---\nbody\n"
    assert sanitize_text(text) == text


def test_sanitize_bytes_round_trips_utf8() -> None:
    text = f"---\nname: a\ndescription: em—dash\n{_RECORD}---\nbody\n"
    assert (
        sanitize_bytes(text.encode())
        == b"---\nname: a\ndescription: em\xe2\x80\x94dash\n---\nbody\n"
    )


def test_sanitizing_twice_is_a_no_op() -> None:
    text = f"---\nname: a\n{_RECORD}---\n\n<!--\nSource: x\n-->\n\nbody\n"
    once = sanitize_text(text)
    assert sanitize_text(once) == once


def test_crlf_artifact_keeps_crlf_endings() -> None:
    text = "---\r\nname: a\r\n" + _RECORD.replace("\n", "\r\n") + "---\r\nbody\r\n"
    assert sanitize_text(text) == "---\r\nname: a\r\n---\r\nbody\r\n"


def test_crlf_artifact_with_only_governance_keys_drops_the_fence() -> None:
    text = "---\r\n" + _RECORD.replace("\n", "\r\n") + "---\r\n\r\nbody\r\n"
    assert sanitize_text(text) == "body\r\n"


def test_claude_keeps_the_capability_key() -> None:
    assert project_capabilities(_FLAGGED, tool="claude") == _FLAGGED


@pytest.mark.parametrize("tool", ["codex", "gemini", "opencode"])
def test_a_tool_without_the_capability_loses_the_key(tool: str) -> None:
    assert project_capabilities(_FLAGGED, tool=tool) == "---\nname: handoff\n---\nbody\n"


@pytest.mark.parametrize("tool", ["codex", "gemini", "opencode"])
def test_every_claude_only_capability_key_is_projected_out(tool: str) -> None:
    text = (
        "---\nname: handoff\nargument-hint: [focus]\n"
        "disable-model-invocation: true\nallowed-tools: Write Bash(git status *)\n"
        "description: d\n---\nbody\n"
    )
    projected = project_capabilities(text, tool=tool)
    assert projected == "---\nname: handoff\ndescription: d\n---\nbody\n"


def test_surviving_keys_are_byte_identical_through_the_projection() -> None:
    description = 'description: "Use when: X, Y; or Z — see the notes"'
    text = f"---\nname: a\n{description}\ndisable-model-invocation: true\n---\nbody\n"
    assert project_capabilities(text, tool="gemini") == f"---\nname: a\n{description}\n---\nbody\n"


def test_the_projection_does_not_touch_the_body() -> None:
    """A capability is a property of the loading runtime; the body is not. A
    leading comment that survives sanitization must survive this too."""
    text = "---\ndisable-model-invocation: true\nname: a\n---\n<!-- TODO: rewrite -->\nbody\n"
    assert (
        project_capabilities(text, tool="codex")
        == "---\nname: a\n---\n<!-- TODO: rewrite -->\nbody\n"
    )


def test_front_matter_of_nothing_but_capability_keys_drops_the_fence() -> None:
    assert (
        project_capabilities("---\nallowed-tools: Write\n---\n\nbody\n", tool="codex") == "body\n"
    )


def test_text_without_front_matter_passes_through_the_projection() -> None:
    assert project_capabilities("# heading\n\nbody\n", tool="codex") == "# heading\n\nbody\n"


def test_unparseable_front_matter_is_not_projected() -> None:
    text = "---\n: : :\n---\ndisable-model-invocation: true\n"
    assert project_capabilities(text, tool="codex") == text


def test_projecting_twice_is_a_no_op() -> None:
    once = project_capabilities(_FLAGGED, tool="opencode")
    assert project_capabilities(once, tool="opencode") == once


def test_projection_keeps_crlf_endings() -> None:
    text = "---\r\nname: a\r\ndisable-model-invocation: true\r\n---\r\nbody\r\n"
    assert project_capabilities(text, tool="gemini") == "---\r\nname: a\r\n---\r\nbody\r\n"


# --- Naming the metadata instead of removing it ------------------------------
#
# The same two recognisers, asked rather than acted on — for the files the deploy
# gate reads but has no mandate to rewrite.


def test_findings_name_every_governance_key_present() -> None:
    text = f"---\nname: a\n{_RECORD}claims:\n  k: v\n---\nbody\n"
    assert governance_findings(text) == ("admission", "claims")


def test_findings_name_a_provenance_comment_with_no_front_matter() -> None:
    assert governance_findings("<!--\nSource: oss-snapshots/x/\n-->\n\nbody\n") == (
        "provenance comment",
    )


def test_a_file_with_ordinary_front_matter_yields_no_findings() -> None:
    assert governance_findings("---\nname: a\n---\n\n<!-- an ordinary note -->\nbody\n") == ()


def test_findings_ignore_a_fence_quirk_that_reassembly_would_normalise() -> None:
    """Not implemented as a byte-compare against `sanitize_text`. A fence carrying
    trailing whitespace round-trips to a different byte string, and reporting that
    under a message about governance metadata would name the wrong defect."""
    text = "---  \nname: a\n---\nbody\n"
    assert sanitize_text(text) != text
    assert governance_findings(text) == ()


def test_what_findings_name_is_what_sanitizing_removes() -> None:
    text = f"---\nname: a\n{_RECORD}---\n\n<!--\nSource: x/\n-->\n\nbody\n"
    assert governance_findings(text) == ("admission", "provenance comment")
    assert governance_findings(sanitize_text(text)) == ()
