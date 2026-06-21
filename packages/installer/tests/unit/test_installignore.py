"""Unit tests for installer.core.installignore — the shared exclusion manifest
loader. Each test pins a coded decision: basename vs directory parsing, comment
and blank-line skipping, and the fail-fast contract on a missing/unreadable file
(load-bearing policy, unlike the inert-default installer.toml loader)."""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.installignore import InstallIgnore, load_installignore


def test_basename_and_directory_entries_are_partitioned(tmp_path: Path) -> None:
    manifest = tmp_path / ".installignore"
    manifest.write_text("AGENTS.md\nrules-readmes/\nREADME.md\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.basenames == frozenset({"AGENTS.md", "README.md"})
    assert ignore.dirnames == frozenset({"rules-readmes"})


def test_comments_and_blank_lines_are_ignored(tmp_path: Path) -> None:
    manifest = tmp_path / ".installignore"
    manifest.write_text("# a comment\n\nAGENTS.md\n   \n# trailing\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.basenames == frozenset({"AGENTS.md"})
    assert ignore.dirnames == frozenset()


def test_surrounding_whitespace_is_trimmed(tmp_path: Path) -> None:
    manifest = tmp_path / ".installignore"
    manifest.write_text("  AGENTS.md  \n\trules-readmes/\t\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.basenames == frozenset({"AGENTS.md"})
    assert ignore.dirnames == frozenset({"rules-readmes"})


def test_excludes_matches_files_against_basenames() -> None:
    ignore = InstallIgnore(
        basenames=frozenset({"AGENTS.md"}), dirnames=frozenset({"rules-readmes"})
    )

    assert ignore.excludes("AGENTS.md", is_dir=False) is True
    assert ignore.excludes("AGENTS.md.template", is_dir=False) is False  # never the real file
    assert ignore.excludes("rules-readmes", is_dir=False) is False  # dir entry, file query


def test_excludes_matches_directories_against_dirnames() -> None:
    ignore = InstallIgnore(
        basenames=frozenset({"AGENTS.md"}), dirnames=frozenset({"rules-readmes"})
    )

    assert ignore.excludes("rules-readmes", is_dir=True) is True
    assert ignore.excludes("AGENTS.md", is_dir=True) is False  # basename entry, dir query


def test_missing_manifest_is_fail_fast(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"\.installignore not found"):
        load_installignore(tmp_path / ".installignore")


def test_bare_slash_line_is_skipped(tmp_path: Path) -> None:
    """A degenerate ``/`` line (empty directory name after the trailing-slash
    strip) is dropped, not stored as an empty-string dirname — matching the bash
    matcher, which would otherwise hit a fatal ``bad array subscript``."""
    manifest = tmp_path / ".installignore"
    manifest.write_text("/\nAGENTS.md\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.dirnames == frozenset()
    assert ignore.basenames == frozenset({"AGENTS.md"})
    assert ignore.excludes("", is_dir=True) is False


def test_same_name_as_file_and_directory_partitions_by_kind(tmp_path: Path) -> None:
    """A manifest carrying both ``foo`` and ``foo/`` records the name under BOTH
    kinds, and ``excludes`` resolves each query against the matching kind only."""
    manifest = tmp_path / ".installignore"
    manifest.write_text("foo\nfoo/\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.basenames == frozenset({"foo"})
    assert ignore.dirnames == frozenset({"foo"})
    assert ignore.excludes("foo", is_dir=False) is True
    assert ignore.excludes("foo", is_dir=True) is True


def test_empty_manifest_excludes_nothing(tmp_path: Path) -> None:
    """An all-comment/blank manifest is valid (not a fail-fast) and excludes
    nothing — present-but-empty is allowed; only absence/unreadability aborts."""
    manifest = tmp_path / ".installignore"
    manifest.write_text("# only a comment\n\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.basenames == frozenset()
    assert ignore.dirnames == frozenset()
    assert ignore.excludes("AGENTS.md", is_dir=False) is False
