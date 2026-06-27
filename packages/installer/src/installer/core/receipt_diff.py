"""Diff a prior receipt against the desired staged plan to find orphans.

Replaces core/prune.py::scan_orphans (wired in a later task). Scope and path
validation are layered on later; this tracer covers the core differential. An
orphan is a recorded entry whose owner is in scope and whose (owner, path) is
not desired.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.model import Orphan, Tool
from installer.core.receipt import Receipt

_ALL_TOOL_NAMES: frozenset[str] = frozenset(t.value for t in Tool)


def scope_owners(
    resolved_tools: set[str], discovered_plugins: set[str], prior: Receipt
) -> set[str]:
    """Owners whose recorded entries are eligible for pruning this run.

    Resolved tools and discovered plugins are in scope. Any prior-entry owner
    that is NOT a tool name is a plugin owner (possibly retired) and is also in
    scope, so a plugin we stopped shipping still gets pruned. Untargeted tools
    (a tool name not in ``resolved_tools``) are deliberately excluded — another
    run's scope must never prune a tool the user did not target.
    """
    retired_plugin_owners = {e.owner for e in prior.entries if e.owner not in _ALL_TOOL_NAMES}
    return resolved_tools | discovered_plugins | retired_plugin_owners


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
