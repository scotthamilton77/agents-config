# RALF-IT Foreign Agent Integration Design

**Date:** 2026-03-15
**Status:** Approved
**Approach:** Integrated Foreign Iterations (Approach A)

## Summary

Enhance the RALF-IT skill to include foreign agent (Codex, Gemini) review passes in the first two iterations. Foreign agents produce review documents; Claude subagents evaluate and selectively apply recommendations. Later iterations (3+) use standard Claude-only fresh-eyes passes to conserve foreign agent token budgets.

## Motivation

Claude subagents, despite being dispatched fresh, share the same underlying cognitive architecture. Foreign agents (Codex, Gemini) introduce genuinely different reasoning patterns, catching blind spots that Claude-to-Claude iteration cannot. Using them sparingly in early iterations maximizes their impact while respecting token budget constraints.

## Modified RALF Loop

```
Steps 1-3: Unchanged (DoD alignment, iteration count, worktree)
Step 4:    Unchanged (initial implementation subagent)
Step 5:    Quality Gate (unchanged)
Step 6:    Iteration 1 — Foreign-Eyes subagent with CODEX as reviewer
Step 7:    Evaluate (same logic as before)
Step 8:    Quality Gate
Step 9:    Iteration 2 — Foreign-Eyes subagent with GEMINI as reviewer
Step 10:   Evaluate
Step 11+:  Quality Gate → standard Fresh-Eyes subagent (3-N, unchanged)
Final:     Final Review, Report (unchanged, adds foreign agent section)
```

### Iteration Assignment Rules

- `MAX_ITERATIONS == 1`: Only Codex gets a foreign-eyes pass
- `MAX_ITERATIONS == 2`: Codex then Gemini
- `MAX_ITERATIONS >= 3`: Codex, Gemini, then pure Claude for the rest
- Foreign agent failure → subagent degrades to pure fresh-eyes; iteration still counts

## `.ralf/` Directory Structure

```
.ralf/
├── .no-gitignore-prompt                    # marker: stop asking about .gitignore
└── {session_id}/
    ├── prompt-codex-{timestamp}.md         # instruction file for Codex
    ├── prompt-gemini-{timestamp}.md        # instruction file for Gemini
    ├── codex-review-{timestamp}.md         # Codex review output
    └── gemini-review-{timestamp}.md        # Gemini review output
```

- `{session_id}`: Main agent's session ID (prevents cross-session collisions)
- `{timestamp}`: `YYYYMMDD-HHmmss` format (prevents cross-run collisions within a session)
- No automatic cleanup; artifacts persist for debugging and visibility

### Gitignore Ceremony

Runs after worktree creation, before any foreign agent invocation:

1. Check if `.ralf` or `.ralf/` appears in `.gitignore`
2. If missing:
   a. Check for `.ralf/.no-gitignore-prompt` marker → if exists, skip silently
   b. Ask user: "Add `.ralf/` to `.gitignore`?"
   c. If yes → append to `.gitignore`
   d. If no → ask "Stop asking?" → if yes, create `.ralf/.no-gitignore-prompt`
3. If present → proceed silently

## Foreign-Eyes Subagent Architecture

New prompt template: `foreign-eyes-prompt.md`

### Subagent Workflow (5 phases)

```
Phase 1: Setup
  1. Read the original spec/DoD (NO prior context)
  2. Write foreign agent instruction file to .ralf/{session_id}/prompt-{agent}-{ts}.md
     (clean artifact from spec/DoD, before any implementation bias)

Phase 2: Fresh-Eyes Implementation
  3. Examine the current code state
  4. Assess completeness and quality against DoD
  5. Fix, complete, or improve whatever is necessary
  6. Run build + typecheck + lint + tests — all must pass
  7. Commit changes

Phase 3: Foreign Agent Consultation
  8. Invoke the foreign CLI (10min timeout, full-auto/non-interactive)
  9. Wait for completion
  10. Read the review file from .ralf/{session_id}/{agent}-review-{ts}.md

Phase 4: Evaluate & Apply Foreign Feedback
  11. Evaluate each foreign recommendation against spec/DoD
  12. Apply changes it agrees with, reject what it doesn't
  13. Run build + typecheck + lint + tests again
  14. Commit any additional changes

Phase 5: Report
  15. Standard fresh-eyes report PLUS foreign agent section
```

### Key Design Decision: Instruction File Written Before Implementation

The instruction file is written in Phase 1 from a pristine mental state (spec/DoD only). This prevents the subagent's own implementation decisions from contaminating what the foreign agent is told. The foreign agent reviews the code as it stands after Phase 2, but is instructed from the clean spec.

## Foreign Agent Instruction File Template

New prompt template: `foreign-agent-prompt.md`

