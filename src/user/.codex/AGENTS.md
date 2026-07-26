# src/user/.codex/ — OpenAI Codex CLI Source Templates

Codex-specific source content. `scripts/install.sh` stages everything here
into `~/.codex/` when Codex is active (auto-detected if `~/.codex/` exists,
or selected via `--tools=codex`).

## Install model

- `*.md.template` — `.template` suffix stripped on copy
  (`AGENTS.md.template` → `~/.codex/AGENTS.md`).
- This folder ships no subdirectories. Codex-specific skills or rules would
  live in `skills/` or `rules/` here and follow the same collision and
  admission rules as the Claude folder.

## Agent warnings

- These are **source templates**, not runtime config. Editing a file here
  changes what gets installed to users' real `~/.codex/` on next install.
- Shared content from `src/user/.agents/` also stages into `~/.codex/`. Name
  collisions in `skills/` across the shared tree + this folder + active
  plugins are a **fatal install error**.
- `AGENTS.md.template` is the Codex-specific workflow extension point. Keep
  Codex-only conventions here; put cross-tool content in `src/user/.agents/`.

See the root [AGENTS.md](../../../AGENTS.md) for the full install model, file
format conventions, and repo-wide rules.
