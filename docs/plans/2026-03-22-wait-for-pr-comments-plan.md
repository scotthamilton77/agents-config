# wait-for-pr-comments Implementation Plan

> **Historical — superseded by `docs/specs/2026-04-26-pr-review-skill-redesign.md`.** This plan implemented the original `wait-for-pr-comments` skill; the skill has since been redesigned (binary FIX/SKIP/ESCALATE classification, default-on chain to `reply-and-resolve-pr-threads`, etc.). The current behavior is governed by the redesign spec at the path above.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a skill that monitors GitHub PRs for review comments, auto-fixes unambiguous feedback, and reports results — with both manual invocation and automatic hook-based triggering.

**Architecture:** Three deliverables in two locations: a shared SKILL.md + hook script (both in `.agents/skills/` to avoid install clobber), and a settings.json.template update (hook wiring). The skill uses CronCreate/CronDelete for polling lifecycle and `gh api` for comment detection.

**Tech Stack:** Bash (hook script), Markdown (skill definition), JSON (settings template), GitHub CLI (`gh`)

**Spec:** `docs/specs/2026-03-22-wait-for-pr-comments-design.md`

---

### Task 1: Create the SKILL.md skill file

**Files:**
- Create: `src/user/.agents/skills/wait-for-pr-comments/SKILL.md`

Reference existing skills for formatting conventions:
- `src/user/.agents/skills/bugfix/SKILL.md` (decision trees, red flags pattern)
- `src/user/.agents/skills/condition-based-waiting/SKILL.md` (polling-related skill)
- `src/user/.agents/skills/ralf-it/SKILL.md` (complex lifecycle, subagent dispatch)

- [ ] **Step 1: Create skill directory**

```bash
mkdir -p src/user/.agents/skills/wait-for-pr-comments
```

- [ ] **Step 2: Write SKILL.md frontmatter and core sections**

Create `src/user/.agents/skills/wait-for-pr-comments/SKILL.md` with frontmatter and sections 1-4:

```yaml
---
name: wait-for-pr-comments
model: sonnet
argument-hint: "[interval] [max-duration] (defaults: 1m 7m)"
description: >
  Use after creating or updating a PR to poll for review comments,
  auto-fix unambiguous feedback, and report results. Auto-triggered
  via PostToolUse hook on gh pr create and git push, or invoke manually.
---
```

Sections to write in this step:
1. **Title & core principle** — "Monitor a PR for review comments, fix what you can, report the rest."
2. **When to Use** — Graphviz decision tree: PR just created/updated? → yes → use this skill. Already monitoring? → no. PR merged/closed? → no.
3. **When NOT to Use** — Draft PRs (unless user says so), PRs with no reviewers assigned, when user explicitly wants to handle comments manually.
4. **Arguments** — Parsing rules: first positional = interval (default `1m`, regex `^\d+m$`), second positional = max-duration (default `7m`, same format). Sub-minute not supported. Examples: `/wait-for-pr-comments`, `/wait-for-pr-comments 2m 15m`, `/wait-for-pr-comments 5m 30m`.

- [ ] **Step 3: Write SKILL.md process and report sections**

Add sections 5-6 to the SKILL.md:

5. **The Process** — Five phases from spec:
   - Phase 1: PR Detection (from args, branch, or hook context)
   - Phase 2: Initial Polling (CronCreate with self-contained prompt, time-based iteration tracking, CronList/CronDelete for self-cancellation, interval-to-cron conversion table)
   - Phase 3: Triage & Fix (fetch new comments via `gh api`, assess each, fix unambiguous, commit & push)
   - Phase 4: Re-poll (single round, same params, new comments reported not fixed)
   - Phase 5: Final Report (three variants from spec)
6. **Report Templates** — All three variants verbatim from spec (clean pass, all fixed + re-poll clean, items need attention)

- [ ] **Step 4: Write SKILL.md reference and safety sections**

Add sections 7-10 to the SKILL.md:

