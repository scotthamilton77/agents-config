"""Shared path-safety helpers.

A single home for the relpath-traversal invariant that several stages rely on
before joining a caller-supplied path under a trusted base directory.
"""

from __future__ import annotations

from pathlib import Path


def is_safe_relpath(path: Path) -> bool:
    """True when ``path`` is safe to join under a trusted base directory.

    Safe means relative *and* free of any ``..`` component, so ``base / path``
    cannot climb out of ``base`` *lexically*. Absolute paths (which discard
    ``base`` entirely) and paths with a parent-directory component are unsafe.
    This is a lexical check on path *components* (``path.parts``); it does not
    resolve symlinks, so it does not guarantee containment of the *resolved*
    path. A filename that merely contains ``..`` as a substring (e.g.
    ``foo..bar.md``) is safe.

    Callers keep their own contextual error when this returns ``False`` — the
    predicate centralises the invariant, not the failure mode.
    """
    return not path.is_absolute() and ".." not in path.parts
