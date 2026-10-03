# src/user/.codex/ — OpenAI Codex CLI Source Templates

Codex-specific source content. `scripts/install.sh` stages everything here
into `~/.codex/` when Codex is active (auto-detected if `~/.codex/` exists,
or selected via `--tools=codex`).

## Install model

- `*.md.template` — `.template` suffix stripped on copy
  (`AGENTS.md.template` → `~/.codex/AGENTS.md`).
- Only top-level templates stage from this folder. The Codex adapter declares
  no tool-scoped namespaces, so a `skills/` or `rules/` directory here deploys
  nowhere, and `make content-lint` reports it as unaccounted content. Codex
  receives skills and rules from the shared tree alone.

## Agent warnings

- These are **source templates**, not runtime config. Editing a file here
  changes what gets installed to users' real `~/.codex/` on next install.
- Shared content from `src/user/.agents/` also stages into `~/.codex/`. Name
  collisions in `skills/` across the shared tree and active plugins are a
  **fatal install error**, with one exception: a plugin's shared skill merges
  into a same-named shared skill when their files do not overlap.
- `AGENTS.md.template` is the Codex-specific workflow extension point. Keep
  Codex-only conventions here; put cross-tool content in `src/user/.agents/`.

See the root [AGENTS.md](../../../AGENTS.md) for repo-wide rules, and
[packages/installer/AGENTS.md](../../../packages/installer/AGENTS.md) for how
the installer stages this tree.
