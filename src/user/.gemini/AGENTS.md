# src/user/.gemini/ — Google Gemini CLI Source Templates

Gemini-specific source content. `scripts/install.sh` stages everything here
into `~/.gemini/` when Gemini is active (auto-detected if `~/.gemini/`
exists, or selected via `--tools=gemini`).

## Install model

- `*.md.template` — `.template` suffix stripped on copy
  (`GEMINI.md.template` → `~/.gemini/GEMINI.md`).
- This folder ships no subdirectories. Gemini-specific skills or rules would
  live in `skills/` or `rules/` here and follow the same collision and
  admission rules as the Claude folder.

## Agent warnings

- These are **source templates**, not runtime config. Editing a file here
  changes what gets installed to users' real `~/.gemini/` on next install.
- Shared content from `src/user/.agents/` also stages into `~/.gemini/`. Name
  collisions in `skills/` across the shared tree + this folder + active
  plugins are a **fatal install error**.
- `GEMINI.md.template` is the Gemini-specific workflow extension point. Keep
  Gemini-only conventions here; put cross-tool content in `src/user/.agents/`.

See the root [AGENTS.md](../../../AGENTS.md) for the full install model, file
format conventions, and repo-wide rules.
