# src/user/.codex/ — OpenAI Codex CLI Source Templates

Codex-specific source content. `scripts/install.sh` stages everything here
into `~/.codex/` when Codex is active (auto-detected if `~/.codex/` exists,
or selected via `--tools=codex`).

## Install model

- `*.md.template` — `.template` suffix stripped on copy
  (`AGENTS.md.template` → `~/.codex/AGENTS.md`,
  `CODEX-EXTENSIONS.md.template` → `~/.codex/CODEX-EXTENSIONS.md`).
- Subdirs (`commands/`, `skills/`, `agents/`, `rules/`) follow the same
  per-type collision rules as the Claude folder if and when they're added
  here: unique names required for `commands/`/`skills/`/`agents/`, append
  for `rules/`.
- `*.json.template` (settings) would union-merge into any existing
  `~/.codex/` equivalent — none shipped today.

## Agent warnings

- These are **source templates**, not runtime config. Editing a file here
  changes what gets installed to users' real `~/.codex/` on next install.
- Shared content from `src/user/.agents/` also stages into `~/.codex/`
  (agents, skills, `INSTRUCTIONS.md`, personas). Name collisions across the
  shared tree + this folder + active plugins are a **fatal install error**
  in `commands/`, `skills/`, and `agents/`.
- `CODEX-EXTENSIONS.md.template` is the Codex-specific workflow extension
  point. Keep Codex-only conventions here; put cross-tool content in
  `src/user/.agents/`.

See the root [AGENTS.md](../../../AGENTS.md) for the full install model, file
format conventions, and repo-wide rules.
