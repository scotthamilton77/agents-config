"""Diff a prior receipt against the desired staged plan to find orphans.

Replaces core/prune.py::scan_orphans (wired in a later task). Scope and path
validation are layered on later; this tracer covers the core differential. An
orphan is a recorded entry whose owner is in scope and whose (owner, path) is
not desired.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.model import Orphan
from installer.core.receipt import Receipt


def diff_orphans(
    prior: Receipt,
    *,
    desired_keys: set[tuple[str, Path]],
    scope_owners: set[str],
    home: Path,
) -> list[Orphan]:
    orphans: list[Orphan] = []
    for e in prior.entries:
        if e.owner not in scope_owners:
            continue
        if (e.owner, e.path) in desired_keys:
            continue
        orphans.append(
            Orphan(
                tool=e.owner,
                namespace=e.path.parts[1] if len(e.path.parts) >= 2 else "",
                path=home / e.path,
                kind=e.kind,
            )
        )
    return orphans
