# src/user/.claude/ — Claude Code Content

Claude-specific content that `scripts/install.sh` copies into `~/.claude/`
by default.

## What lives here

- `commands/` — Slash commands. Plain markdown; `$ARGUMENTS` is substituted at
  runtime. Empty today: every command was record-less and moved to
  `archive/src/user/.claude/commands/`.
- `rules/` — Claude-specific workflow rules. Empty today: every rule was
  record-less and moved to `archive/src/user/.claude/rules/`. Readmission
  requires an admission record.
- `AGENTS.md.template` — Top-level instruction file that pulls in the shared
  personas and session-primer, and `CLAUDE-EXTENSIONS.md`. Does not yet pull
  in the shared zero-based `AGENTS.md.template` survivor — see that file's
  entry in `src/user/.agents/README.md` (`agents-config-9k9.10`).
- `CLAUDE.md.template` — Thin wrapper pointing at `AGENTS.md`.
- `CLAUDE-EXTENSIONS.md.template` — Stub header kept for compatibility;
  Claude-specific workflow now lives in `rules/`.
- `settings.json.template` — Permission allowlists, hooks, and experimental
  features. The installer union-merges this into any existing
  `~/.claude/settings.json`.

## Where it installs

Into `~/.claude/` (user-scoped Claude Code config). The installer strips the
`.template` suffix on copy. Existing files get diff previews before overwrite.

## Who it's for

Claude Code users who want to adopt this repo's agents, skills, rules, and
slash commands. Shared content from `src/user/.agents/` also installs into
`~/.claude/` alongside the files in this folder.

See the [root README](../../../README.md) for install flow and customization
pointers.
