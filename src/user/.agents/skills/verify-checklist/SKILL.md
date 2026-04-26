---
name: verify-checklist
description: Use when about to declare work complete or report final status to the user, or when user invokes directly — audits all completed work against verification workflows stored in memory and produces a structured completion report
context: fork
agent: bead-verifier
---

# Verify Checklist

## Core Principle

**Completion without audit is assumption.** Cross-reference every piece of work against the verification workflows in your memory before declaring done. If steps were skipped, do them now. Then produce a structured report with evidence.

## When to Use

- You're about to tell the user work is complete ("I've finished...", "That's all done", "Everything passes")
- User invokes this skill directly
- You've finished a non-trivial task and are preparing final status

## When NOT to Use

- Mid-task progress updates (final status only)
- Trivial one-liners (config tweaks, typo fixes)
- User explicitly says to skip verification

## The Process

### 1. Load Verification Workflows

Locate verification workflow definitions from your memory. These describe the steps required before work can be declared complete.

**Check in order:**
1. **Shared rules** — look for `<verification-checklist>` in instruction files (always loaded)
2. **Tool extensions** — `<completion-gate>` and `<delivery>` for tool-specific implementation
3. **Project config** — project-level overrides or additions (AGENTS.md, CLAUDE.md, etc.)
4. **Memory files** — any supplemental verification workflows

**If no verification workflows found anywhere:**

STOP. Tell the user:

> "No verification workflows found in memory or instruction files. I recommend adding verification workflow memories at the user and/or project level so future work can be audited. Would you like help creating these?"

Then proceed with best-effort verification using whatever project conventions you can infer. Do not silently skip.

### 2. Audit

For **each** verification workflow step:

1. **Check**: Did you complete this step during this session? What evidence exists?
2. **If completed**: Record the result (test output, review findings, commit SHAs)
3. **If NOT completed**: **Execute it now.** Do not merely report it missing — do the work, then record the result.
4. **If blocked**: Record why and flag for the user

Do not skip steps. Do not reorder steps. Do not decide steps "don't apply."

### 3. Gather Context

Collect before writing the report:

- **Task objective** — What were you asked to do? One sentence.
- **PRs** — Branch names, PR URLs/numbers, current status
- **Remaining work** — Anything incomplete if this was a partial delivery
- **Discovered work** — Issues found but not addressed during implementation
- **Where recorded** — Bead IDs, issue numbers, memory entries for each discovered item

If discovered work is unrecorded, **record it now** (create beads, issues, or memory entries as appropriate for the project). Unrecorded work is lost work.

### 4. Produce the Report

```markdown
## Completion Report

### Objective
[One-sentence description of the task]

### Pull Requests
| PR | Branch | Status |
|----|--------|--------|
| #N or URL | branch-name | open / merged / draft |

### Verification Checklist
| # | Step | Status | Notes |
|---|------|--------|-------|
| 1 | [step from workflows] | done | [evidence or result] |
| 2 | [step from workflows] | just completed | [what was done now] |
| 3 | [step from workflows] | blocked | [why] |
| 4 | [step from workflows] | n/a — user-approved skip | [reason] |

### Remaining Work
[What's still to do, or "None — all work complete"]

### Discovered Work
| Item | Recorded In |
|------|-------------|
| [description] | bead:ID / issue:#N / memory / backlog |
```

Omit sections that are genuinely empty (no PRs, no discovered work). But you must always include **Objective**, **Verification Checklist**, and **Remaining Work**.

## Source Dependency

The canonical checklist lives in `<verification-checklist>` in shared instructions — always loaded, always available. Tool extensions provide the "how" (which skills/agents implement each step). Project config and memory can add or override steps.

If `<verification-checklist>` is missing from your loaded instructions, warn the user — the shared instruction files may not be installed. Fall back to tool extensions and memory, but flag the gap.

## Red Flags — STOP

If any of these thoughts cross your mind, you're rationalizing:

| Thought | Reality |
|---------|---------|
| "I already verified everything" | Did you check memory for the full list? Audit again. |
| "The user didn't ask for a report" | The report IS the evidence. Produce it. |
| "These steps don't apply to this task" | Memory says they do. Follow them or justify in the report. |
| "I'll skip the discovered work section" | Unrecorded work is lost work. Record it now. |
| "No workflows in memory, so I'm clear" | Warn the user. Don't silently skip. |
| "This was trivial, no report needed" | If the skill was invoked, produce the report. No exceptions. |
| "I'll just say 'all checks passed'" | Itemize each step with evidence. Vague claims are not proof. |
| "I did most of the steps, close enough" | Most is not all. Execute the missing ones now. |
| "I'll produce the report later" | Now. The report is the last thing the user sees. |

## Quick Reference

| Phase | Action |
|-------|--------|
| **Load** | Re-read memory files for verification workflows |
| **Audit** | Check each step; execute anything missed |
| **Gather** | Task objective, PRs, remaining + discovered work |
| **Report** | Structured checklist with evidence per step |
| **No memory** | Warn user, suggest adding workflow memories, best-effort fallback |