7. **Error Handling** — Commit failure, push failure, PR closed/merged during polling, `gh` auth issues
8. **Hook Auto-Trigger** — How the PostToolUse hook works, what the context injection looks like, where the script lives
9. **Quick Reference** — Table: situation → action (mirrors spec's lifecycle branches)
10. **Red Flags** — Rationalizations table

Keep the total skill under 200 lines to respect token budget constraints.

- [ ] **Step 5: Validate SKILL.md section coverage**

Verify all 8 required body sections from the spec outline exist:

```bash
grep -c '^## ' src/user/.agents/skills/wait-for-pr-comments/SKILL.md
```

Expected: At least 8 second-level headings. Also check for these specific headings:
- `## When to Use`
- `## Arguments`
- `## The Process`
- `## Report Templates`
- `## Error Handling`
- `## Hook Auto-Trigger`
- `## Quick Reference`
- `## Red Flags`

- [ ] **Step 6: Verify skill follows project conventions**

Check: frontmatter fields match existing skills, section structure is consistent, Graphviz decision tree uses same syntax as bugfix/SKILL.md.

```bash
head -10 src/user/.agents/skills/wait-for-pr-comments/SKILL.md
head -10 src/user/.agents/skills/bugfix/SKILL.md
```

Compare frontmatter structure.

- [ ] **Step 7: Commit**

```bash
git add src/user/.agents/skills/wait-for-pr-comments/SKILL.md
git commit -m "feat(skills): add wait-for-pr-comments skill"
```

---

### Task 2: Create the detect-pr-push.sh hook script

**Files:**
- Create: `src/user/.agents/skills/wait-for-pr-comments/detect-pr-push.sh`

**Note:** This file lives in the shared `.agents/skills/` directory alongside SKILL.md (not in `.claude/skills/`) to avoid an install clobber bug — `sync_directory` replaces entire directories on hash mismatch, so splitting files between Phase 2 and Phase 5 destinations would destroy SKILL.md. Non-Claude tools copy this script but never use it (harmless).

Reference the hook protocol from existing plugins:
- `/Users/scott/.claude/plugins/marketplaces/claude-plugins-official/plugins/ralph-loop/hooks/stop-hook.sh`
- `/Users/scott/.claude/plugins/marketplaces/claude-plugins-official/plugins/hookify/hooks/posttooluse.py`

Claude Code PostToolUse hooks receive JSON on stdin with the structure:
```json
{
  "tool_name": "Bash",
  "tool_input": { "command": "..." },
  "tool_output": { "stdout": "...", "stderr": "..." }
}
```

The hook outputs text to stdout for context injection, or nothing to remain silent.

- [ ] **Step 1: Write detect-pr-push.sh**

Create `src/user/.agents/skills/wait-for-pr-comments/detect-pr-push.sh`:

```bash
#!/usr/bin/env bash
# PostToolUse hook: detect PR creation or push, suggest /wait-for-pr-comments
# Reads JSON from stdin. Outputs context injection on match, nothing otherwise.
set -euo pipefail

# Read hook input
input="$(cat)"

# Extract tool name — only care about Bash
tool_name="$(echo "$input" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0
[[ "$tool_name" == "Bash" ]] || exit 0

# Extract command and stdout
command="$(echo "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
stdout="$(echo "$input" | jq -r '.tool_output.stdout // empty' 2>/dev/null)" || exit 0

# Pattern 1: gh pr create — look for PR URL in stdout
if [[ "$command" == *"gh pr create"* ]]; then
    pr_url="$(echo "$stdout" | grep -oE 'https://github\.com/[^/]+/[^/]+/pull/[0-9]+' | head -1)" || true
    if [[ -n "$pr_url" ]]; then
        pr_number="$(echo "$pr_url" | grep -oE '[0-9]+$')"
        echo "PR activity detected: #${pr_number} (${pr_url}). Run /wait-for-pr-comments to monitor for review comments."
        exit 0
    fi
fi

# Pattern 2: git push — check if branch has an open PR
if [[ "$command" == git\ push* ]]; then
    pr_json="$(gh pr view --json number,url,state 2>/dev/null)" || exit 0
    pr_state="$(echo "$pr_json" | jq -r '.state // empty')" || exit 0
    if [[ "$pr_state" == "OPEN" ]]; then
        pr_number="$(echo "$pr_json" | jq -r '.number')"
        pr_url="$(echo "$pr_json" | jq -r '.url')"
        echo "PR activity detected: #${pr_number} (${pr_url}). Run /wait-for-pr-comments to monitor for review comments."
    fi
fi

exit 0
```

- [ ] **Step 2: Make script executable**

```bash
chmod +x src/user/.agents/skills/wait-for-pr-comments/detect-pr-push.sh
```

- [ ] **Step 3: Verify script syntax**

```bash
bash -n src/user/.agents/skills/wait-for-pr-comments/detect-pr-push.sh
echo "Exit code: $?"
```

Expected: Exit code 0 (no syntax errors).

- [ ] **Step 4: Test with mock input (gh pr create match)**

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"gh pr create --title test"},"tool_output":{"stdout":"https://github.com/owner/repo/pull/42\n","stderr":""}}' | bash src/user/.agents/skills/wait-for-pr-comments/detect-pr-push.sh
```

Expected output: `PR activity detected: #42 (https://github.com/owner/repo/pull/42). Run /wait-for-pr-comments to monitor for review comments.`

