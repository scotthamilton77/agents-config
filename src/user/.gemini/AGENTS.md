# src/user/.gemini/ — Antigravity CLI Source Templates

Gemini-specific source content. `scripts/install.sh` stages everything here
into `~/.gemini/` when Gemini is active (auto-detected if `~/.gemini/`
exists, or selected via `--tools=gemini`).

## Install model

- `*.md.template` — `.template` suffix stripped on copy
  (`GEMINI.md.template` → `~/.gemini/GEMINI.md`).
- Only top-level templates stage from this folder. The Gemini adapter declares
  no tool-scoped namespaces, so a `skills/` or `rules/` directory here deploys
  nowhere, and `make content-lint` reports it as unaccounted content. Gemini
  receives skills and rules from the shared tree alone.

## Agent warnings

- These are **source templates**, not runtime config. Editing a file here
  changes what gets installed to users' real `~/.gemini/` on next install.
- Shared content from `src/user/.agents/` also stages into `~/.gemini/`.
  Shared skills land in `~/.gemini/config/skills/`, the only place Antigravity
  CLI discovers global skills. Name collisions in `skills/` across the shared
  tree and active plugins are a **fatal install error**, with one exception: a
  plugin's shared skill merges into a same-named shared skill when their files
  do not overlap.
- `GEMINI.md.template` is the Gemini-specific workflow extension point. Keep
  Gemini-only conventions here; put cross-tool content in `src/user/.agents/`.

See the root [AGENTS.md](../../../AGENTS.md) for repo-wide rules, and
[packages/installer/AGENTS.md](../../../packages/installer/AGENTS.md) for how
the installer stages this tree.
