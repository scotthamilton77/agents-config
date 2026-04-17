# src/user/.gemini/ — Google Gemini CLI Content

Gemini-specific content that `scripts/install.sh` copies into `~/.gemini/`
when Gemini is selected by the installer, such as when `~/.gemini/` already
exists or when the user passes `--tools=gemini`.

## What lives here

- `GEMINI.md.template` — Top-level instruction file that pulls in the shared
  `INSTRUCTIONS.md`, personas, and `GEMINI-EXTENSIONS.md`.
- `GEMINI-EXTENSIONS.md.template` — Placeholder for Gemini-specific workflow
  additions. Currently empty; populate as Gemini-specific conventions emerge.

## Where it installs

Into `~/.gemini/` (user-scoped Gemini CLI config). The installer strips the
`.template` suffix on copy.

Shared content from `src/user/.agents/` also installs into `~/.gemini/`
(agents, skills, `INSTRUCTIONS.md`, personas).

## Who it's for

Google Gemini CLI users who want the same agents, skills, and persona setup
they'd get under Claude Code, adapted to Gemini's conventions.

See the [root README](../../../README.md) for install flow and customization
pointers.
