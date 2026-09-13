"""The user-owned tail of a deployed instruction file, merged as text.

Every tool's instruction file ends with a fixed heading: the installer owns
everything above it and rewrites it on each install, the user owns everything
below it and the installer never touches it. These tests pin the merge itself —
pure bytes in, pure bytes out — plus the one repo-content fact the merge depends
on, that each of the four tools really does stage a file ending in the bare
heading.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from installer.core.custom_content import (
    HEADING,
    CustomContentConflictError,
    has_custom_content_heading,
    heading_conflicts,
    merge_custom_content,
)
from installer.core.installignore import InstallIgnore
from installer.core.io_port import ScriptedIO
from installer.core.staging import build_plan
from installer.core.templates import flatten_plan_templates
from installer.tools.base import ToolAdapter
from installer.tools.claude import ClaudeAdapter
from installer.tools.codex import CodexAdapter
from installer.tools.gemini import GeminiAdapter
from installer.tools.opencode import OpenCodeAdapter

_REPO_ROOT = Path(__file__).resolve().parents[4]

# The staged instruction file each tool deploys, keyed by its dest in the plan.
_INSTRUCTION_FILE: dict[type[ToolAdapter], Path] = {
    ClaudeAdapter: Path("AGENTS.md"),
    CodexAdapter: Path("AGENTS.md"),
    GeminiAdapter: Path("GEMINI.md"),
    OpenCodeAdapter: Path("AGENTS.md"),
}

# The managed part is every byte above the heading line, blank separator
# included — the template's own shape, and what the digest covers.
_MANAGED = "# Instructions\n\nrule one\nrule two\n\n"
_INCOMING = f"{_MANAGED}{HEADING}\n".encode()


def _digest_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _stamped(managed: str) -> str:
    """The heading line as written for ``managed`` — recomputed here from the
    contract (sha-256 of everything above the heading) rather than imported, so a
    change to how the installer stamps it fails these tests."""
    return (
        f"{HEADING} <!-- the installer rewrites everything above this line "
        f"and nothing below it; digest {_digest_of(managed)} -->\n"
    )


# ───────────────────────── selector ─────────────────────────


def test_only_content_carrying_the_heading_is_selected() -> None:
    """
    Given staged content with and without the heading
    When the selector is asked
    Then only the content carrying the heading opts into the merge — the heading's
    presence is the whole selector, with no per-file registry behind it.
    """
    assert has_custom_content_heading(_INCOMING)
    assert not has_custom_content_heading(b"# Instructions\n\nrule one\n")


def test_non_utf8_staged_content_is_not_selected() -> None:
    """
    Given staged bytes that are not valid UTF-8
    When the selector is asked
    Then they do not opt in — undecodable bytes cannot carry the heading, and the
    selector must not raise on them.
    """
    assert not has_custom_content_heading(b"\xff\xfe binary")


# ───────────────────────── rule 1: no existing file ─────────────────────────


def test_fresh_install_writes_the_managed_part_and_a_stamped_heading() -> None:
    """
    Given no existing destination
    When the staged content is merged
    Then the managed part is written with the bare heading replaced by the
    stamped one, and nothing is reported as migrated.
    """
    result = merge_custom_content(_INCOMING, None)

    assert result.content == (_MANAGED + _stamped(_MANAGED)).encode("utf-8")
    assert not result.migrated


def test_fresh_install_keeps_the_templates_seed_tail() -> None:
    """
    Given no existing destination and staged content carrying text below its heading
    When it is merged
    Then that text is written under the heading as the seed tail — the only case
    where the template's own tail reaches disk.
    """
    incoming = f"{_MANAGED}{HEADING}\n\nseed line\n".encode()

    result = merge_custom_content(incoming, None)

    assert result.content.decode("utf-8").endswith(f"{_stamped(_MANAGED)}\nseed line\n")


# ───────────────────────── rule 2: existing file, no heading ─────────────────


def test_existing_file_without_a_heading_keeps_its_unmanaged_lines_below_it() -> None:
    """
    Given an existing file with no heading, holding managed lines plus the user's own
    When it is merged
    Then the user's lines are carried under the new heading, and the migration is
    reported so the caller can tell the user to review it.
    """
    existing = "# Instructions\n\nrule one\n\nmy own note\nand another\n"

    result = merge_custom_content(_INCOMING, existing.encode("utf-8"))

    assert result.migrated
    assert result.content.decode("utf-8") == (
        _MANAGED + _stamped(_MANAGED) + "\nmy own note\nand another\n"
    )


def test_migration_drops_every_line_the_managed_part_already_carries() -> None:
    """
    Given an existing file whose every non-blank line also appears in the managed part
    When it is merged
    Then nothing is carried down: the file gains only the heading, and no migration
    is reported. A line the installer wrote is the installer's, wherever it sits.
    """
    existing = "rule two\n\nrule one\n# Instructions\n"

    result = merge_custom_content(_INCOMING, existing.encode("utf-8"))

    assert result.content == (_MANAGED + _stamped(_MANAGED)).encode("utf-8")
    assert not result.migrated


def test_migration_keeps_paragraph_breaks_and_drops_the_padding() -> None:
    """
    Given a file whose own text is several paragraphs, padded with blank lines
    When it is merged
    Then the blank line between two paragraphs survives, while the padding around
    the block and a doubled break do not. The carried text has to still read as
    the user wrote it, without inheriting the gaps left by the lines removed
    around it.
    """
    existing = "# Instructions\n\n\nfirst para\n\n\nsecond para\n\n\n"

    result = merge_custom_content(_INCOMING, existing.encode("utf-8"))

    assert result.content.decode("utf-8").endswith(
        f"{_stamped(_MANAGED)}\nfirst para\n\nsecond para\n"
    )


def test_migration_of_a_byte_identical_file_adds_only_the_heading() -> None:
    """
    Given an existing file byte-identical to the staged managed part
    When it is merged
    Then the heading is the only change.
    """
    result = merge_custom_content(_INCOMING, _MANAGED.encode("utf-8"))

    assert result.content == (_MANAGED + _stamped(_MANAGED)).encode("utf-8")
    assert not result.migrated


# ───────────────────────── rules 3 and 4: existing heading ──────────────────


def test_an_intact_file_keeps_its_tail_byte_for_byte() -> None:
    """
    Given an existing file whose heading digest still matches the bytes above it
    When a changed managed part is merged
    Then the tail below the heading is reproduced byte-for-byte and the heading is
    re-stamped for the new managed part. A tail edit trips nothing.
    """
    old_managed = "# Instructions\n\nrule one\n\n"
    tail = "\n## my notes\n\n\ttabbed\ttext  \nlast\n"
    existing = (old_managed + _stamped(old_managed) + tail).encode("utf-8")

    result = merge_custom_content(_INCOMING, existing)

    assert result.content == (_MANAGED + _stamped(_MANAGED) + tail).encode("utf-8")
    assert not result.migrated


def test_a_second_heading_inside_the_tail_does_not_move_the_boundary() -> None:
    """
    Given a user tail that itself contains a second heading line
    When the file is merged
    Then the first heading is still the boundary and the second survives inside the
    preserved tail — a user writing the heading again does not shrink their own
    content.
    """
    old_managed = "# Instructions\n\nrule one\n\n"
    tail = f"\nmine\n{HEADING}\nalso mine\n"
    existing = (old_managed + _stamped(old_managed) + tail).encode("utf-8")

    result = merge_custom_content(_INCOMING, existing)

    assert result.content == (_MANAGED + _stamped(_MANAGED) + tail).encode("utf-8")


def test_a_hand_placed_heading_without_a_digest_is_accepted() -> None:
    """
    Given a file whose heading the user typed themselves, carrying no digest
    When it is merged
    Then the tail is preserved and the heading is stamped — a heading that pins
    nothing cannot disagree with anything, so there is nothing to refuse.
    """
    existing = f"whatever they had\n{HEADING}\n\nmine\n".encode()

    result = merge_custom_content(_INCOMING, existing)

    assert result.content == (_MANAGED + _stamped(_MANAGED) + "\nmine\n").encode("utf-8")
    assert not heading_conflicts(existing)


def test_the_written_digest_covers_exactly_the_bytes_above_the_heading() -> None:
    """
    Given a merged result
    When the digest in its heading is checked against the bytes preceding that line
    Then they agree — which is what makes the next install's tamper check meaningful.
    """
    written = merge_custom_content(_INCOMING, None).content.decode("utf-8")
    above, heading = written.split(HEADING, 1)

    assert f"digest {hashlib.sha256(above.encode('utf-8')).hexdigest()[:12]} " in heading
    assert not heading_conflicts(written.encode("utf-8"))


# ───────────────────────── rule 5: the managed part was edited ──────────────


def test_an_edited_managed_part_is_a_conflict() -> None:
    """
    Given a file whose text above the heading changed after the installer stamped it
    When the conflict check runs
    Then it reports the conflict, and merging anyway refuses rather than
    overwriting the edit.
    """
    managed = "# Instructions\n\nrule one\n\n"
    existing = (managed + "hand-typed line\n" + _stamped(managed) + "\nmine\n").encode("utf-8")

    assert heading_conflicts(existing)
    with pytest.raises(CustomContentConflictError):
        merge_custom_content(_INCOMING, existing)


def test_a_file_that_is_not_utf8_is_a_conflict() -> None:
    """
    Given a destination whose bytes do not decode as UTF-8
    When the conflict check runs
    Then it is a conflict: the installer cannot read the file well enough to know
    what belongs to whom, so it must not write over it.
    """
    assert heading_conflicts(b"\xff\xfe not text")


def test_the_conflict_error_names_every_offending_path() -> None:
    """
    Given several destinations that tripped the check
    When the error is raised for them
    Then its message names each absolute path, so one run reports every file the
    user has to fix.
    """
    paths = [Path("/home/u/.claude/AGENTS.md"), Path("/home/u/.codex/AGENTS.md")]

    error = CustomContentConflictError(paths)

    assert error.paths == tuple(paths)
    assert all(str(path) in str(error) for path in paths)


def test_merging_content_without_a_heading_is_a_programmer_error() -> None:
    """
    Given staged content the selector would have rejected
    When it is merged anyway
    Then the call fails loudly rather than inventing a boundary — the selector is
    the caller's precondition, not a fallback this function papers over.
    """
    with pytest.raises(ValueError, match=HEADING):
        merge_custom_content(b"no heading here\n", None)


# ───────────────────────── the repo's own templates ─────────────────────────


@pytest.mark.parametrize("adapter_cls", list(_INSTRUCTION_FILE))
def test_each_tools_staged_instruction_file_ends_with_the_bare_heading(
    adapter_cls: type[ToolAdapter], ignore: InstallIgnore
) -> None:
    """The real plan for each tool, flattened as at deploy, ends with the bare
    heading — the installer stamps it, so the template must not."""
    plan = build_plan(adapter_cls(), repo_root=_REPO_ROOT, ignore=ignore)
    flatten_plan_templates(plan, repo_root=_REPO_ROOT, io=ScriptedIO())

    content = plan.items[_INSTRUCTION_FILE[adapter_cls]].content
    assert content is not None
    assert content.decode("utf-8").endswith(f"\n{HEADING}\n")


@pytest.mark.parametrize("adapter_cls", list(_INSTRUCTION_FILE))
def test_no_staged_content_refers_to_a_sibling_local_file(
    adapter_cls: type[ToolAdapter], ignore: InstallIgnore
) -> None:
    """No item any tool stages mentions ``AGENTS.local.md``: the custom-content
    section replaced that route, and a deployed file pointing at both would tell
    the user two different places to put the same thing."""
    plan = build_plan(adapter_cls(), repo_root=_REPO_ROOT, ignore=ignore)
    flatten_plan_templates(plan, repo_root=_REPO_ROOT, io=ScriptedIO())

    for dest, item in plan.items.items():
        if item.content is None:
            continue
        assert "AGENTS.local" not in item.content.decode("utf-8", errors="replace"), dest
