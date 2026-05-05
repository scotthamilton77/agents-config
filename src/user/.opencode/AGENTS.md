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
`<!-- DYNAMIC-INCLUDE-RULES: rule1,rule2,... -->` markers that the installer
resolves at staging time, producing a single flat `AGENTS.md` with no `@`
references. This is required because OpenCode does not support `@` include
resolution.

## Agent warnings

These are **source templates**, not runtime config. Editing a file here changes
what gets installed to users' real `~/.config/opencode/` on next install.

See the root [AGENTS.md](../../../AGENTS.md) for the full install model.
