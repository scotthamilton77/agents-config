"""Canonical installer namespace vocabulary — the single source for every
per-concern namespace view.

A *namespace* is a top-level content directory name the installer routes on
(``skills``, ``rules``, …). Historically seven lists across five modules named
these strings independently and drifted: ``hooks`` appeared in one, ``workflows``
was missing from two, ``formulas`` lived in exactly one, and two lists held the
same set in different orders. This module is the one place the vocabulary lives;
each per-concern view below is a named, rationale-carrying subset (or ordering)
of :data:`ALL` that a call site consumes. Add a namespace here and to the views
it belongs to — never re-declare a list at a call site.

Ordering note: for the iterated tuple views (:data:`TOOL_SCOPED`, :data:`SHARED`,
:data:`PLUGIN_TOOL_SCOPED`) iteration order is *not* collision-load-bearing —
each namespace stages under a disjoint ``dest_relpath`` prefix, so no
cross-namespace collision can occur and the resulting plan is order-invariant.
Order is fixed only for deterministic, reproducible plans.
"""

from __future__ import annotations

# The full universe of content-namespace directory names the installer knows.
# Every view below satisfies ``set(view) <= ALL``.
ALL: frozenset[str] = frozenset(
    {"commands", "skills", "agents", "rules", "hooks", "workflows", "formulas"}
)

# Tool-scope namespaces a tool stages into its own config tree (staging Phase 4).
# ``ClaudeAdapter.scoped_namespaces()`` returns this; tools that stage no
# tool-scoped content (Codex/Gemini/OpenCode) return ``()`` independently.
# Excludes ``formulas``: it is plugin-routed to a non-tool root (e.g.
# ``~/.beads/formulas``), never a tool-tree dir.
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
# Excludes ``hooks``: it is staged and deployed (see :data:`TOOL_SCOPED`) but is
# NOT currently receipt-tracked, so a removed-source hook survives forever in
# ~/.claude/hooks/ — a suspected latent gap (the identical gap was deliberately
# fixed for ``workflows``, which is why workflows IS here). Preserved as-is so
# this consolidation changes no behavior; the prune-policy fix is tracked as
# separate follow-up work. Excludes ``formulas``: plugin-routed content is pruned
# via the plugin-route receipt path, not this tool-tree set.
PRUNE: tuple[str, ...] = ("commands", "skills", "agents", "rules", "workflows")

# Namespaces whose backups route to a sibling ``<namespace>-backup/`` dir rather
# than an in-place ``<name>.backup-<ts>`` suffix. Includes ``formulas``: an
# overwritten plugin-route file still gets a sibling-dir backup. Excludes
# ``hooks`` (the same suspected gap as :data:`PRUNE`).
BACKUP: frozenset[str] = frozenset(
    {"commands", "skills", "agents", "rules", "formulas", "workflows"}
)
