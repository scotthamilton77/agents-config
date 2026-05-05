# OpenCode Configuration Source

This directory contains source templates for OpenCode (`opencode`) support.

## Contents

- `AGENTS.md.template` — Skeleton with dynamic-include markers for the flat instruction file
- `OPENCODE-EXTENSIONS.md.template` — OpenCode-specific notes and conventions
- `opencode.jsonc.template` — Settings (model, permissions, skills paths)

## How it works

`install.sh` builds a flat `AGENTS.md` at install time by:
1. Reading `AGENTS.md.template`
2. Resolving `<!-- DYNAMIC-INCLUDE: path -->` markers (inlines referenced file content)
3. Resolving `<!-- DYNAMIC-INCLUDE-RULES: rule1,... -->` markers (inlines rules from `src/user/.claude/rules/`)
4. Writing the result to `~/.config/opencode/AGENTS.md`

This preserves DRY (content lives in one place) while producing a file OpenCode can use.
