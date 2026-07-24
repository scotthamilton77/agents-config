# Getting Started

## Prerequisites

- **An AI coding assistant** — one or more of: Claude Code, OpenAI Codex CLI,
  Google Gemini CLI, OpenCode. The installer detects which you have and installs
  to each.
- **[obra/superpowers](https://github.com/obra/superpowers)** (Claude Code
  plugin) — provides the process skills the workflow rules lean on
  (`test-driven-development`, verification, worktree helpers).
  Without it, several skills and rules reference things that don't exist.
- **[steveyegge/beads](https://github.com/steveyegge/beads)** — the `bd`
  work tracker. The workflow treats durable work as beads that survive across
  sessions and context compaction.
- **`uv`** — the installer is a uv-managed Python package; `uv` auto-installs a
  suitable Python (≥3.11) on first run. `uv` ≥ 0.10.4 is required for the
  installer's CLI-deploy stage (see [Configuration](./configuration.md#optional-the-prgroom-cli)).

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
| `src/user/.agents/` | each tool's config dir | shared agents, skills, workflow rules, persona templates |
| `src/user/.claude/` | `~/.claude/` | slash commands, Claude-only skills/rules, `settings.json` |
| `src/user/.codex/` | `~/.codex/` | Codex instruction file + extensions |
| `src/user/.gemini/` | `~/.gemini/` | Gemini instruction file + extensions |
| `src/user/.opencode/` | `~/.config/opencode/` | OpenCode instruction skeleton + settings |
| `src/plugins/<name>/` | matching tools, when detected | optional plugin rules (beads, graphify, codex) |

`*.md.template` files install with the `.template` suffix stripped (e.g.
`AGENTS.md.template` → `AGENTS.md`). Existing files get a diff preview and a
timestamped backup before any overwrite. The installer also deploys the
`work` and `prgroom` CLIs onto your PATH via `uv tool install` (uv ≥ 0.10.4
required for this stage).

## Verify the install

Open your assistant in any project and confirm the pieces are visible:

- Ask it to list available skills — you should see `grilling`,
  `test-driven-development`, `verify-checklist`, `merge-guard`, and the rest.
- Check that `~/.claude/AGENTS.md` (or your tool's instruction file) exists
  and carries the zero-based `<laws>`/`<decisions>`/`<hard-lines>`/
  `<conventions>` core — a fresh `./scripts/install.sh` run composes it from
  the shared zero-base fragment.

## Next: make it yours

The templates ship with the author's personal identity and preferences. Before
real use, personalize the personas and review `settings.json` — see
[Configuration](./configuration.md).
