# Getting Started

## Prerequisites

- **An AI coding assistant** — one or more of: Claude Code, OpenAI Codex CLI,
  Google Gemini CLI, OpenCode. The installer detects which you have and installs
  to each.
- **`uv`** — the installer is a uv-managed Python package; `uv` auto-installs a
  suitable Python (≥3.11) on first run. `uv` ≥ 0.10.4 is required for the stage
  that puts this repo's CLIs on your PATH.

Nothing else is required. Two things that earlier versions of this guide listed
as prerequisites are now optional:

- **[steveyegge/beads](https://github.com/steveyegge/beads)** — the `bd` work
  tracker. The `work` CLI the installer puts on your PATH is a facade over `bd`
  and does nothing useful without it. Nothing in the installed instruction
  surface requires either one, so skip both if you do not want a tracker.
- **[obra/superpowers](https://github.com/obra/superpowers)** — no longer a
  dependency. The rules and skills that referenced its process skills have been
  retired; nothing that installs today calls into it.

## Install

From the repo root:

```bash
# Preview exactly what would change — always safe
./scripts/install.sh --dry-run

# Install with confirmation prompts
./scripts/install.sh

# Install and remove anything the installer previously owned but no longer ships
./scripts/install.sh --prune
```

The installer auto-detects your tools. Override with `--tools=claude,codex` (or
`gemini`, `opencode`). See the [README installer section](../../README.md#installation)
for the full flag list and pruning semantics.

## What lands where

Shared content installs into **every** detected tool; tool-specific content only
into its own tool.

| Source | Installs to | Contains |
|--------|-------------|----------|
| `src/user/.agents/` | each tool's config dir | shared skills, shared rules, and the instruction-file core |
| `src/user/.claude/` | `~/.claude/` | slash commands, Claude-only skills and rules, hooks, `settings.json` |
| `src/user/.codex/` | `~/.codex/` | Codex instruction file |
| `src/user/.gemini/` | `~/.gemini/` | Gemini instruction file |
| `src/user/.opencode/` | `~/.config/opencode/` | OpenCode instruction file + settings |
| `src/plugins/<name>/` | matching tools, when detected | optional plugin content |

Two things decide whether a given skill, rule, command, or agent actually lands.
It has to be in the source tree, and its front matter has to carry a complete
**admission record** — what it prevents or provides, what it costs, and what
observation would remove it. Anything missing that record is dropped at install
and pruned on the next run, so the source directory is the upper bound on what
you get rather than a promise. `src/user/.agents/rules/` is empty today for
exactly this reason.

`*.md.template` files install with the `.template` suffix stripped (e.g.
`AGENTS.md.template` → `AGENTS.md`). Existing files get a diff preview and a
timestamped backup before any overwrite.

The installer also puts this repo's CLIs on your PATH via `uv tool install`
(receipt-tracked, pruned on retirement). They are `work`, `prgroom`, `grind`,
`executor` and `gitclean`; `CLI_PACKAGES` in
`packages/installer/src/installer/core/clis.py` is the authoritative list. Of
those, `gitclean` is the one the installed skills actually reach for.

## Verify the install

Open your assistant in any project and confirm the pieces are visible:

- Ask it to list available skills — you should see `grilling`, `to-spec`,
  `review-panel`, `writing-skills`, and the rest of what is under
  `src/user/.agents/skills/` and `src/user/.claude/skills/`.
- Check that `~/.claude/AGENTS.md` (or your tool's instruction file) exists
  and carries the zero-based `<laws>`/`<decisions>`/`<hard-lines>`/
  `<conventions>` core — a fresh `./scripts/install.sh` run composes it from
  the shared zero-base fragment.

## Next: make it yours

Review the installed `settings.json` and tell the assistant about your project —
see [Configuration](./configuration.md).
