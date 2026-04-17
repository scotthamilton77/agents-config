# src/user/.codex/ — OpenAI Codex CLI Content

Codex-specific content that `scripts/install.sh` copies into `~/.codex/` when
Codex is selected, either explicitly via `--tools=codex` or automatically
because `~/.codex/` already exists.

## What lives here

- `AGENTS.md.template` — Top-level instruction file that pulls in the shared
  `INSTRUCTIONS.md`, personas, and `CODEX-EXTENSIONS.md`.
- `CODEX-EXTENSIONS.md.template` — Placeholder for Codex-specific workflow
  additions. Currently empty; populate as Codex-specific conventions emerge.

## Where it installs

Into `~/.codex/` (user-scoped Codex CLI config). The installer strips the
`.template` suffix on copy.

Shared content from `src/user/.agents/` also installs into `~/.codex/`
(agents, skills, `INSTRUCTIONS.md`, personas).

## Who it's for

OpenAI Codex CLI users who want the same agents, skills, and persona setup
they'd get under Claude Code, adapted to Codex's conventions.

See the [root README](../../../README.md) for install flow and customization
pointers.