- [ ] **Step 5: Test with mock input (no match)**

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"ls -la"},"tool_output":{"stdout":"total 0\n","stderr":""}}' | bash src/user/.agents/skills/wait-for-pr-comments/detect-pr-push.sh
```

Expected output: (empty — no match, no context injection)

- [ ] **Step 6: Test with mock input (git push — note limitation)**

The `git push` pattern (Pattern 2) calls `gh pr view` against the real GitHub API, so it cannot be fully mocked with stdin alone. Verify the pattern-matching logic is correct by testing with a non-push command that won't trigger the `gh pr view` call:

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"git push origin main"},"tool_output":{"stdout":"Everything up-to-date\n","stderr":""}}' | bash src/user/.agents/skills/wait-for-pr-comments/detect-pr-push.sh
```

Expected: Either a PR detection message (if current branch has an open PR) or empty output (if not). The `gh pr view` call will fail gracefully via `|| exit 0` if no PR exists.

- [ ] **Step 7: Commit**

```bash
git add src/user/.agents/skills/wait-for-pr-comments/detect-pr-push.sh
git commit -m "feat(hooks): add PostToolUse hook for PR comment monitoring"
```

---

### Task 3: Update settings.json.template with hook entry

**Files:**
- Modify: `src/user/.claude/settings.json.template`

- [ ] **Step 1: Read current settings.json.template**

```bash
cat src/user/.claude/settings.json.template
```

Verify current structure before modifying.

- [ ] **Step 2: Add hooks section**

Add the PostToolUse hook entry to the existing JSON as a new top-level key, alongside the existing `$schema`, `env`, and `permissions` keys. The `install.sh` union-merge will combine this with any existing user hooks:

```json
"hooks": {
  "PostToolUse": [
    {
      "matcher": "Bash",
      "hooks": [
        {
          "type": "command",
          "command": "~/.claude/skills/wait-for-pr-comments/detect-pr-push.sh",
          "timeout": 5
        }
      ]
    }
  ]
}
```

- [ ] **Step 3: Validate JSON syntax**

```bash
jq empty src/user/.claude/settings.json.template
echo "Exit code: $?"
```

Expected: Exit code 0 (valid JSON).

- [ ] **Step 4: Commit**

```bash
git add src/user/.claude/settings.json.template
git commit -m "feat(settings): add PostToolUse hook for wait-for-pr-comments"
```

---

### Task 4: Verify full install dry-run

**Files:**
- None (verification only)

- [ ] **Step 1: Run full install dry-run**

```bash
cd /Users/scott/src/projects/agents-config && bash scripts/install.sh --dry-run --tools=claude
```

Verify the output shows ALL THREE of these:
1. `skills/wait-for-pr-comments` being synced from shared `.agents/skills/` (includes both SKILL.md and detect-pr-push.sh)
2. `settings.json` merge proposed with hooks entry
3. No Phase 5 collision — `.claude/skills/wait-for-pr-comments/` should NOT appear as a separate sync item (since we moved the hook script to shared)

- [ ] **Step 2: Verify destination paths**

After install, the files should land at:
- `~/.claude/skills/wait-for-pr-comments/SKILL.md` — the skill definition
- `~/.claude/skills/wait-for-pr-comments/detect-pr-push.sh` — the hook script (path matches settings.json.template reference)
- `~/.claude/settings.json` — contains the merged hooks entry

Confirm these paths are consistent with the `command` path in the settings.json.template hook entry.

- [ ] **Step 3: Verify no stale Claude-specific skill directory exists**

```bash
ls src/user/.claude/skills/ 2>/dev/null || echo "No .claude/skills/ directory (correct)"
```

Expected: No `.claude/skills/wait-for-pr-comments/` directory exists (we moved everything to `.agents/skills/`).
