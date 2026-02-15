# Refresh AGENTS.md

Refresh all CLAUDE.md and AGENTS.md files across the project. Uses git history as context and the `optimize-agents-md` skill principles for quality.

`$ARGUMENTS` contains optional guidance:
- **Time range**: "last 2 weeks", "since v2.0", "50 commits" (default: 30 days)
- **Focus areas**: "focus on the API layer", "new auth module needs attention"

If `$ARGUMENTS` is empty, use defaults (30 days, no specific focus).

## Step 0 — Parse Input

Extract from `$ARGUMENTS`:
1. **Time range** — any phrase indicating how far back to look in git history. Convert to a `git log --since` compatible value. Default: `--since="30 days ago"`.
2. **Focus areas** — any remaining text describing what to pay special attention to. Store as context for Phase 3.

## Step 1 — Parallel Discovery

Invoke the `dispatching-parallel-agents` skill to run these three tasks simultaneously:

### Subagent 1: Git Analyzer

Run `git log --since="<time range>" --stat --name-status` and analyze the output. Summarize:
- New, renamed, or deleted directories
- Dependency file changes (package.json, requirements.txt, go.mod, Cargo.toml, pyproject.toml, etc.)
- Config file changes (tsconfig.json, webpack.config.*, vite.config.*, etc.)
- New patterns or conventions visible in recent commits
- Total commit count and most active areas

### Subagent 2: File Inventory

Find all existing CLAUDE.md and AGENTS.md files in the project tree. For each, report:
- Full path
- Line count
- Whether it's a pointer file (just references another file) or has real content

### Subagent 3: Directory Discovery

Identify directories that **should** have their own AGENTS.md but don't. Check for:
- **Package boundaries**: directories containing package.json, go.mod, Cargo.toml, pyproject.toml, setup.py, pom.xml
- **Architectural zones**: apps/*, packages/*, services/*, src/backend, src/frontend, src/shared, lib/*
- **Independent concerns**: directories with their own test suite, build config, or CI config

For each candidate, note the rationale (e.g. "has package.json", "distinct architectural zone").

Exclude: node_modules, vendor, .git, dist, build, coverage, __pycache__, .next, .nuxt

## Step 2 — Present Refresh Map

Combine all discovery results into a summary and present it to the user:

```
## Refresh Plan

### Git Context (<time range>)
- <N> commits, <key changes summary>
- Focus areas: <from $ARGUMENTS or "none specified">

### Files to Update
- ./CLAUDE.md (<N> lines, <pointer|content>)
- ./AGENTS.md (<N> lines)
- ...

### Suggested New Files
- ./packages/worker/ — <rationale>
- ...
  (or "None — all relevant directories already have files")
```

If no files exist at all (bootstrapping a new project), always include the project root as a suggested location.

Ask the user to confirm, remove locations, or add more. **Do not proceed until the user approves.**

If the user removes suggested new files, respect that. If they add directories, include them.

## Step 3 — Sequential Updates

Process files in **hierarchy order** (shallowest path depth first, so root is always first). This ensures child files can reference updated parent content.

For each approved location:

### 3a. Gather Context

1. Read the existing CLAUDE.md and AGENTS.md at this location (if they exist)
2. Read the parent directory's AGENTS.md (if any) to understand what's already covered at a higher level
3. Explore the codebase at this directory level:
   - Key source files, directory structure, config files
   - Test setup, build commands, linting config
   - README or other docs
4. Cross-reference with git analysis: what changed recently in this area?

### 3b. Update AGENTS.md

Apply the `optimize-agents-md` skill principles — but **skip the 5 scope questions** (infer from codebase):

- **Verify freshness**: Does the file reflect the current project state? Flag stale content.
- **Eliminate**: Remove generic AI advice, vague imperatives, parent duplication, stale file paths, anything Claude would do without being told.
- **Transform**: Convert weak directives ("try to keep functions small") to strong ones ("Functions >50 lines require justification comment").
- **Hierarchy**: Only include content unique to this level. Don't repeat parent rules.
- **Progressive disclosure**: Move heavy reference content to linked files if appropriate.
- **Structure**: Use bullet points, tables, sentence fragments. No filler words. Target <200 lines.

If the file doesn't exist yet (suggested new file), draft it from scratch based on codebase exploration.

If focus areas from `$ARGUMENTS` are relevant to this directory, give them extra attention.

### 3c. Update CLAUDE.md

Ensure CLAUDE.md at this location correctly points to AGENTS.md. The standard pattern:

```markdown
# CLAUDE.md

Refer to the @AGENTS.md file in the same directory.
```

If CLAUDE.md has additional content beyond a pointer, evaluate whether that content belongs in AGENTS.md instead and consolidate.

### 3d. Validate

Run the optimize-agents-md validation checklist against the updated file:
- No generic AI advice
- No vague imperatives — all rules measurable or falsifiable
- No parent duplication
- No child overlap
- Every directive has concrete action or threshold
- File paths are exact, not illustrative
- Under 200 lines
- Every line passes: "Would removing this cause Claude to make mistakes?"

### 3e. Present Diff

Show the user a before/after comparison:
- What was removed and why
- What was added and why
- What was transformed (weak to strong)
- Line count: original vs updated

**Wait for user approval before writing the file.** If the user requests changes, revise and re-present.

Move to the next location only after the current one is approved and written.

## Step 4 — Commit

After all files are updated, present a summary of all changes and offer to commit:

```
All files refreshed:
- ./CLAUDE.md (updated)
- ./AGENTS.md (142 → 118 lines)
- ./packages/api/AGENTS.md (created, 45 lines)
- ...

Commit these changes?
```

If yes, stage all changed/created CLAUDE.md and AGENTS.md files and commit with message:
`docs: refresh AGENTS.md files across project`
