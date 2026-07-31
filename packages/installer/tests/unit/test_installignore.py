"""Unit tests for installer.core.installignore — the shared exclusion manifest
loader. Each test pins a coded decision: file vs directory patterns, anchored
vs any-depth scope, glob vs exact matching, comment/blank-line skipping, the
'/' parse-error posture, and the fail-fast contract on a missing/unreadable
file (load-bearing policy, unlike the inert-default installer.toml loader)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from installer.core.installignore import InstallIgnore, load_installignore


def test_anchored_file_and_directory_patterns_are_parsed(tmp_path: Path) -> None:
    manifest = tmp_path / ".installignore"
    manifest.write_text("/AGENTS.md\n/rules-readmes/\n/README.md\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.excludes("AGENTS.md", is_dir=False, at_root=True) is True
    assert ignore.excludes("README.md", is_dir=False, at_root=True) is True
    assert ignore.excludes("rules-readmes", is_dir=True, at_root=True) is True
    assert (
        ignore.excludes("rules-readmes", is_dir=False, at_root=True) is False
    )  # dir pattern, file query


def test_comments_and_blank_lines_are_ignored(tmp_path: Path) -> None:
    manifest = tmp_path / ".installignore"
    manifest.write_text("# a comment\n\n/AGENTS.md\n   \n# trailing\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.excludes("AGENTS.md", is_dir=False, at_root=True) is True
    assert len(ignore.patterns) == 1


def test_surrounding_whitespace_is_trimmed(tmp_path: Path) -> None:
    manifest = tmp_path / ".installignore"
    manifest.write_text("  /AGENTS.md  \n\t/rules-readmes/\t\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.excludes("AGENTS.md", is_dir=False, at_root=True) is True
    assert ignore.excludes("rules-readmes", is_dir=True, at_root=True) is True


def test_anchored_pattern_matches_only_at_root(tmp_path: Path) -> None:
    """A leading '/' anchors a pattern to the direct children of a staged
    namespace subdirectory — the whole scope an anchored pattern reaches. The
    same name one level deeper (``at_root=False``, e.g. inside a DIR item's
    interior) is NOT excluded by an anchored entry."""
    manifest = tmp_path / ".installignore"
    manifest.write_text("/README.md\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.excludes("README.md", is_dir=False, at_root=True) is True
    assert ignore.excludes("README.md", is_dir=False, at_root=False) is False


def test_unanchored_pattern_matches_at_any_depth_including_root(tmp_path: Path) -> None:
    """No leading '/' means the pattern matches regardless of depth — including
    at the root, since "any depth" includes depth zero."""
    manifest = tmp_path / ".installignore"
    manifest.write_text("emit_prompts_test.py\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.excludes("emit_prompts_test.py", is_dir=False, at_root=True) is True
    assert ignore.excludes("emit_prompts_test.py", is_dir=False, at_root=False) is True


def test_glob_pattern_matches_via_fnmatch(tmp_path: Path) -> None:
    manifest = tmp_path / ".installignore"
    manifest.write_text("*_test.py\ntest_*.py\n*_test.js\n*.pyc\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.excludes("emit_prompts_test.py", is_dir=False, at_root=False) is True
    assert ignore.excludes("test_checker.py", is_dir=False, at_root=False) is True
    assert ignore.excludes("proxy_test.js", is_dir=False, at_root=False) is True
    assert ignore.excludes("emit_prompts.cpython-312.pyc", is_dir=False, at_root=False) is True
    # test_ prefix is scoped to .py — a JSON fixture with the same prefix survives.
    assert ignore.excludes("test_data.json", is_dir=False, at_root=False) is False


def test_glob_is_case_sensitive(tmp_path: Path) -> None:
    manifest = tmp_path / ".installignore"
    manifest.write_text("*.pyc\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.excludes("cache.PYC", is_dir=False, at_root=False) is False


def test_plain_pattern_without_glob_characters_matches_exactly(tmp_path: Path) -> None:
    """A name carrying none of '*?[' is an exact match, not a glob — a
    substring or prefix match must not fire."""
    manifest = tmp_path / ".installignore"
    manifest.write_text("AGENTS.md\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.excludes("AGENTS.md", is_dir=False, at_root=False) is True
    assert ignore.excludes("AGENTS.md.template", is_dir=False, at_root=False) is False
    assert ignore.excludes("XAGENTS.md", is_dir=False, at_root=False) is False


def test_directory_pattern_glob(tmp_path: Path) -> None:
    manifest = tmp_path / ".installignore"
    manifest.write_text("__pycache__/\n.*_cache/\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.excludes("__pycache__", is_dir=True, at_root=False) is True
    assert ignore.excludes(".pytest_cache", is_dir=True, at_root=False) is True
    assert ignore.excludes(".ruff_cache", is_dir=True, at_root=False) is True
    assert (
        ignore.excludes("__pycache__", is_dir=False, at_root=False) is False
    )  # dir pattern, file query


def test_missing_manifest_is_fail_fast(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"\.installignore not found"):
        load_installignore(tmp_path / ".installignore")


def test_present_but_unreadable_manifest_is_not_swallowed(tmp_path: Path) -> None:
    """A present-but-unreadable manifest is NOT silently treated as
    exclude-nothing: load_installignore lets the PermissionError (an OSError
    subclass) from read_text propagate, preserving the module's fail-fast
    contract. This is the regression guard against someone wrapping the read in a
    try/except that would re-enable the dead-docs leak the manifest prevents.
    Skipped when chmod cannot make the file unreadable (running as root, or a
    filesystem that ignores mode bits)."""
    manifest = tmp_path / ".installignore"
    manifest.write_text("/AGENTS.md\n", encoding="utf-8")
    manifest.chmod(0o000)
    try:
        if os.access(manifest, os.R_OK):
            pytest.skip("manifest still readable after chmod (root or mode-less fs)")
        with pytest.raises(PermissionError):
            load_installignore(manifest)
    finally:
        manifest.chmod(0o644)


def test_bare_slash_line_is_skipped(tmp_path: Path) -> None:
    """A degenerate '/' line (empty name after stripping the leading AND
    trailing slash) is dropped, not stored as an empty-string pattern that
    would need its own no-op-matching special case."""
    manifest = tmp_path / ".installignore"
    manifest.write_text("/\n/AGENTS.md\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert len(ignore.patterns) == 1
    assert ignore.excludes("AGENTS.md", is_dir=False, at_root=True) is True
    assert ignore.excludes("", is_dir=True, at_root=True) is False


def test_double_slash_degenerate_line_is_skipped(tmp_path: Path) -> None:
    """A '//' line strips to an empty name after BOTH the leading-anchor and
    trailing-directory strip; still degenerate, still skipped."""
    manifest = tmp_path / ".installignore"
    manifest.write_text("//\n/AGENTS.md\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert len(ignore.patterns) == 1


def test_slash_in_the_middle_is_a_parse_error(tmp_path: Path) -> None:
    """A '/' anywhere other than the leading or trailing position is a parse
    error — fail-fast, consistent with the loader's other error posture,
    rather than silently matching a single path component."""
    manifest = tmp_path / ".installignore"
    manifest.write_text("skills/foo\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"'/' only allowed as leading/trailing"):
        load_installignore(manifest)


def test_anchored_slash_in_the_middle_is_also_a_parse_error(tmp_path: Path) -> None:
    manifest = tmp_path / ".installignore"
    manifest.write_text("/skills/foo/\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"'/' only allowed as leading/trailing"):
        load_installignore(manifest)


def test_same_name_as_file_and_directory_pattern_partitions_by_kind(tmp_path: Path) -> None:
    """A manifest carrying both 'foo' and 'foo/' records the name under BOTH
    kinds, and ``excludes`` resolves each query against the matching kind only."""
    manifest = tmp_path / ".installignore"
    manifest.write_text("foo\nfoo/\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.excludes("foo", is_dir=False, at_root=False) is True
    assert ignore.excludes("foo", is_dir=True, at_root=False) is True


def test_empty_manifest_excludes_nothing(tmp_path: Path) -> None:
    """An all-comment/blank manifest is valid (not a fail-fast) and excludes
    nothing — present-but-empty is allowed; only absence/unreadability aborts."""
    manifest = tmp_path / ".installignore"
    manifest.write_text("# only a comment\n\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.patterns == ()
    assert ignore.excludes("AGENTS.md", is_dir=False, at_root=True) is False


def test_default_construction_excludes_nothing() -> None:
    """``InstallIgnore()`` with no patterns is the empty-manifest default every
    sync-path caller that hasn't loaded a real manifest falls back to."""
    ignore = InstallIgnore()

    assert ignore.excludes("anything", is_dir=False, at_root=True) is False
    assert ignore.excludes("anything", is_dir=True, at_root=False) is False
