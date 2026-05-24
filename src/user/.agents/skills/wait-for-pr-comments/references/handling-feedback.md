<!--
Provenance: this file amalgamates the pushback discipline from the
superpowers `receiving-code-review` skill at commit f2cbfbe (v5.1.0).
Source: oss-snapshots/superpowers/receiving-code-review/SKILL.md.

Drift policy: in-tree copy. Re-sync only when the source materially
changes; pattern #7 (blast-radius) is a local addition with no upstream
equivalent. Discovered work for related lifts is tracked under bead
agents-config-cx6.7.11.
-->

# Handling PR Review Feedback

Audience: the per-comment fix subagent dispatched by
`wait-for-pr-comments` Phase 4 (and any orchestrator-side classification
step). Load this BEFORE deciding FIX/SKIP/ESCALATE and BEFORE designing
the fix.

**Core principle:** technical correctness over social comfort. Verify
before agreeing. Ask before assuming. The comment is a hypothesis about
the code, not a verdict.

## Contents

- [The seven patterns](#the-seven-patterns)
  - [1. No performative agreement](#1-no-performative-agreement)
  - [2. Restate the requirement in your own words](#2-restate-the-requirement-in-your-own-words)
  - [3. Verify against the codebase before responding](#3-verify-against-the-codebase-before-responding)
  - [4. Push back with technical reasoning when wrong](#4-push-back-with-technical-reasoning-when-wrong)
  - [5. Ask before assuming on unclear items](#5-ask-before-assuming-on-unclear-items)
  - [6. YAGNI grep — verify the feature is actually used](#6-yagni-grep--verify-the-feature-is-actually-used)
  - [7. Check for larger blast radius](#7-check-for-larger-blast-radius)
- [Outcome routing](#outcome-routing)
- [When you pushed back and were wrong](#when-you-pushed-back-and-were-wrong)
- [What this file does NOT cover](#what-this-file-does-not-cover)

## The seven patterns

### 1. No performative agreement

Never agree before you have verified. The orchestrator's classification
and the subagent's commit message are both internal artifacts that the
reviewer never sees — but lazy phrasing leaks into the actual reply text
and produces fix decisions made for the wrong reason.

**Forbidden internal phrasings** (catch yourself before they appear in a
`fix_summary`, classification rationale, or commit message body):

- "You're absolutely right"
- "Great point" / "Excellent feedback"
- "Thanks for catching that" / any gratitude expression
- "Let me implement that now" (before verification)

**Instead:** restate the technical requirement in your own words, or just
act and let the diff speak. If you catch yourself about to type
"Thanks": delete it and state the fix.

### 2. Restate the requirement in your own words

Before classifying or acting, write down — even just in your scratch
space — what you understand the reviewer to be asking for. If the
restatement is fuzzy, ask. If you can't restate it without re-reading
the comment three times, the comment is ambiguous; route to ESCALATE.

Partial understanding produces wrong implementations. Restatement is the
cheapest comprehension check available.

### 3. Verify against the codebase before responding

The comment is a claim about the code. Check the claim before accepting
it.

```
BEFORE classifying FIX:
  1. Read the file at the cited line(s).
  2. Confirm the reviewer's description matches what is actually there.
  3. Check whether a recent commit (or another reviewer) already addressed it.
  4. Check whether the suggestion breaks something currently working.
  5. Check whether there is a documented reason for the current implementation.
```

If the reviewer's claim is wrong about what the code does, do NOT
implement their suggested fix. Push back with the actual code state
(pattern #4).

### 4. Push back with technical reasoning when wrong

Disagreement is fine. Defensiveness is not. Push back when:

- The suggestion breaks existing functionality.
- The reviewer lacks context the codebase makes obvious.
- It violates YAGNI (see pattern #6).
- It is technically incorrect for this stack / platform / version target.
- Legacy or compatibility constraints exist.
- It conflicts with an architectural decision recorded in `docs/adr/`
  or `CONTEXT.md`.

**How to push back:**

- Use technical reasoning grounded in the codebase, not opinion.
- Cite specific files, tests, or commits.
- Ask a specific clarifying question instead of restating the
  disagreement.

Example pushback (good, written in reply voice — safe to quote verbatim
into a thread reply): *"Build target is 10.15+; this API requires 13+.
Removing the legacy path breaks backward compatibility. Either keep the
path, or drop pre-13 support — which would you prefer?"*

Pushback decisions route to **SKIP** with a non-empty `rationale` that
the reviewer will actually read. The rationale becomes the public reply
verbatim — write it for them, not for the orchestrator.

### 5. Ask before assuming on unclear items

```
IF any part of the comment is unclear:
  STOP — do not implement anything yet.
  ROUTE: ESCALATE with rationale "needs clarification: <what is unclear>"
```

Comments often have implicit relationships. Implementing the parts you
understood while skipping the parts you didn't produces an inconsistent
fix that fails the next review round. Better to surface the ambiguity
once than to ship a half-answer.

### 6. YAGNI grep — verify the feature is actually used

Before implementing a "we should also..." suggestion, check whether the
target code is reachable.

```
IF reviewer suggests "implement properly" or "add X for completeness":
  grep the codebase for actual call sites or imports of the affected symbol.

  IF unused: route SKIP with rationale
    "This <symbol> has no callers in <searched-scope>. YAGNI — not
     adding <feature> for an unused entry point."
  IF used: implement the suggestion.
```

The reviewer and the agent both report to the human. If the feature
isn't needed, don't add it — even if the suggestion is technically
correct in isolation.

### 7. Check for larger blast radius

**The comment is a representative sample, not the only instance.**
Reviewers flag what they happened to read; the same defect almost
always exists in code they did not read.

```
WHEN classifying FIX:
  1. Identify the underlying defect class (missing null check, wrong
     error type, unguarded array access, stale import, etc.).
  2. Grep the codebase for analogous instances.
  3. Decide:
     - All instances fit cleanly in this PR's scope → fix them ALL
       in the same commit. One commit can address N instances; the
       Phase 4 "exactly one commit" guard is satisfied.
     - The broader fix would exceed PR scope (touches unrelated
       modules, requires a refactor, would inflate diff size beyond
       the reviewer's mental budget) → route ESCALATE with rationale
       "blast-radius exceeds PR scope: <N> additional instances at
        <paths>; needs human approval before expansion."
```

The agent performing the fix is responsible for fixing all areas needing
the same kind of fix — within the PR's scope. Crossing that scope
boundary requires human approval, not unilateral expansion.

**Example:**

> Reviewer flags missing null check on `userId` at `auth.ts:42`. You
> grep and find 8 other call sites in `auth.ts`, `session.ts`, and
> `middleware.ts` with the same pattern. All three files are already
> touched by this PR → fix all 9 in one commit. If the same pattern
> also lives in `billing.ts` (untouched by this PR) → ESCALATE the
> billing-side instances; fix only the in-scope 9.

## Outcome routing

The seven patterns produce one of three outcomes per comment:

| Outcome | When |
|---|---|
| **FIX → COMMITTED_FIX** | Verified (per #3), restated (per #2), blast-radius scoped (per #7), no YAGNI violation (per #6). |
| **SKIP** | Reviewer claim is wrong (per #3 + #4), or feature is unused (per #6 + #4), or you have a defensible counterargument. Rationale becomes the reply. |
| **ESCALATE** | Comment is ambiguous (per #2 + #5), or blast-radius exceeds PR scope (per #7), or you cannot make the call without human judgment. |

## When you pushed back and were wrong

If the orchestrator audits your report or a later review round proves
your SKIP rationale incorrect:

- Acknowledge factually: *"Verified — the reviewer is correct.
  `<file>:<line>` does <X>. Implementing."*
- Do NOT apologize at length.
- Do NOT defend the prior pushback.
- State the new fix and move on.

## What this file does NOT cover

These disciplines live elsewhere and are NOT repeated here:

- **Reply phrasing** — pinned template matrix in `wait-for-pr-comments/SKILL.md`
  and `reply-and-resolve-pr-threads/SKILL.md`. The matrix is sterile by
  design; no gratitude phrasings can leak through.
- **Verify-first-commit-second** — Phase 4 subagent contract in
  `wait-for-pr-comments/SKILL.md`.
- **`already_addressed` diff-hunk requirement** — orchestrator audit
  guard in `wait-for-pr-comments/SKILL.md`.
- **Serial dispatch** — Phase 4 enforces it; parallelism is a deferred
  follow-up.
