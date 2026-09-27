"""Canonical installer namespace vocabulary — the single source for every
per-concern namespace view.

A *namespace* is a top-level content directory name the installer routes on
(``skills``, ``rules``, …). Lists that name these strings independently at each
call site drift: a namespace lands in one and goes missing from another, and two
lists hold the same set in different orders. This module is the one place the
vocabulary lives; each per-concern view below is a named, rationale-carrying
subset (or ordering) of :data:`ALL` that a call site consumes. Add a namespace
here and to the views it belongs to — never re-declare a list at a call site.

Ordering note: for the iterated tuple views (:data:`TOOL_SCOPED`, :data:`SHARED`,
:data:`PLUGIN_TOOL_SCOPED`) iteration order is *not* collision-load-bearing —
each namespace stages under a disjoint ``dest_relpath`` prefix, so no
cross-namespace collision can occur and the resulting plan is order-invariant.
Order is fixed only for deterministic, reproducible plans.

Where a namespace lands on disk is also decided here, by :data:`RELOCATED` and
the two functions below it. A plan keys every namespaced item as
``<namespace>/<name>`` for every tool, and only the step from a plan key to a
path under the tool's destination root consults the relocation table.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

# The full universe of content-namespace directory names the installer knows.
# Every view below satisfies ``set(view) <= ALL``.
ALL: frozenset[str] = frozenset({"commands", "skills", "agents", "rules", "hooks", "workflows"})

# Tool-scope namespaces a tool stages into its own config tree (staging Phase 4).
# ``ClaudeAdapter.scoped_namespaces()`` returns this; tools that stage no
# tool-scoped content (Codex/Gemini/OpenCode) return ``()`` independently.
# Every namespace in :data:`ALL` is a tool-tree dir today, so this view currently
# holds the whole vocabulary. It stays a distinct name because it answers a
# narrower question: a namespace that staged outside every tool tree would be in
# :data:`ALL` and not here. None does now. Route destinations are not the example
# of that — a route's ``dest_dir`` is an arbitrary directory name mirrored from its
# source tree, and nothing reads it as a namespace.
TOOL_SCOPED: tuple[str, ...] = ("commands", "skills", "agents", "rules", "hooks", "workflows")

# Shared namespaces staged from ``src/user/.agents`` (staging Phase 2) and
# overlaid from each plugin's ``.agents`` tree (overlay shared scope). Excludes
# ``commands``: shared content is tool-agnostic and there are no shared commands
# (commands are a tool-scoped concept).
SHARED: tuple[str, ...] = ("skills", "agents", "rules")

# The shared namespaces whose DIR units are carrier dirs — a plugin may
# carrier-merge disjoint files into one. Subset of :data:`SHARED`; excludes
# ``rules`` because rules/ holds files, not directories, so it never
# carrier-merges.
SHARED_CARRIER: frozenset[str] = frozenset({"skills", "agents"})

# Plugin tool-scope overlay namespaces (overlay tool scope). v1 plugins ship only
# ``rules``; this set mirrors the tool-scope namespaces a plugin may contribute.
# Excludes ``hooks`` and ``workflows`` that :data:`TOOL_SCOPED` carries: no plugin
# ships them and v1 does not overlay plugin-authored executables or workflows
# (a deferred expansion, kept out of this consolidation to avoid a behavior
# change).
PLUGIN_TOOL_SCOPED: tuple[str, ...] = ("commands", "skills", "agents", "rules")

# Namespaces recorded in the install receipt (prune-eligible tool-tree content).
# Includes ``hooks``: it is staged and deployed (see :data:`TOOL_SCOPED`) and IS
# receipt-tracked, so a removed-source hook is pruned from ~/.claude/hooks/ on
# the next install — the identical fix already applied to ``workflows``.
# This set gates tool-tree items only (``core/ownership.py``); routed content is
# receipt-tracked and pruned through the plugin-route path, which derives its
# entries from each route's own ``dest_dir`` and never consults this vocabulary.
PRUNE: tuple[str, ...] = ("commands", "skills", "agents", "rules", "hooks", "workflows")

# Namespaces whose backups route to a sibling ``<namespace>-backup/`` dir rather
# than an in-place ``<name>.backup-<ts>`` suffix. Includes ``hooks``: an
# overwritten hook script is backed up to ``hooks-backup/`` rather than lost,
# since a hook is an executable in the user's home.
#
# Membership is matched by the target's parent DIRECTORY NAME, not by the
# staging path that produced it (``core/backup.py`` branches on
# ``parent.name in BACKUP``). So a name here relocates the backup of every file
# under a directory of that name — a routed file's as much as a staged one's —
# which is why the set is exactly the staged tool-tree namespaces: those are the
# directories this installer creates and overwrites. Adding a name is cheap;
# removing one moves an existing backup from the sibling dir to in place, so it
# is a behaviour change even when nothing currently deploys there.
BACKUP: frozenset[str] = frozenset({"commands", "skills", "agents", "rules", "hooks", "workflows"})

# Namespaces a tool reads from somewhere other than a directory of the
# namespace's own name at the root of its tree, keyed by ``(tool, namespace)``;
# each value is relative to the tool's destination root.
#
# Antigravity CLI replaced Gemini CLI and reuses ``~/.gemini``, but it discovers
# global skills only under ``~/.gemini/config/skills/``, so a skill deployed to
# ``~/.gemini/skills/`` is never loaded. Everything else under
# ``~/.gemini/config/`` is Antigravity's own state, which is why the relocation
# names the ``skills`` subtree alone and never the ``config`` directory.
#
# The plan key stays ``skills/<name>`` for Gemini as for every other tool, since
# profile selectors, merge collisions, admission and prune eligibility all read
# the namespace from that key. Rewriting the key instead would have every one of
# those readers see ``config`` where they expect ``skills``.
RELOCATED: Mapping[tuple[str, str], Path] = MappingProxyType(
    {("gemini", "skills"): Path("config", "skills")}
)


def deployed_relpath(tool: str, staged: Path) -> Path:
    """Return where a plan item keyed ``staged`` lands, relative to ``tool``'s destination root.

    A path outside every relocated namespace lands at its own key.
    """
    if staged.parts:
        prefix = RELOCATED.get((tool, staged.parts[0]))
        if prefix is not None:
            return prefix.joinpath(*staged.parts[1:])
    return staged


def staged_relpath(tool: str, deployed: Path) -> Path:
    """Return the plan key for an on-disk path relative to ``tool``'s destination root.

    This inverts :func:`deployed_relpath`, so a reader that asks which namespace
    a deployed path belongs to gets ``skills`` for a relocated skill rather than
    the first directory of its relocated prefix. A path outside every relocated
    prefix is its own key.
    """
    for (owner, namespace), prefix in RELOCATED.items():
        if owner == tool and deployed.is_relative_to(prefix):
            return Path(namespace).joinpath(*deployed.parts[len(prefix.parts) :])
    return deployed
