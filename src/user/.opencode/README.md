# OpenCode Configuration Source

This directory contains source templates for OpenCode (`opencode`) support.

## Contents

- `AGENTS.md.template` — Skeleton with dynamic-include markers for the flat instruction file
- `opencode.jsonc.template` — Settings (model, permissions)

## How it works

`install.sh` builds a flat `AGENTS.md` at install time by:
1. Reading `AGENTS.md.template`
2. Resolving its `<!-- DYNAMIC-INCLUDE: path -->` marker (inlines
   `USER-CORE.md.template`'s content)
3. Writing the result to `~/.config/opencode/AGENTS.md`

The template carries no `<!-- DYNAMIC-INCLUDE-ALL-RULES -->` or
`<!-- DYNAMIC-INCLUDE-RULES: ... -->` marker today, so no rules content
reaches OpenCode's `AGENTS.md`. This preserves DRY (content lives in one
place) while producing a file OpenCode can use.
