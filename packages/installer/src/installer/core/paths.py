"""Shared path-safety helpers.

A single home for the relpath-traversal invariant that several stages rely on
before joining a caller-supplied path under a trusted base directory.
"""

from __future__ import annotations

from pathlib import Path


def is_safe_relpath(path: Path) -> bool:
    """True when ``path`` is safe to join under a trusted base directory.

    Safe means relative *and* free of any ``..`` component: ``base / path``
    then cannot resolve outside ``base``. Absolute paths (which discard
    ``base`` entirely) and paths containing a parent-directory component are
    unsafe. The check is on path *components* (``path.parts``), so a filename
    that merely contains ``..`` as a substring (e.g. ``foo..bar.md``) is safe.

    Callers keep their own contextual error when this returns ``False`` — the
    predicate centralises the invariant, not the failure mode.
    """
    return not path.is_absolute() and ".." not in path.parts
