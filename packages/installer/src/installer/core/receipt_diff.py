"""Diff a prior receipt against the desired staged plan to find orphans.

Finds orphans by diffing the prior receipt against the desired staged plan. An
orphan is a recorded entry whose owner is in scope and whose (owner, path) is
not desired; scope and path validation gate which recorded entries are eligible.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.model import Orphan, Tool
from installer.core.receipt import Receipt, ReceiptEntry

_ALL_TOOL_NAMES: frozenset[str] = frozenset(t.value for t in Tool)


def validate_entry(
    entry: ReceiptEntry,
    *,
    home: Path,
    live_roots_by_owner: dict[str, set[Path]],
    allowlist: set[Path],
) -> bool:
    """Whether a recorded entry is safe to act on (prune).

    Rejects (returns False) a structurally unsafe path/root (absolute or with a
    ``..`` component), a path that escapes its root once symlinks are resolved
    (symlink-aware containment, unlike the lexical ``is_safe_relpath``), or an
    illegitimate root for the owner: a tool/discovered-plugin owner must match one
    of its live roots; a retired owner (absent from ``live_roots_by_owner``) must
    match the persisted ``allowlist``."""
    if entry.path.is_absolute() or ".." in entry.path.parts:
        return False
    if entry.root.is_absolute() or ".." in entry.root.parts:
        return False
    try:
        resolved_path = (home / entry.path).resolve()
        resolved_root = (home / entry.root).resolve()
        resolved_path.relative_to(resolved_root)
    except (ValueError, OSError):
        # OSError covers symlink loops (ELOOP) and FS/permission errors during
        # ``.resolve()``: an unresolvable entry fails closed (skipped), never
        # crashes the prune.
        return False
    legit = live_roots_by_owner.get(entry.owner)
    if legit is not None:
        return entry.root in legit
    return entry.root in allowlist


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
    live_roots_by_owner: dict[str, set[Path]],
    allowlist: set[Path],
) -> list[Orphan]:
    orphans: list[Orphan] = []
    for e in prior.entries:
        if e.owner not in scope_owners:
            continue
        if (e.owner, e.path) in desired_keys:
            continue
        # Trust-boundary validation is mandatory on this deletion path: an
        # in-scope, non-desired entry is only emitted as an orphan once it passes
        # validate_entry. Both inputs are required (no optional defaults) so the
        # validation can never be silently skipped.
        if not validate_entry(
            e, home=home, live_roots_by_owner=live_roots_by_owner, allowlist=allowlist
        ):
            continue
        # Namespace is the first path segment AFTER the recorded root, so roots
        # with multiple segments (e.g. OpenCode's ``.config/opencode``) group
        # orphans under the real namespace (``skills/``), not the root tail.
        # By construction ``path`` is lexically under ``root``; the ValueError
        # fallback keeps the prune from crashing on a pathological entry.
        try:
            rel_parts = e.path.relative_to(e.root).parts
        except ValueError:
            rel_parts = ()
        orphans.append(
            Orphan(
                tool=e.owner,
                namespace=rel_parts[0] if rel_parts else "",
                path=home / e.path,
                kind=e.kind,
            )
        )
    return orphans
