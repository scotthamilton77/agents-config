---
name: bugfix
description: Use when encountering a bug with unclear origins, when multiple files could be involved, or when the symptom does not obviously point to a single root cause
---

# Bugfix

**Core principle:** Gather evidence from three angles in parallel, synthesize into a root cause analysis, THEN fix. Sequential investigation wastes hours — parallel evidence gathering catches what single-threaded debugging misses.

**Iron Law:** `NO FIX WITHOUT PARALLEL EVIDENCE FIRST`

## When to Use

```dot
digraph when_to_use {
    "Bug reported" [shape=ellipse];
    "Root cause obvious?" [shape=diamond];
    "Fix directly" [shape=box];
    "Multiple files involved?" [shape=diamond];
    "Symptom unclear?" [shape=diamond];
    "Use this skill" [shape=doublecircle];
    "Use systematic-debugging" [shape=box];

    "Bug reported" -> "Root cause obvious?";
    "Root cause obvious?" -> "Fix directly" [label="yes, single line"];
    "Root cause obvious?" -> "Multiple files involved?" [label="no"];
    "Multiple files involved?" -> "Use this skill" [label="yes"];
    "Multiple files involved?" -> "Symptom unclear?" [label="no, single file"];
    "Symptom unclear?" -> "Use this skill" [label="yes"];
    "Symptom unclear?" -> "Use systematic-debugging" [label="no"];
}
```

**Use when:**
- Bug involves multiple files or layers
- Symptom doesn't point to a single obvious root cause
- Intermittent failures, race conditions, or data-dependent bugs
- You've already tried one fix and it didn't work

**Don't use when:**
- Root cause is obvious from the error message (typo, missing import, syntax error)
- Single-file, single-function bug with clear stack trace
- Build/config errors with explicit messages

## The Three Threads

Before proposing ANY fix, spawn three parallel tasks. All three MUST complete before you synthesize.

### Thread 1: Git Archaeology

```
Search git log for the last 20 commits touching the affected files.
For each relevant commit: summarize WHAT changed and WHO changed it.
Flag any commits that could have introduced the bug.
Return: Timeline of changes with annotations.
```

**Why this matters:** The bug was introduced by a change. Finding that change often reveals the root cause instantly.

### Thread 2: Reproduce with a Failing Test

```
Write a minimal failing test that reproduces the exact symptom described.
Run the test. Confirm it fails with the expected error.
If you cannot reproduce: say so. Do NOT write a test that tests something else.
Return: The test code AND the failure output.
```

**Why this matters:** A failing test proves you understand the symptom. If you can't reproduce it, you don't understand it yet.

### Thread 3: Data Flow Trace

```
Read all relevant source files from entry point to failure point.
Trace the data flow: what values enter, how they transform, where they exit.
Identify where the data could become invalid.
Return: Annotated data flow showing the path and suspect points.
```

**Why this matters:** Reading code reveals assumptions. Combined with git history and test results, it pinpoints where assumptions break.

Spawn all three as parallel subagent tasks in a single message. Each thread is independent — no shared state between them. **WAIT for all three to complete.** Do not proceed to synthesis if any thread is still running.

## Synthesis Gate

Once all three threads return, synthesize their findings:

1. **Correlate:** Does the git history show a change that aligns with the data flow suspect points?
2. **Confirm:** Does the failing test reproduce the exact symptom from the suspect path?
3. **Converge:** Do all three threads point to the same root cause?

```dot
digraph synthesis {
    "All 3 threads complete" [shape=ellipse];
    "Findings converge?" [shape=diamond];
    "State root cause with evidence" [shape=box];
    "Any thread inconclusive?" [shape=diamond];
    "Declare what is unknown" [shape=box];
    "Propose targeted investigation" [shape=box];
    "Propose fix" [shape=doublecircle];

    "All 3 threads complete" -> "Findings converge?";
    "Findings converge?" -> "State root cause with evidence" [label="yes"];
    "Findings converge?" -> "Any thread inconclusive?" [label="no"];
    "State root cause with evidence" -> "Propose fix";
    "Any thread inconclusive?" -> "Declare what is unknown" [label="yes"];
    "Any thread inconclusive?" -> "Propose targeted investigation" [label="all conclusive but divergent"];
    "Declare what is unknown" -> "Propose targeted investigation";
}
```

**Honesty clause:** If a thread's findings are inconclusive, say so. "Git history shows no relevant changes in the last 20 commits" is a valid finding. "I couldn't reproduce the failure" is a valid finding. Do NOT speculate to fill gaps.

**Fallback:** If root cause remains unclear after synthesis, escalate to complementary skills:
- `root-cause-tracing` — deep call-stack investigation
- `systematic-debugging` — full sequential 4-phase approach
- `condition-based-waiting` — timing/race condition analysis

## Implementation Phase

Only after synthesis identifies a root cause:

1. **Propose the fix** — explain what you'll change and why, citing evidence from the threads
2. **Implement the fix** — single focused change addressing the root cause
3. **Run the failing test** — confirm it now passes
4. **Run the full test suite** — confirm no regressions
5. **Commit only if ALL tests pass** — no partial commits, no "fix later" promises

## Red Flags — STOP and Recheck

If you catch yourself:
- Proposing a fix before all three threads complete
- Skipping the test thread because "I already understand the bug"
- Skipping git archaeology because "it's probably not a recent change"
- Writing a test that passes instead of fails
- Speculating about root cause when a thread was inconclusive
- Making multiple changes instead of a single focused fix
- Committing with failing tests ("only unrelated tests fail")
- Treating a user's diagnosis as confirmed without thread evidence
- Skipping threads because "production is down"

**ALL of these mean: STOP. You are skipping the process.**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "I can see the bug, skip the threads" | You see a symptom. Threads reveal root cause. |
| "Git history won't help here" | 80% of bugs trace to a recent change. Check anyway. |
| "Can't write a failing test for this" | If you can't reproduce it, you don't understand it. |
| "Two threads are enough" | Three angles catch what two miss. Run all three. |
| "Threads are overkill for this bug" | Sequential debugging wastes more time. Parallel is faster. |
| "I'll synthesize as threads come in" | Partial synthesis leads to premature conclusions. Wait for all three. |
| "The test isn't failing the right way" | Then you don't understand the symptom yet. Fix the test first. |
| "One fix should handle this" | Verify with the failing test. Don't trust your intuition. |
| "User already identified the root cause" | Their diagnosis is one data point, not confirmation. Threads verify or refute it. |
| "Production is down, no time for process" | A wrong fix in production is worse than a 10-minute investigation. Parallel is fast. |

## Quick Reference

| Phase | Action | Output |
|-------|--------|--------|
| **Dispatch** | Spawn 3 parallel tasks | Git timeline, failing test, data flow trace |
| **Synthesize** | Correlate findings from all 3 | Root cause with evidence, or honest gaps |
| **Fix** | Single change at root cause | Implementation addressing evidence |
| **Verify** | Run failing test + full suite | Green across the board |
| **Commit** | Only if all tests pass | Clean commit with context |

## Verification Checklist

Before claiming the bug is fixed:
- [ ] All three threads completed (none skipped)
- [ ] Synthesis explicitly correlates findings from all threads
- [ ] Root cause stated with evidence, not speculation
- [ ] Fix addresses root cause, not just symptom
- [ ] Original failing test now passes
- [ ] Full test suite passes with no regressions
- [ ] Commit includes only the focused fix

