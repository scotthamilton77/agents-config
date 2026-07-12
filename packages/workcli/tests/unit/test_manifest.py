"""`## Continuations` manifest parser (plan Task 2 / spec §6, §15).

`parse_continuations` turns a spec's `## Continuations` section into a typed
`Manifest`. The grammar is wrap-tolerant (a bullet's title/AC may continue
across physical lines) and requires a bare `Noun` token -- both load-bearing
per the deep review that blocked the pre-fix grammar (MAJOR finding: wrapped
and annotated bullets were rejected; placement annotations like "(under `x`)"
are not part of the facade grammar).
"""

from __future__ import annotations

import pytest

from workcli.envelope import ErrorCode, WorkError
from workcli.lifecycle.manifest import Manifest, ManifestItem, parse_continuations


def test_three_item_section_parses_into_three_manifest_items():
    spec = (
        "# Some Spec\n\n"
        "## Continuations\n"
        "- feat: Add the flag — AC: flag toggles behavior\n"
        "- bugfix: Fix the race — AC: no more races\n"
        "- chore: Update docs — AC: docs mention the flag\n"
    )

    manifest = parse_continuations(spec)

    assert manifest.none_reason is None
    assert manifest.items == (
        ManifestItem(noun="feat", title="Add the flag", acceptance="flag toggles behavior"),
        ManifestItem(noun="bugfix", title="Fix the race", acceptance="no more races"),
        ManifestItem(noun="chore", title="Update docs", acceptance="docs mention the flag"),
    )


def test_bullet_wraps_across_physical_lines_into_one_item():
    spec = (
        "## Continuations\n"
        "- feat: Add a flag to enable foo\n"
        "  for the bar use case — AC: flag toggles the bar behavior\n"
    )

    manifest = parse_continuations(spec)

    assert manifest.items == (
        ManifestItem(
            noun="feat",
            title="Add a flag to enable foo for the bar use case",
            acceptance="flag toggles the bar behavior",
        ),
    )


def test_none_bullet_with_reason_yields_empty_items_and_the_reason():
    spec = "## Continuations\n- none — this spec is the deliverable\n"

    manifest = parse_continuations(spec)

    assert manifest == Manifest(items=(), none_reason="this spec is the deliverable")


def test_missing_continuations_section_raises_manifest_error():
    spec = "# Some Spec\n\nNo continuations section here.\n"

    with pytest.raises(WorkError) as exc_info:
        parse_continuations(spec)

    assert exc_info.value.code == ErrorCode.MANIFEST


def test_non_bare_noun_annotation_is_rejected():
    spec = "## Continuations\n- feat (under `x`): Add the flag — AC: flag toggles behavior\n"

    with pytest.raises(WorkError) as exc_info:
        parse_continuations(spec)

    assert exc_info.value.code == ErrorCode.MANIFEST


def test_unknown_noun_is_rejected():
    spec = "## Continuations\n- widget: Add the flag — AC: flag toggles behavior\n"

    with pytest.raises(WorkError) as exc_info:
        parse_continuations(spec)

    assert exc_info.value.code == ErrorCode.MANIFEST


def test_none_mixed_with_real_items_is_rejected():
    spec = "## Continuations\n- none\n- feat: Add the flag — AC: flag toggles behavior\n"

    with pytest.raises(WorkError) as exc_info:
        parse_continuations(spec)

    assert exc_info.value.code == ErrorCode.MANIFEST


def test_empty_section_is_rejected():
    spec = "## Continuations\n## Out of Scope\n- feat: Add the flag — AC: flag toggles behavior\n"

    with pytest.raises(WorkError) as exc_info:
        parse_continuations(spec)

    assert exc_info.value.code == ErrorCode.MANIFEST


def test_item_missing_ac_separator_is_rejected():
    spec = "## Continuations\n- feat: Add the flag with no acceptance criteria\n"

    with pytest.raises(WorkError) as exc_info:
        parse_continuations(spec)

    assert exc_info.value.code == ErrorCode.MANIFEST


def test_second_header_ends_the_section():
    spec = (
        "## Continuations\n"
        "- feat: Add the flag — AC: flag toggles behavior\n"
        "\n"
        "## Out of Scope\n"
        "- bugfix: This should not be included — AC: not included\n"
    )

    manifest = parse_continuations(spec)

    assert manifest.items == (
        ManifestItem(noun="feat", title="Add the flag", acceptance="flag toggles behavior"),
    )


def test_bare_none_bullet_with_no_reason_yields_empty_reason_string():
    spec = "## Continuations\n- none\n"

    manifest = parse_continuations(spec)

    assert manifest == Manifest(items=(), none_reason="")


def test_prose_before_the_first_bullet_is_ignored_not_appended_to_any_item():
    spec = (
        "## Continuations\n"
        "This section lists the follow-on work.\n"
        "- feat: Add the flag — AC: flag toggles behavior\n"
    )

    manifest = parse_continuations(spec)

    assert manifest.items == (
        ManifestItem(noun="feat", title="Add the flag", acceptance="flag toggles behavior"),
    )


def test_item_bullet_with_no_colon_at_all_is_rejected():
    spec = "## Continuations\n- this bullet has no noun separator\n"

    with pytest.raises(WorkError) as exc_info:
        parse_continuations(spec)

    assert exc_info.value.code == ErrorCode.MANIFEST


def test_item_bullet_with_empty_title_is_rejected():
    spec = "## Continuations\n- feat:  — AC: flag toggles behavior\n"

    with pytest.raises(WorkError) as exc_info:
        parse_continuations(spec)

    assert exc_info.value.code == ErrorCode.MANIFEST


def test_item_bullet_with_empty_acceptance_is_rejected():
    spec = "## Continuations\n- feat: Add the flag — AC: \n"

    with pytest.raises(WorkError) as exc_info:
        parse_continuations(spec)

    assert exc_info.value.code == ErrorCode.MANIFEST
