# src/user/.agents/ — Shared Source Templates

Tool-agnostic source content. `scripts/install.sh` stages everything here into
**every active tool** (Claude always; Codex and Gemini when their `~/.<tool>/`
dir exists or `--tools=` selects them).

## Install model

- `*.md.template` — `.template` suffix stripped on copy; lands at
  `~/.<tool>/<basename>.md` (e.g. `INSTRUCTIONS.md.template` → `~/.claude/INSTRUCTIONS.md`).
- `agents/`, `skills/` — each top-level entry copied; **names must be unique**
  across the combined tree (shared + tool-specific + active plugins).
  Collisions in these dirs are a **fatal install error**.
- Tool-specific files (`.claude/`, `.codex/`, `.gemini/`) overlay on top of
  these in later phases; plugin content overlays last. Ordering matters.

## Agent warnings

- These are **source templates**, not runtime config. Editing a file here
  changes what gets installed into users' real configs on next `install.sh` run.
- Do not confuse `src/user/.agents/agents/foo.md` (source) with
  `~/.claude/agents/foo.md` (installed copy) — never edit the installed copy
  from this repo.
- Before adding a new agent or skill, check for name collisions in
  `src/user/.claude/`, `src/user/.codex/`, `src/user/.gemini/`, and every
  `src/plugins/*/` — the installer aborts on duplicate names.

See the root [AGENTS.md](../../../AGENTS.md) for the full install model, file
format conventions, and repo-wide rules.
