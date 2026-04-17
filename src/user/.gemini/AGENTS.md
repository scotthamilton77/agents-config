# src/user/.gemini/ — Google Gemini CLI Source Templates

Gemini-specific source content. `scripts/install.sh` stages everything here
into `~/.gemini/` when Gemini is active (auto-detected if `~/.gemini/`
exists, or selected via `--tools=gemini`).

## Install model

- `*.md.template` — `.template` suffix stripped on copy
  (`GEMINI.md.template` → `~/.gemini/GEMINI.md`,
  `GEMINI-EXTENSIONS.md.template` → `~/.gemini/GEMINI-EXTENSIONS.md`).
- Subdirs (`commands/`, `skills/`, `agents/`, `rules/`) follow the same
  per-type collision rules as the Claude folder if and when they're added
  here: unique names required for `commands/`/`skills/`/`agents/`, append
  for `rules/`.
- `*.json.template` (settings) would union-merge into any existing
  `~/.gemini/` equivalent — none shipped today.

## Agent warnings

- These are **source templates**, not runtime config. Editing a file here
  changes what gets installed to users' real `~/.gemini/` on next install.
- Shared content from `src/user/.agents/` also stages into `~/.gemini/`
  (agents, skills, `INSTRUCTIONS.md`, personas). Name collisions across the
  shared tree + this folder + active plugins are a **fatal install error**
  in `commands/`, `skills/`, and `agents/`.
- `GEMINI-EXTENSIONS.md.template` is the Gemini-specific workflow extension
  point. Keep Gemini-only conventions here; put cross-tool content in
  `src/user/.agents/`.

See the root [AGENTS.md](../../../AGENTS.md) for the full install model, file
format conventions, and repo-wide rules.
