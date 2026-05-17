# src/user/.opencode/ — OpenCode Source Templates

OpenCode-specific source content. `scripts/install.sh` stages content here into
`~/.config/opencode/` when OpenCode is active (auto-detected if `opencode` is on
PATH or `~/.config/opencode/` exists, or selected via `--tools=opencode`).

## Install model

- `*.md.template` — `.template` suffix stripped on copy
  (`AGENTS.md.template` → `~/.config/opencode/AGENTS.md`).
- `opencode.jsonc.template` → `~/.config/opencode/opencode.jsonc` (plain copy).

## Dynamic flattening

`AGENTS.md.template` is special: it contains `<!-- DYNAMIC-INCLUDE: path -->` and
`<!-- DYNAMIC-INCLUDE-ALL-RULES -->` markers that the installer
resolves at staging time, producing a single flat `AGENTS.md` with no `@`
references. This is required because OpenCode does not support `@` include
resolution.

## Skills

OpenCode scans `~/.claude/skills/**/SKILL.md` natively. Shared skills are
available without duplication. Some referenced skills (e.g. `superpowers:*`)
require the [obra/superpowers](https://github.com/obra/superpowers) Claude Code
plugin.

## Agents

Shared agents from `src/user/.agents/agents/` are **not** installed to OpenCode
for now because the frontmatter format differs (OpenCode uses provider-prefixed
model IDs, `mode:`, `permission:`, etc.). Install OpenCode-specific agents to
`~/.config/opencode/agents/` manually if needed.

## Commands

Shared commands from `src/user/.claude/commands/` are **not** installed to
OpenCode. OpenCode commands live in `~/.config/opencode/commands/` and use a
slightly different frontmatter format.

## Agent warnings

These are **source templates**, not runtime config. Editing a file here changes
what gets installed to users' real `~/.config/opencode/` on next install.

See the root [AGENTS.md](../../../AGENTS.md) for the full install model.
