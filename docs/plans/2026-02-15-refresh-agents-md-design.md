# Design: refresh-agents-md Command

## Purpose

A Claude Code command that performs a full refresh of all CLAUDE.md and AGENTS.md files across a project, using git history as context and the optimize-agents-md skill principles for quality.

## Input

`$ARGUMENTS` — free-form text containing:
- **Time range**: "last 2 weeks", "since v2.0", "50 commits" (default: 30 days)
- **Focus areas**: "focus on the API layer", "new auth module needs attention"

Examples:
```
/refresh-agents-md
/refresh-agents-md last 3 months, focus on the new plugin system
/refresh-agents-md since last release
```

## Design Decisions

- **CLAUDE.md and AGENTS.md treated as a pair**: CLAUDE.md is the entry point (often a pointer), AGENTS.md holds real instructions. Both updated per their role.
- **Smart discovery with confirmation**: Uses heuristics (package boundaries, distinct architectural zones) to suggest new file locations. Confirms before creating.
- **Full refresh with git context**: Always refreshes all files, but uses git history to understand recent evolution and prioritize attention.
- **Skip scope questions**: Infers everything from codebase exploration and git history. Only user input is `$ARGUMENTS`.

## Architecture: Two-Phase Process

### Phase 1: Parallel Discovery

Three parallel subagents gather context simultaneously:

1. **Git Analyzer**: Parse time range from `$ARGUMENTS` (default 30 days). Run git log to identify:
   - New/renamed/deleted directories
   - Dependency changes (package.json, requirements.txt, etc.)
   - Config file changes (tsconfig, webpack, etc.)
   - New patterns or conventions from recent commits

2. **File Inventory**: Find all existing CLAUDE.md and AGENTS.md files in project tree

3. **Directory Discovery**: Identify directories that should have AGENTS.md:
   - Package boundaries (package.json, go.mod, Cargo.toml, pyproject.toml)
   - Distinct architectural zones (apps/*, packages/*, src/backend vs src/frontend, services/*)
   - Directories with own test suites or build configs

### Phase 2: Present Map & Confirm

Present a summary before any changes:
- Git context summary (commits, key changes)
- Files to update (existing files with line counts)
- Suggested new files (with rationale)

User approves, removes locations, or adds more.

### Phase 3: Sequential Updates (Root First)

Process in hierarchy order so children reference updated parents:

For each location:
1. Read existing file (or note it's new)
2. Read codebase in that directory — key files, structure, conventions
3. Read parent AGENTS.md for hierarchy context
4. Apply optimize-agents-md skill principles:
   - Verify freshness against current project state
   - Eliminate generic/redundant/stale content
   - Transform weak directives to strong
   - Ensure hierarchy respected (no parent duplication)
   - Keep under 200 lines
5. For CLAUDE.md: ensure it correctly points to AGENTS.md
6. Present diff to user for approval before writing

After all files processed, offer to commit changes.

## Skill Invocation

The command invokes the `optimize-agents-md` skill for guidance on optimization principles, but operates autonomously (no 5 scope questions). The skill's validation checklist is used as final quality gate for each file.

## File Location

`src/user/.claude/commands/refresh-agents-md.md`
