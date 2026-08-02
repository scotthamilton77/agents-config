# src/user/.claude/ — Claude Code Source Templates

Claude-specific source content. `scripts/install.sh` stages everything here
into `~/.claude/` (Claude is always an active tool; never auto-detected away).

## Install model

- `*.md.template` — `.template` suffix stripped on copy
  (`AGENTS.md.template` → `~/.claude/AGENTS.md`,
  `CLAUDE.md.template` → `~/.claude/CLAUDE.md`, etc.).
- `skills/` — entries copied as-is; **names must be unique** across the merged
  tree (shared `src/user/.agents/` + this folder + active plugins). Collisions
  are a **fatal install error**.
- `rules/*.md` — collisions are allowed: files with the same name are
  **appended** (base first, plugins alphabetically) with a `---` separator.
- `settings.json.template` — **union-merged** with any existing
  `~/.claude/settings.json` via `jq` (user values preserved, arrays
  deduplicated, new keys added).

## Agent warnings

- These are **source templates**. Editing a file here changes what lands in
  `~/.claude/` on next install. Do not edit `~/.claude/...` to fix something
  that should live here.
- Shared content from `src/user/.agents/` also stages into `~/.claude/`, so
  collisions in `skills/`, `rules/`, or top-level templates span both trees.
  Check before adding.
- `rules/` is the append-only extension point for Claude-specific workflow
  (stuff that would only apply in a Claude context, plus any plugin
  append-merges); tool-agnostic rules source from `src/user/.agents/rules/`
  and stage into `~/.claude/rules/` at install time. Both are empty today —
  the record-less rules moved to `archive/src/user/**`. Keep files scoped and
  single-purpose.
- `commands/*.md` — one flat file per command; a tool-scoped namespace with no
  shared variant, so Claude is the only tree that carries one.
- Everything in `commands/`, `skills/` and `rules/` is subject to the admission gate: no
  `admission:` record in front matter means the installer drops it and prunes
  any deployed copy. Adding a file here without a record ships nothing.

See the root [AGENTS.md](../../../AGENTS.md) for the full install model, file
format conventions, and repo-wide rules.