```markdown
# Code Review Request

You are reviewing code in this repository as an external reviewer.

## CRITICAL INSTRUCTIONS
- Do NOT modify any source files — you are running in read-only mode
- Output your complete review to stdout (it will be captured automatically)

## Definition of Done
{DoD}

## Original Spec
{spec}

## Your Review Should Cover
1. Correctness: Does the implementation match the spec?
2. Bugs: Any logical errors, edge cases, or failure modes?
3. Quality: Code clarity, naming, structure, patterns?
4. Tests: Are tests meaningful and sufficient?
5. Missing: Anything the spec requires that isn't implemented?

## Review Format
For each finding, use:
### [SEVERITY: critical|major|minor|nit] — Short title
- **File:** path/to/file
- **Lines:** N-M (if applicable)
- **Issue:** What's wrong
- **Recommendation:** Specific fix or improvement

End with a summary: PASS / PASS_WITH_CONCERNS / NEEDS_WORK
```

## Failure Handling

All failures degrade gracefully to a standard fresh-eyes iteration.

| Failure Mode | Detection | Action |
|---|---|---|
| CLI not found | Exit code + "command not found" | Report unavailable, continue as pure fresh-eyes |
| Timeout (10min) | Bash timeout | Kill process, report timeout, continue as pure fresh-eyes |
| Token quota hit | Scan stderr/stdout for "quota", "rate limit", "exceeded", "429" | Report quota exhaustion, continue as pure fresh-eyes |
| No review file produced | File doesn't exist after CLI exits | Report no output, continue as pure fresh-eyes |
| Review file empty/garbage | File exists but unparseable | Report unparseable, continue as pure fresh-eyes |

## Report Template Changes

### New Section: Foreign Agent Participation

```markdown
### Foreign Agent Participation
- **Iteration 1 (Codex):** [COMPLETED/UNAVAILABLE/TIMED_OUT/QUOTA_EXCEEDED]
  - Findings: [N] ([accepted]/[rejected])
  - Notable: [most impactful accepted recommendation, if any]
- **Iteration 2 (Gemini):** [COMPLETED/UNAVAILABLE/TIMED_OUT/QUOTA_EXCEEDED]
  - Findings: [N] ([accepted]/[rejected])
  - Notable: [most impactful accepted recommendation, if any]
```

### Updated Iteration Summary

```markdown
- **Iteration 1 (+ Codex review):** [fresh-eyes findings] + [Codex findings]
- **Iteration 2 (+ Gemini review):** [fresh-eyes findings] + [Gemini findings]
- **Iteration 3+:** [standard fresh-eyes findings]
```

### New Section: Foreign Agent Artifacts

```markdown
### Foreign Agent Artifacts
Review files preserved at: .ralf/{session_id}/
```

## Red Flags (Additions)

**Never:**
- Write the foreign agent instruction file after doing implementation work (context contamination)
- Let a foreign agent modify source files directly (review document only)
- Trust foreign agent recommendations blindly (evaluate each against spec/DoD)
- Skip an iteration because the foreign agent failed (degrade to pure fresh-eyes)
- Expose iteration count to foreign agents (no bias)

**Always:**
- Write the instruction file from clean spec context before implementation
- Set a 10-minute timeout on foreign CLI invocation
- Check for token quota exhaustion patterns in CLI output
- Report foreign agent status even when it fails (visibility)
- Preserve all `.ralf/` artifacts for debugging

## New Files

| File | Purpose |
|---|---|
| `foreign-eyes-prompt.md` | Claude subagent template for iterations with foreign agent review |
| `foreign-agent-prompt.md` | Instruction file template written to `.ralf/` for foreign CLI consumption |

## Modified Files

| File | Changes |
|---|---|
| `SKILL.md` | Updated loop description, new foreign agent configuration section, updated report template, new red flags, CLI discovery notes |

## CLI Discovery (Verified)

### Codex
- **Non-interactive:** `codex exec` subcommand
- **Sandbox:** `-s read-only` (prevents all file writes — foreign agent cannot touch source)
- **Prompt input:** `-` flag reads prompt from stdin
- **Full invocation:** `codex exec -s read-only - < {prompt_file} > {review_file} 2>{error_file}`
- **Timeout:** Bash timeout at 600000ms (10 minutes)

### Gemini
- **Non-interactive:** `-p ""` flag triggers headless mode
- **Read-only:** `--approval-mode plan` (read-only mode, can read but not write)
- **Output format:** `-o text` for plain text output
- **Prompt input:** stdin is appended to `-p` prompt
- **Full invocation:** `gemini -p "" --approval-mode plan -o text < {prompt_file} > {review_file} 2>{error_file}`
- **Timeout:** Bash timeout at 600000ms (10 minutes)

### Common Pattern
Both CLIs: stdin prompt, read-only sandbox, stdout captured to review file, stderr captured separately for error detection. The Claude subagent checks stderr for quota/rate-limit patterns before reading the review file.
