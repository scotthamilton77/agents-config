# src/user/.opencode/ — OpenCode Source Templates

OpenCode-specific source content. `scripts/install.sh` stages content here into
`~/.config/opencode/` when OpenCode is active (auto-detected if `opencode` is on
PATH or `~/.config/opencode/` exists, or selected via `--tools=opencode`).

## Install model

- `*.md.template` — `.template` suffix stripped on copy
  (`AGENTS.md.template` → `~/.config/opencode/AGENTS.md`).
- `opencode.jsonc.template` → `~/.config/opencode/opencode.jsonc` (plain copy).

## Dynamic flattening

`AGENTS.md.template` is special: it is a single `<!-- DYNAMIC-INCLUDE: path -->`
marker (today it pulls in `USER-CORE.md.template`), which the installer
resolves at staging time, producing a flat `AGENTS.md` with no `@` references.
This is required because OpenCode does not support `@` include resolution.
The installer also supports a `<!-- DYNAMIC-INCLUDE-ALL-RULES -->` marker and
a named `<!-- DYNAMIC-INCLUDE-RULES: ruleA,ruleB -->` subset marker, but this
template carries neither today, so no rules content is inlined into
OpenCode's `AGENTS.md`.

## Skills

Shared skills stage into `~/.config/opencode/skills/` the same way they stage
into every other tool's tree (one directory per skill, bare names like
`review-verdict`). OpenCode scans that directory by default, so
`opencode.jsonc.template` carries no `skills` key: `skills.paths` only *adds*
roots to the defaults, and an entry naming this one would restate a default
while reading as the mechanism that makes skills load.

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
