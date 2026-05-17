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

---

# Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a single command file that instructs Claude to refresh all CLAUDE.md/AGENTS.md files across a project.

**Architecture:** A markdown command file following existing patterns (implement-bead.md, optimize-my-agent.md). The command orchestrates three phases: parallel discovery, map confirmation, and sequential updates.

**Tech Stack:** Markdown (Claude Code command format)

---

### Task 1: Write the command file

**Files:**
- Create: `src/user/.claude/commands/refresh-agents-md.md`

**Step 1: Draft the complete command file**

Write `src/user/.claude/commands/refresh-agents-md.md` with these sections, following the structure of `implement-bead.md` as a pattern:

1. **Title and purpose** — one-line description of what the command does
2. **Step 0 — Parse Input** — extract time range and focus areas from `$ARGUMENTS`, with defaults
3. **Step 1 — Parallel Discovery** — dispatch 3 parallel subagents (git analyzer, file inventory, directory discovery) using `dispatching-parallel-agents` skill
4. **Step 2 — Present Refresh Map** — format and present the discovery results, get user approval
5. **Step 3 — Sequential Updates** — root-first processing, invoke `optimize-agents-md` skill principles (skip scope questions), present diffs for approval
6. **Step 4 — Commit** — offer to commit all changes

Key details to include:
- `$ARGUMENTS` parsing: time range defaults to 30 days, focus areas are optional free text
- Git analysis: `git log --since` with `--stat`, `--name-status` for structural changes
- File inventory: glob for `**/CLAUDE.md` and `**/AGENTS.md`
- Directory discovery heuristics: package manifests, architectural zones, distinct test/build configs
- Confirmation gate between discovery and updates
- Hierarchy ordering: sort by path depth, process shallowest first
- For each file: read context, apply optimize-agents-md validation checklist, present diff before writing
- CLAUDE.md role: ensure it points to AGENTS.md (typically just `Refer to the @AGENTS.md file in the same directory.`)
- AGENTS.md role: the real content — apply full optimization principles
- Under 200 lines per file target from optimize-agents-md skill

**Step 2: Review against existing commands**

Compare the draft against `implement-bead.md` and `optimize-my-agent.md` for:
- Consistent tone and structure
- Proper use of `$ARGUMENTS`
- Appropriate skill references (use `@skill-name` syntax where referencing skills)
- Clear stop-and-ask-user gates

**Step 3: Commit**

```
git add src/user/.claude/commands/refresh-agents-md.md
git commit -m "feat: add refresh-agents-md command"
```
