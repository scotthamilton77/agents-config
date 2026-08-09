# src/user/.agents/ — Shared Source Templates

Tool-agnostic source content. `scripts/install.sh` stages everything here into
**every active tool** (Claude always; Codex and Gemini when their `~/.<tool>/`
dir exists; OpenCode when `opencode` is on PATH or `~/.config/opencode/`
exists; or `--tools=` selects any of them).

## Install model

- `USER-CORE.md.template` — this directory's only top-level template, and
  include-only: each tool's own `AGENTS.md.template` (or `GEMINI.md.template`
  for Gemini) pulls it in with a `DYNAMIC-INCLUDE` marker, and the
  installer's template-flattening step drops the standalone copy during
  staging, so it never lands on its own as `~/.<tool>/USER-CORE.md`.
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
- Do not confuse a source file here with its installed copy under `~/.<tool>/`
  (`~/.config/opencode/` for OpenCode) — never edit the installed copy from
  this repo.
- Before adding a skill or rule, check for name collisions against
  `src/user/.claude/` and every `src/plugins/*/` — the installer aborts on
  duplicate names.

See the root [AGENTS.md](../../../AGENTS.md) for the full install model, file
format conventions, and repo-wide rules.
