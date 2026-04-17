# src/user/.claude/ — Claude Code Source Templates

Claude-specific source content. `scripts/install.sh` stages everything here
into `~/.claude/` (Claude is always an active tool; never auto-detected away).

## Install model

- `*.md.template` — `.template` suffix stripped on copy
  (`AGENTS.md.template` → `~/.claude/AGENTS.md`,
  `CLAUDE.md.template` → `~/.claude/CLAUDE.md`, etc.).
- `commands/`, `skills/`, `agents/` — entries copied as-is; **names must be
  unique** across the merged tree (shared `src/user/.agents/` + this folder
  + active plugins). Collisions are a **fatal install error**.
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
  collisions in `agents/`, `skills/`, or top-level templates span both trees.
  Check before adding.
- `rules/` is the append-only extension point for Claude-specific workflow
  (delegation, completion gate, delivery, git, subagents, codex routing).
  Keep files scoped and single-purpose.

See the root [AGENTS.md](../../../AGENTS.md) for the full install model, file
format conventions, and repo-wide rules.
