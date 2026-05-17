# wait-for-pr-comments — Design Spec

> **Historical — superseded by `docs/specs/2026-04-26-pr-review-skill-redesign.md`.** This document describes an earlier design for `wait-for-pr-comments`. The skill's current behavior is governed by the redesign spec at the path above.

**Date:** 2026-03-22
**Status:** Approved

## Purpose

A skill that monitors a GitHub PR for review comments, automatically fixes unambiguous feedback, and reports results to the user. Supports both manual invocation and automatic triggering via a PostToolUse hook.

## Requirements

1. **Manual invocation**: `/wait-for-pr-comments [interval] [max-duration]` with defaults `1m` and `7m`
2. **Auto-trigger**: PostToolUse hook detects `gh pr create` output or `git push` to a PR branch, injects context suggesting skill invocation
3. **Polling**: Uses `CronCreate` for recurring checks; `CronDelete` for cancellation
4. **Comment detection**: Fetches PR review comments via `gh api`, compares against baseline count at skill start to detect new comments only
5. **Auto-fix**: Claude triages new comments using its own judgment — fixes unambiguous issues, skips anything requiring human decision
6. **Single re-poll**: After fixing and pushing, one more polling round (same interval/duration), then always hand back to user. New comments found during re-poll are **reported but not auto-fixed**.
7. **Report**: Clear, structured report showing what was fixed, what was skipped (and why), and what action the user should take

## Deliverables

### Files

```
src/user/.agents/skills/wait-for-pr-comments/
├── SKILL.md                  # Main skill definition
└── detect-pr-push.sh         # PostToolUse hook script (Claude-specific, inert in other tools)

src/user/.claude/settings.json.template   # Updated: PostToolUse hook entry added
```

Both files live in the shared `.agents/skills/` directory to avoid an install collision: the `install.sh` `sync_directory` function replaces entire directories on hash mismatch, so splitting files between `.agents/skills/` (Phase 2) and `.claude/skills/` (Phase 5) would cause Phase 5 to clobber Phase 2's SKILL.md. Keeping them together means a single copy in Phase 2 with no Phase 5 conflict. The hook script is inert in non-Claude environments (Codex/Gemini copy it but never reference it).

### SKILL.md Frontmatter

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

### SKILL.md Body Outline

```
# wait-for-pr-comments
Core principle one-liner

## When to Use / When NOT to Use
Decision tree for invocation

## Arguments
Parsing rules, defaults, examples

## The Process
Phase-by-phase methodology (mirrors lifecycle below)

## Report Templates
The three report variants

## Error Handling
What to do when things go wrong

## Hook Auto-Trigger
How the PostToolUse hook works, how to install it

## Quick Reference
Table of situations → actions

## Red Flags
Rationalizations to watch for
```

## Lifecycle

### State Machine

```
INVOKE → DETECT_PR → SETUP_CRON → POLL_LOOP → [COMMENTS_FOUND | MAX_REACHED]

If MAX_REACHED (no comments):
  → CANCEL_CRON → REPORT_CLEAN → DONE

If COMMENTS_FOUND:
  → CANCEL_CRON → TRIAGE → FIX → PUSH → REPOLL_SETUP → REPOLL_LOOP
  → [REPOLL_COMMENTS_FOUND | REPOLL_MAX_REACHED]
  → CANCEL_CRON → FINAL_REPORT → DONE

If ERROR at any phase:
  → CANCEL_CRON (if active) → REPORT_ERROR → DONE
```

### Phase 1: Invocation & PR Detection

The skill determines the PR number from:
1. Explicit argument (PR number or URL)
2. Current branch → `gh pr view --json number,title,url`
3. Hook-injected context — the hook outputs a message in the format:
   `PR activity detected: #<number> (<url>). Run /wait-for-pr-comments to monitor for review comments.`
   The skill extracts the PR number via pattern match.

If no PR can be detected, report an error and stop.

### Phase 2: Initial Polling

1. Record baseline: current review comment count via `gh api repos/{owner}/{repo}/pulls/{number}/comments` (this captures inline code review comments, not just top-level PR comments)
2. Convert the interval parameter to a cron expression:
   - `1m` → `*/1 * * * *`
   - `2m` → `*/2 * * * *`
   - Sub-minute intervals are not supported (cron minimum granularity is 1 minute)
3. Calculate max iterations: `ceil(max-duration / interval)` — e.g., `7m / 1m = 7 iterations`
4. Create a recurring cron job via `CronCreate` with a self-contained prompt:
   ```
   PR comment check for #<number>.
   Started: <ISO-8601 start timestamp>. Interval: <N>m. Max duration: <M>m.
   Baseline: <count> review comments.

   Step 1: Calculate current iteration from elapsed time:
     iteration = floor((now - start_time) / interval) + 1
     max_iterations = ceil(max_duration / interval)

   Step 2: Run: gh api repos/{owner}/{repo}/pulls/{number}/comments --jq 'length'

   Step 3: If count > baseline: new comments found.
     Look up this job's ID via CronList, cancel it with CronDelete,
     fetch the new comments, and invoke the wait-for-pr-comments triage process.

   Step 4: If count == baseline and iteration >= max_iterations:
     Look up this job's ID via CronList, cancel it with CronDelete,
     and report no comments found — PR is ready to merge.

   Step 5: If count == baseline and iteration < max_iterations:
     Do nothing — wait for next cron fire.
   ```

   **Iteration tracking:** Cron fires are stateless — each fire calculates its iteration number from elapsed wall-clock time since the start timestamp encoded in the prompt. No mutable state needed between fires.

   **Job self-cancellation:** The prompt instructs Claude to call `CronList` to find the job ID, then `CronDelete` to cancel it. This avoids the chicken-and-egg problem of needing the job ID before the job exists.
