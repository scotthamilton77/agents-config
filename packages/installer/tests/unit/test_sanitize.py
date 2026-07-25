"""Deploy-time sanitization of governance metadata.

Pins the two removals (governance front-matter keys, provenance comment) and,
just as importantly, what must survive them: every other front-matter key,
byte for byte, and any comment that is content rather than bookkeeping.
"""

from __future__ import annotations

from installer.core.sanitize import sanitize_bytes, sanitize_text

_RECORD = "admission:\n  prevents: p\n  cost: c\n  remove_when: r\n"


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
