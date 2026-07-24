# src/user/.agents/ — Shared Source Templates

Tool-agnostic source content. `scripts/install.sh` stages everything here into
**every active tool** (Claude always; Codex and Gemini when their `~/.<tool>/`
dir exists or `--tools=` selects them).

## Install model

- `*.md.template` — `.template` suffix stripped on copy; lands at
  `~/.<tool>/<basename>.md` (e.g. `AGENTS.md.template` → `~/.claude/AGENTS.md`,
  by DYNAMIC-INCLUDE into the per-tool assembled instruction file).
- `agents/` — each top-level entry copied; **names must be unique** across the
  combined tree (shared + tool-specific + active plugins). Collisions are a
  **fatal install error**.
- `skills/` — each top-level entry copied; **names must be unique** across the
  combined tree (shared + tool-specific + active plugins). Collisions are a
  **fatal install error**.
- `rules/` — tool-agnostic workflow rules. Each file is copied into every
  active tool's `rules/` directory; **same-name collisions append-merge**
  with a `---` separator (base first, plugins alphabetically).
- Tool-specific files (`.claude/`, `.codex/`, `.gemini/`, `.opencode/`) overlay
  on top of these in later phases; plugin content overlays last. Ordering matters.
- OpenCode gets a **flat, dynamically-built AGENTS.md** (no `@` includes).
  See `src/user/.opencode/` for details.

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