5. CronCreate jobs only fire while the REPL is idle (not mid-query). This is expected — the skill returns control between polls.
6. CronCreate jobs auto-expire after 7 days; our max-duration is far shorter, so this is a non-issue.

### Phase 3: Triage & Fix

1. Fetch all new comments via `gh api repos/{owner}/{repo}/pulls/{number}/comments`
2. Filter to comments created after baseline timestamp
3. For each comment, Claude assesses: can this be fixed unambiguously?
4. Fix what can be fixed, note what was skipped and why
5. Commit and push fixes
6. Proceed to Phase 4

**Error handling:**
- If commit fails (pre-commit hook, merge conflict): report error with details, skip push, proceed to final report
- If `git push` fails (auth, remote rejection): report error, include the local commit SHA so user can push manually
- If the PR was closed or merged during polling: detect via `gh pr view --json state`, report and stop

### Phase 4: Re-poll (single round)

1. Create a new cron job with the same interval/duration
2. Record new baseline (post-fix comment count)
3. Poll for additional comments from the same or new reviewers
4. If new comments arrive during re-poll: they are **reported but not auto-fixed** (prevents recursive fix loops). They appear in the final report under a "New during re-poll" section.
5. When re-poll completes (new comments reported or max reached) → cancel cron, proceed to Phase 5

### Phase 5: Final Report

Always deliver a structured report to the user. Three variants:

**Variant 1 — Clean pass (no comments):**
```markdown
## PR Comment Watch Complete

**PR:** #<number> — "<title>"
**Monitored:** <N> polls over <duration>
**Result:** No review comments received

Ready to merge.
```

**Variant 2 — All fixed, re-poll clean:**
```markdown
## PR Comment Watch Complete

**PR:** #<number> — "<title>"

### Fixed (<count>)
- **@<author>** (<location>): "<comment summary>" → <what was done>

### Status
- Fixes pushed in commit `<sha>`
- Re-poll: No new comments after <duration>

All review feedback addressed. Ready to merge.
```

**Variant 3 — Items need attention:**
```markdown
## PR Comment Watch Complete

**PR:** #<number> — "<title>"

### Fixed (<count>)
- **@<author>** (<location>): "<comment summary>" → <what was done>

### Skipped (<count>)
- **@<author>** (<location>): "<comment summary>" → <reason skipped>

### New During Re-poll (<count>)
- **@<author>** (<location>): "<comment summary>"

### Status
- Fixes pushed in commit `<sha>`
- Re-poll: <status>

What would you like to do about the remaining items?
```

## Hook Design

### detect-pr-push.sh

A PostToolUse hook script that:

1. Reads hook input from stdin (JSON with tool name, input, output)
2. Checks if the tool was `Bash` and the command/output matches:
   - `gh pr create` with a PR URL in stdout → extract PR number from URL
   - `git push` where the current branch has an open PR → run `gh pr view --json number` to get PR number
3. If matched: outputs context message:
   `PR activity detected: #<number> (<url>). Run /wait-for-pr-comments to monitor for review comments.`
4. If not matched: exits silently (no output = no injection)

### settings.json.template Hook Entry

```json
{
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
}
```

The union-merge in `install.sh` adds this alongside any existing hooks.

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| interval | `1m` | Time between polls (minimum 1m, cron granularity) |
| max-duration | `7m` | Total polling window per round |

Positional: `/wait-for-pr-comments [interval] [max-duration]`

**Iteration count:** `ceil(max-duration / interval)`. Wall-clock duration is approximate due to cron jitter (up to 10% of interval).

**Interval to cron conversion:**

| Interval | Cron Expression |
|----------|----------------|
| `1m` | `*/1 * * * *` |
| `2m` | `*/2 * * * *` |
| `5m` | `*/5 * * * *` |

Sub-minute intervals are not supported.

## Polling Mechanism

- **Primary**: `CronCreate`/`CronDelete` for precise lifecycle control with self-contained prompts
- **Manual alternative**: Users can run `/loop 1m "check PR #N for comments"` for ad-hoc lightweight monitoring without the full triage/fix workflow. This is not part of the skill — just a documented tip for users who want simpler behavior.

## Constraints

- Sonnet model — polling and comment triage don't need opus
- Single re-poll after fixes — no recursive loops; re-poll comments are reported, not fixed
- Hook suggests invocation, doesn't force it — user retains control
- Comment detection uses `gh api` for inline review comments (not just `gh pr view` which misses code-level feedback)
- Count-based baseline is simple and sufficient; edited/deleted comments are an accepted limitation
- Both SKILL.md and detect-pr-push.sh live in shared `.agents/skills/` to avoid install clobber; hook script is inert in non-Claude environments

## Out of Scope

- Multi-PR monitoring (one PR per invocation)
- Resolving GitHub review threads programmatically
- Integration with CI/CD status checks
- Slack/Discord notifications
- Detecting edited or deleted comments (count-based baseline limitation)
