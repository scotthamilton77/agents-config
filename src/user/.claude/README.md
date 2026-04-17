# src/user/.claude/ — Claude Code Content

Claude-specific content that `scripts/install.sh` copies into `~/.claude/`
when Claude Code is detected on the system.

## What lives here

- `commands/` — Slash commands (e.g. `/optimize-my-agent`,
  `/refresh-agents-md`). Plain markdown; `$ARGUMENTS` is substituted at
  runtime.
- `rules/` — Claude-specific workflow rules that implement the shared
  `<verification-checklist>` and related protocols:
  - `delegation.md` — when to use which skill
  - `completion-gate.md` — code review, simplification, and verification gate
  - `delivery.md` — worktree isolation, PR creation, Copilot review monitoring
  - `git-commits.md` — commit style under the sandbox
  - `subagents.md` — subagent dispatch rules
  - `codex-routing.md` — when to delegate to the Codex plugin, and which model
- `AGENTS.md.template` — Top-level instruction file that pulls in the shared
  `INSTRUCTIONS.md`, personas, and `CLAUDE-EXTENSIONS.md`.
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
