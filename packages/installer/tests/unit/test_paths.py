"""Unit tests for installer.core.paths — the shared path-safety helper.

Behavioural tests for ``is_safe_relpath`` — the single relpath-traversal guard
consolidated from sync.py, templates.py, and extensions.py. Each test pins one
safe/unsafe decision; none assert on internals.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.paths import is_safe_relpath


@pytest.mark.parametrize(
    "rel",
    [
        Path("file.md"),
        Path("docs/plans/file.md"),
    ],
)
def test_plain_relative_path_is_safe(rel: Path) -> None:
    """A relative path with no parent-dir component joins safely under a base."""
    assert is_safe_relpath(rel) is True


@pytest.mark.parametrize(
    "abs",
    [
        Path("/etc/passwd"),
        Path("/"),
    ],
)
def test_absolute_path_is_unsafe(abs: Path) -> None:
    """An absolute path discards the base on join, so it can never be safe."""
    assert is_safe_relpath(abs) is False


@pytest.mark.parametrize(
    "rel",
    [
        Path("../escape.md"),  # leading
        Path("a/../b.md"),  # mid-path — position must not matter
        Path("a/.."),  # trailing
    ],
)
def test_parent_dir_component_is_unsafe(rel: Path) -> None:
    """Any ``..`` component lets the join climb out of the base — unsafe."""
    assert is_safe_relpath(rel) is False


def test_dotdot_substring_in_filename_is_safe() -> None:
    """``..`` inside a single filename is not a parent-dir component: the guard
    checks ``path.parts``, not the string, so ``foo..bar.md`` stays safe.

    Pins the membership check against a naive ``".." in str(path)`` rewrite,
    which would wrongly reject this path.
    """
    assert is_safe_relpath(Path("foo..bar.md")) is True
