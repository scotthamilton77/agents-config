"""Canonical installer namespace vocabulary — the single source for every
per-concern namespace view.

A *namespace* is a top-level content directory name the installer routes on
(``skills``, ``rules``, …). Historically seven lists across five modules named
these strings independently and drifted: ``hooks`` appeared in one, ``workflows``
was missing from two, and two lists held the same set in different orders. This
module is the one place the vocabulary lives; each per-concern view below is a
named, rationale-carrying subset (or ordering) of :data:`ALL` that a call site
consumes. Add a namespace here and to the views it belongs to — never re-declare
a list at a call site.

Ordering note: for the iterated tuple views (:data:`TOOL_SCOPED`, :data:`SHARED`,
:data:`PLUGIN_TOOL_SCOPED`) iteration order is *not* collision-load-bearing —
each namespace stages under a disjoint ``dest_relpath`` prefix, so no
cross-namespace collision can occur and the resulting plan is order-invariant.
Order is fixed only for deterministic, reproducible plans.
"""

from __future__ import annotations

# The full universe of content-namespace directory names the installer knows.
# Every view below satisfies ``set(view) <= ALL``.
ALL: frozenset[str] = frozenset({"commands", "skills", "agents", "rules", "hooks", "workflows"})

# Tool-scope namespaces a tool stages into its own config tree (staging Phase 4).
# ``ClaudeAdapter.scoped_namespaces()`` returns this; tools that stage no
# tool-scoped content (Codex/Gemini/OpenCode) return ``()`` independently.
# Every namespace in :data:`ALL` is a tool-tree dir today, so this view currently
# holds the whole vocabulary. It stays a distinct name because it answers a
# narrower question: content that lands outside every tool tree — what a route's
# ``dest_dir`` names — belongs to :data:`ALL` but not here.
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
