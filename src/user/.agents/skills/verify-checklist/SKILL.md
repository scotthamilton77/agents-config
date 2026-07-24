---
name: verify-checklist
description: Use when about to declare work complete or report final status to the user, or when user invokes directly — audits all completed work against verification workflows stored in memory and produces a structured completion report
---

<!--
Source: oss-snapshots/superpowers/verification-before-completion/
Upstream: https://github.com/obra/superpowers @ f2cbfbefebbfef77321e4c9abc9e949826bea9d7 (v5.1.0)
Last sync: 2026-05-24
Drift policy: accept-periodic-resync (amalgamated lift — Iron Law framing + "evidence before claims, always" tagline + identify-run-read-verify-claim gate function only; tracked in agents-config-cx6.7.13)
-->

# Verify Checklist

## Core Principle

**The Iron Law: no completion claims without fresh verification evidence in this message.**

Claiming work is complete without verification is dishonesty, not efficiency. **Evidence before claims, always.** Completion without audit is assumption — cross-reference every piece of work against the verification workflows in your memory before declaring done. If steps were skipped, do them now. Then produce a structured report with evidence.

## When to Use

- You're about to tell the user work is complete ("I've finished...", "That's all done", "Everything passes")
- User invokes this skill directly
- You've finished a non-trivial task and are preparing final status

## When NOT to Use

- Mid-task progress updates (final status only)
- Trivial one-liners (config tweaks, typo fixes)
- User explicitly says to skip verification

## The Checklist

This is the canonical home of the 10-step checklist — shared instructions no
longer carry a `<verification-checklist>` block (zero-based per D17). The
`completion-gate` rule routes it at gate time to one of three depths: `SKIP`
(step 5 only), `SERIAL` (all ten, steps 1–4 run in-house), or `HEAVY` (steps
1–4 run as a multi-agent adversarial pass). Step 5 is non-substitutable under
every tier. Delivery and Housekeeping are not tiered — they always run.

**Quality gate:**
1. Code review — changes reviewed against plan, standards, and architectural intent
2. Address review findings — all findings resolved or explicitly deferred with rationale
3. Simplification review — changed code assessed for clarity, duplication, and maintainability
4. Address simplification findings — all findings resolved
5. Verify with evidence — tests pass, build succeeds, static analysis clean; output as proof

**Delivery:**
6. Work isolation — changes on a feature branch or worktree, not directly on trunk
7. Pull request — PR created with summary, linked to tracking if applicable
8. Automated review — automated reviewer feedback collected and triaged

**Housekeeping:**
9. Discovered work recorded and triaged — issues found during work are tracked, priority-rated with rationale, and anchored to the roadmap per the discovered-work discipline
10. Memory updated — non-obvious decisions, corrections, or context preserved

Tool-specific extensions define which skills, agents, or commands implement
each step — see the `completion-gate` rule for Claude's concrete `SERIAL` 1–5
tool mapping and delivery-chain wiring for 6–8. Project-level config may add
or override steps.

## The Process

### 1. Load Verification Workflows

Locate verification workflow definitions from your memory. These describe the steps required before work can be declared complete.

**Check in order:**
1. **This skill's checklist** (above) — the canonical 10-step definition, always available
2. **Tool extensions** — the `completion-gate` rule and the delivery skills it hands off to, for tool-specific implementation
3. **Project config** — project-level overrides or additions (AGENTS.md, CLAUDE.md, etc.)
4. **Memory files** — any supplemental verification workflows

**If no verification workflows found anywhere:**

STOP. Tell the user:

> "No verification workflows found in memory or instruction files. I recommend adding verification workflow memories at the user and/or project level so future work can be audited. Would you like help creating these?"

Then proceed with best-effort verification using whatever project conventions you can infer. Do not silently skip.

### 2. Audit

For **each** verification workflow step:

1. **Check**: Did you complete this step during this session? What evidence exists?
2. **If completed**: Record the result (test output, review findings, commit SHAs).
3. **If NOT completed**: **Execute it now using the gate function below** — do the work, then record the result.
4. **If blocked**: Record why and flag for the user.

Do not skip steps. Do not reorder steps. Do not decide steps "don't apply."

**The gate function** — apply per step, fresh, in this message:

1. **IDENTIFY** — What command or check proves this step?
2. **RUN** — Execute the full command (fresh, complete).
3. **READ** — Full output; check exit code; count failures.
4. **VERIFY** — Does the output confirm the claim?
5. **CLAIM** — Only now, with evidence.

Skipping any step is lying, not verifying. Stale evidence ("I ran tests earlier") is not fresh evidence — re-run.

### 3. Gather Context

Collect before writing the report:

- **Task objective** — What were you asked to do? One sentence.
- **PRs** — Branch names, PR URLs/numbers, current status
- **Remaining work** — Anything incomplete if this was a partial delivery, plus every in-scope discovery deferred to a tracked item (each is an escalation line here, not just a manifest row)
- **Discovered work** — Every issue found during implementation: fixed in-session, deferred in-scope, or filed out-of-scope
- **Triage audit** — For each item filed this session: anchor parent present? Priority rationale present? Provenance link present?

If discovered work is unrecorded, **record it now** in the project's tracking system (issues, backlog, memory entries — whatever the project uses). Unrecorded work is lost work. If a filed item is unanchored or untriaged, **fix it now** per the project's discovered-work discipline — an unanchored item is an orphan; anchor it, rate it, and say why.

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
| Item | Scope | Lands in | Tracked item | Priority — why |
|------|-------|----------|------------|----------------|
| [description] | in-scope | this PR | — | — |
| [description] | in-scope | parent work item (<id>) | <id> | P1 — deferred: <hatch>; <priority rationale> |
| [description] | out-of-scope | <anchor id> | <id> | P2 — <priority rationale> |
```

"Lands in" must be one of: `this PR`, `parent work item (<id>)`, an anchor
id, or `unanchored — needs your call` (the rare loud-escalation value) — never
a vague bucket like "future work". Any in-scope row not landing in `this PR`
must also appear under **Remaining Work** as an escalation line. A bare `—`
cell is legitimate only on `this PR` rows (nothing was filed, so there is no
tracked item or priority); every row that files a tracked item must fill all
five cells.

Omit sections that are genuinely empty (no PRs, no discovered work). But you must always include **Objective**, **Verification Checklist**, and **Remaining Work**.

## Red Flags — STOP

If any of these thoughts cross your mind, you're rationalizing:

| Thought | Reality |
|---------|---------|
| "I already verified everything" | Did you check memory for the full list? Audit again. |
| "The user didn't ask for a report" | The report IS the evidence. Produce it. |
| "These steps don't apply to this task" | Memory says they do. Follow them or justify in the report. |
| "I'll skip the discovered work section" | Unrecorded work is lost work. Record it now. |
| "I'll mention the filed items casually at the end" | Every discovery gets a manifest row with full triage — scope, landing anchor, priority rationale. |
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
