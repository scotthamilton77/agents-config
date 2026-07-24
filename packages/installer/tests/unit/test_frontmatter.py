"""Front-matter split shared by the admission bar and surface budget (S3)."""

from __future__ import annotations

from installer.core.frontmatter import split_frontmatter


def test_leading_block_parsed_and_body_returned() -> None:
    mapping, body = split_frontmatter("---\nadmission:\n  prevents: x\n---\nbody line\n")
    assert mapping == {"admission": {"prevents": "x"}}
    assert body == "body line\n"


def test_no_leading_fence_is_all_body() -> None:
    mapping, body = split_frontmatter("# Heading\n\ntext\n")
    assert mapping is None
    assert body == "# Heading\n\ntext\n"


def test_empty_text_has_no_frontmatter() -> None:
    mapping, body = split_frontmatter("")
    assert mapping is None
    assert body == ""


def test_opening_fence_without_close_is_all_body() -> None:
    text = "---\nadmission: x\nno closing fence\n"
    mapping, body = split_frontmatter(text)
    assert mapping is None
    assert body == text


def test_unparseable_yaml_is_treated_as_no_frontmatter() -> None:
    text = "---\n: : : not yaml\n---\nbody\n"
    mapping, body = split_frontmatter(text)
    assert mapping is None
    assert body == text


def test_non_mapping_payload_is_not_frontmatter() -> None:
    # A YAML list payload is valid YAML but not a front-matter mapping.
    text = "---\n- a\n- b\n---\nbody\n"
    mapping, body = split_frontmatter(text)
    assert mapping is None
    assert body == text
