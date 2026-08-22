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
- `hooks/` — Python scripts referenced by `settings.json.template`'s hook
  commands (invoked as `python3 {{HOME}}/.claude/hooks/<script>.py`); each
  script ships a paired test. `{{HOME}}` is resolved by the installer to the
  home that run installs into — `~` for the user's own home, an absolute path
  for any other — so the command names the copy that run placed. Write a new
  hook command with the placeholder, never a literal `~`.
- `settings.json.template` — **union-merged** with any existing
  `~/.claude/settings.json` by the installer's own deep-merge strategy (pure
  Python, no `jq` dependency): dicts recurse, arrays concatenate and dedupe,
  a scalar conflict keeps the existing value, and new keys are added.

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
  and stage into `~/.claude/rules/` at install time. Each of those directories
  carries its own `AGENTS.md` saying what is currently in it; read that rather
  than counting files. Keep files scoped and single-purpose.
- `commands/*.md` — one flat file per command; a tool-scoped namespace with no
  shared variant, so Claude is the only tree that carries one.
- Everything in `commands/`, `skills/`, `rules/` and `workflows/` is subject to
  the admission gate: no `admission:` record in front matter means the installer
  drops it and prunes any deployed copy. Adding a file here without a record
  ships nothing.
- `workflows/*.js` — gated like the rest, and a `.js` file has no front matter of
  its own, so the record goes in a leading `---` fence holding nothing but the
  `admission:` block. The installer strips that block, and the now-empty fence
  with it, so the deployed file is plain JavaScript; the authored file is not
  valid JS until then. There is no workflow in the tree today.

See the root [AGENTS.md](../../../AGENTS.md) for the full install model, file
format conventions, and repo-wide rules.
