# src/user/.codex/ — OpenAI Codex CLI Content

Codex-specific content that `scripts/install.sh` copies into `~/.codex/` when
Codex is selected, either explicitly via `--tools=codex` or automatically
because `~/.codex/` already exists.

## What lives here

- `AGENTS.md.template` — Top-level instruction file. It is a single
  `DYNAMIC-INCLUDE` of the shared zero-based core in
  `src/user/.agents/USER-CORE.md.template`, which the installer flattens in at
  deploy time. It ends with a bare `## Custom content` heading, and whatever
  the user writes below that heading in the deployed file is theirs: each
  install rewrites the part above it and reproduces the part below it
  untouched. Codex has no import mechanism, so a section of the file itself is
  the only route to the user's own always-on content.

## Where it installs

Into `~/.codex/` (user-scoped Codex CLI config). The installer strips the
`.template` suffix on copy.

Shared content from `src/user/.agents/` also installs into `~/.codex/` — the
skills, and the rules directory, which is empty today. No agent definitions and
no persona templates exist to install: the always-on surface is zero-based and
carries no identity content.

## Who it's for

OpenAI Codex CLI users who want the same skills and the same shared instruction
core they'd get under Claude Code.

See the [root README](../../../README.md) for install flow and customization
pointers.
