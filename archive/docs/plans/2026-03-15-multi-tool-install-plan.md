# Multi-Tool Install Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restructure source layout to separate shared vs tool-specific content and rewrite install.sh to deploy to Claude, Codex, and Gemini config directories.

**Architecture:** Shared content (skills, agents, instructions, personas) lives in `src/user/.agents/`. Tool-specific content (extensions, commands, settings) lives in `src/user/.<tool>/`. Install script auto-detects installed tools and copies shared + tool-specific content to each.

**Tech Stack:** Bash, jq (existing)

**Design doc:** `docs/plans/2026-03-15-multi-tool-install-design.md`

---

### Task 1: Create shared `.agents/` directory structure

**Files:**
- Create: `src/user/.agents/` directory
- Move: `src/user/.claude/AGENT-PERSONA.md.template` -> `src/user/.agents/AGENT-PERSONA.md.template`
- Move: `src/user/.claude/USER-PERSONA.md.template` -> `src/user/.agents/USER-PERSONA.md.template`
- Move: `src/user/.claude/agents/` -> `src/user/.agents/agents/`
- Move: `src/user/.claude/skills/` -> `src/user/.agents/skills/`

**Step 1: Create the .agents directory**

```bash
mkdir -p src/user/.agents
```

**Step 2: Move persona templates**

```bash
git mv src/user/.claude/AGENT-PERSONA.md.template src/user/.agents/AGENT-PERSONA.md.template
git mv src/user/.claude/USER-PERSONA.md.template src/user/.agents/USER-PERSONA.md.template
```

**Step 3: Move agents and skills directories**

```bash
git mv src/user/.claude/agents src/user/.agents/agents
git mv src/user/.claude/skills src/user/.agents/skills
```

**Step 4: Verify structure**

```bash
find src/user/.agents -type f | head -20
```

Expected: persona templates at top level, agents/*.md and skills/*/ underneath.

**Step 5: Commit**

```bash
git add -A && git commit -m "refactor: move shared content to src/user/.agents/"
```

---

### Task 2: Extract Claude-specific sections into CLAUDE-EXTENSIONS.md.template

**Files:**
- Create: `src/user/.claude/CLAUDE-EXTENSIONS.md.template`
- Modify: `src/user/.claude/AGENTS.md.template`

**Step 1: Create CLAUDE-EXTENSIONS.md.template**

Extract these sections from the current AGENTS.md.template into a new file:
- `<delegation>` (references Claude-specific skills by name)
- `<git_commits>` (Claude Code sandbox workaround)
- `<beads>` (Claude Code plugin)

The new file should contain just those three XML-wrapped sections, with a brief header comment explaining this is Claude-specific configuration.

**Step 2: Verify the extracted content matches the original**

Diff the sections to make sure nothing was lost or altered.

**Step 3: Commit**

```bash
git add src/user/.claude/CLAUDE-EXTENSIONS.md.template src/user/.claude/AGENTS.md.template
git commit -m "refactor: extract Claude-specific sections into CLAUDE-EXTENSIONS.md.template"
```

---

### Task 3: Create shared INSTRUCTIONS.md.template

**Files:**
- Create: `src/user/.agents/INSTRUCTIONS.md.template`
- Modify: `src/user/.claude/AGENTS.md.template` (replace inline sections with @-reference)

**Step 1: Create INSTRUCTIONS.md.template**

This file gets the tool-agnostic sections from the current AGENTS.md.template:
- `<laws>` section (L0-L3 priority system)
- `<constraints>` section (minimal edits, root causes, git safety, etc.)
- `<workflow>` section (TDD, semantic commits)
- `<orchestration>` section (plan first, subagents, tracer bullets, etc.)

**Step 2: Rewrite Claude's AGENTS.md.template**

Replace the inline sections with @-references:

```markdown
# AGENTS.md

User-scoped instructions for all projects.

<persona>
<!-- PRESERVE: user interaction preferences -->
Read the contents of @AGENT-PERSONA.md for agent personality.
Read the contents of @USER-PERSONA.md for user context.
</persona>

Read the contents of @INSTRUCTIONS.md for shared laws, constraints, workflow, and orchestration.
Read the contents of @CLAUDE-EXTENSIONS.md for Claude-specific configuration.
```

**Step 3: Verify all original content is accounted for**

Every section from the old AGENTS.md.template should exist in exactly one of:
- `INSTRUCTIONS.md.template` (shared)
- `CLAUDE-EXTENSIONS.md.template` (Claude-specific)
- `AGENTS.md.template` itself (the glue/references)

**Step 4: Commit**

```bash
git add src/user/.agents/INSTRUCTIONS.md.template src/user/.claude/AGENTS.md.template
git commit -m "refactor: create shared INSTRUCTIONS.md.template, update Claude AGENTS.md to use refs"
```

---

### Task 4: Create Codex source directory and templates

**Files:**
- Create: `src/user/.codex/AGENTS.md.template`
- Create: `src/user/.codex/CODEX-EXTENSIONS.md.template`

**Step 1: Create directory**

```bash
mkdir -p src/user/.codex
```

**Step 2: Create Codex AGENTS.md.template**

```markdown
# AGENTS.md

User-scoped instructions for all projects.

<persona>
Read the contents of @AGENT-PERSONA.md for agent personality.
Read the contents of @USER-PERSONA.md for user context.
</persona>

Read the contents of @INSTRUCTIONS.md for shared laws, constraints, workflow, and orchestration.
Read the contents of @CODEX-EXTENSIONS.md for Codex-specific configuration.
```

