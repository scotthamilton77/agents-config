# src/user/.claude/ — Claude Code Content

Claude-specific content that `scripts/install.sh` copies into `~/.claude/`
by default.

## What lives here

- `commands/` — Slash commands, one flat markdown file each; `$ARGUMENTS` is
  substituted at runtime. Front matter carrying a complete `admission:` record
  is required, not optional: without one the installer drops the file and
  `content-lint` fails the build, so a command written as bare markdown ships
  nothing.
- `rules/` — Claude-specific workflow rules, under that same gate. Each rules
  directory carries its own `AGENTS.md` saying what is currently in it; read
  that rather than counting files here.
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
