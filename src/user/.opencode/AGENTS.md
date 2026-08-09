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

Shared skills stage into `~/.config/opencode/skills/` the same way they stage
into every other tool's tree (one directory per skill, bare names like
`review-verdict`). `opencode.jsonc.template`'s `skills.paths` points OpenCode
at that same directory, so the installed config and the installed content
agree on where to look.

## Agents and commands

This repo ships neither. If it ever does, they will not cross over to OpenCode
unchanged: OpenCode's agent frontmatter uses provider-prefixed model IDs plus
`mode:` and `permission:` keys, and its command frontmatter differs again.
OpenCode-specific ones would be installed by hand to
`~/.config/opencode/agents/` and `~/.config/opencode/commands/`.

## Agent warnings

These are **source templates**, not runtime config. Editing a file here changes
what gets installed to users' real `~/.config/opencode/` on next install.

See the root [AGENTS.md](../../../AGENTS.md) for the full install model.