**Step 3: Create CODEX-EXTENSIONS.md.template**

```markdown
# Codex-Specific Extensions

<!-- Add Codex-specific workflow sections here as needed -->
```

**Step 4: Commit**

```bash
git add src/user/.codex/
git commit -m "feat: add Codex source directory with instruction templates"
```

---

### Task 5: Create Gemini source directory and templates

**Files:**
- Create: `src/user/.gemini/GEMINI.md.template`
- Create: `src/user/.gemini/GEMINI-EXTENSIONS.md.template`

**Step 1: Create directory**

```bash
mkdir -p src/user/.gemini
```

**Step 2: Create Gemini GEMINI.md.template**

Same structure as Codex but filename is GEMINI.md and references GEMINI-EXTENSIONS.md.

**Step 3: Create GEMINI-EXTENSIONS.md.template**

```markdown
# Gemini-Specific Extensions

<!-- Add Gemini-specific workflow sections here as needed -->
```

**Step 4: Commit**

```bash
git add src/user/.gemini/
git commit -m "feat: add Gemini source directory with instruction templates"
```

---

### Task 6: Rewrite install.sh for multi-tool support

**Files:**
- Modify: `scripts/install.sh`

This is the largest task. The script needs to:

**Step 1: Update header comment and add --tools flag**

- Update the description to mention multi-tool support
- Add `--tools=claude,codex,gemini` flag parsing (comma-separated)
- Keep `--dry-run`, `--yes`, `--help` as-is

**Step 2: Add tool detection logic**

```bash
SHARED_SRC="$PROJECT_ROOT/src/user/.agents"

# Tool registry: name, dest_dir, src_dir
declare -A TOOL_DEST TOOL_SRC
TOOL_DEST[claude]="$HOME/.claude"   TOOL_SRC[claude]="$PROJECT_ROOT/src/user/.claude"
TOOL_DEST[codex]="$HOME/.codex"     TOOL_SRC[codex]="$PROJECT_ROOT/src/user/.codex"
TOOL_DEST[gemini]="$HOME/.gemini"   TOOL_SRC[gemini]="$PROJECT_ROOT/src/user/.gemini"

# Auto-detect or use --tools override
# claude always included; codex/gemini only if ~/.codex or ~/.gemini exist
```

**Step 3: Refactor sync logic into reusable functions**

The existing `sync_directory` and template-sync logic are already well-factored. Wrap them to accept a source dir and dest dir as parameters instead of using globals.

Existing functions to keep as-is: `backup()`, `compute_hash()`, `confirm()`, color helpers.

New function structure:
- `sync_templates "$src_dir" "$dest_dir" "$tool_name"` — handles `*.md.template` and `*.json.template`
- `sync_directory "$dir_name" "$src_dir" "$dest_dir"` — modified to accept src/dest params
- `merge_settings_json "$template" "$dest"` — extracted from inline settings logic
- `install_tool "$tool_name"` — orchestrates all phases for one tool

**Step 4: Implement per-tool install loop**

For each detected tool:
1. Copy shared templates from `.agents/` to `~/.<tool>/`
2. Sync shared skills from `.agents/skills/` to `~/.<tool>/skills/`
3. Sync shared agents from `.agents/agents/` to `~/.<tool>/agents/`
4. Copy tool-specific templates from `.<tool>/` to `~/.<tool>/`
5. Sync tool-specific subdirs (commands, etc.) from `.<tool>/` to `~/.<tool>/`
6. Merge settings (JSON for claude/gemini, skip TOML for codex for now)

**Step 5: Update summary output**

Show per-tool counts:
```
── Summary ──
  claude:  3 installed, 1 updated, 1 merged, 0 skipped
  codex:   5 installed, 0 updated, 0 merged, 0 skipped
  gemini:  (not detected, skipped)
```

**Step 6: Verify with --dry-run**

```bash
./scripts/install.sh --dry-run
```

Expected: shows operations for claude (always), codex (if ~/.codex exists), gemini (if ~/.gemini exists). Shared content appears for each detected tool.

**Step 7: Commit**

```bash
git add scripts/install.sh
git commit -m "feat: rewrite install.sh for multi-tool support (Claude, Codex, Gemini)"
```

---

### Task 7: Update project AGENTS.md documentation

**Files:**
- Modify: `AGENTS.md` (project root)

**Step 1: Update Repository Structure section**

Reflect the new `src/user/.agents/`, `src/user/.codex/`, `src/user/.gemini/` directories and their purposes.

**Step 2: Update install.sh description**

Mention multi-tool support, auto-detection, and --tools flag.

**Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs: update AGENTS.md for multi-tool source layout"
```

---

### Task 8: End-to-end verification

**Step 1: Run install with --dry-run**

```bash
./scripts/install.sh --dry-run
```

Verify: shared content listed for all detected tools, tool-specific content only for its tool.

**Step 2: Run install with --dry-run --tools=claude**

Verify: only Claude operations shown.

**Step 3: Run actual install for Claude**

```bash
./scripts/install.sh --tools=claude --yes
```

Verify: `~/.claude/` has INSTRUCTIONS.md, AGENT-PERSONA.md, USER-PERSONA.md, CLAUDE-EXTENSIONS.md, plus agents/, skills/, commands/, AGENTS.md, CLAUDE.md, settings.json.

**Step 4: Spot-check a Codex install (if ~/.codex exists)**

```bash
./scripts/install.sh --tools=codex --dry-run
```

Verify: shared skills/agents/templates listed, AGENTS.md and CODEX-EXTENSIONS.md listed.

**Step 5: Commit any fixes discovered during verification**
