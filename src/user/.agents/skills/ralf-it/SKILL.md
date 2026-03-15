---
name: ralf-it
model: opus
argument-hint: "[task-id, plan file, or description]"
description: Use when executing tasks, implementing plans, designs, or complex multi-step work - iterative refinement with fresh-eyes subagents that catch what the first pass missed
---

# RALF-IT: Refine, Assess, Loop, Finalize

Execute work through iterative refinement cycles where each cycle dispatches a fresh-eyes subagent to find and fix what the previous pass missed. Produces substantially higher quality than single-pass execution.

**Core principle:** Fresh subagent per refinement cycle + quality gates between cycles = converging on excellence. Use ultrathink for synthesis and evaluation decisions.

**Announce at start:** "I'm using RALF-IT to execute this with iterative refinement."

## When to Use

```dot
digraph when_to_use {
    "Have a task, plan, or spec?" [shape=diamond];
    "Trivial one-liner?" [shape=diamond];
    "Just do it directly" [shape=box];
    "RALF-IT" [shape=box style=filled fillcolor=lightgreen];

    "Have a task, plan, or spec?" -> "Trivial one-liner?" [label="yes"];
    "Have a task, plan, or spec?" -> "Just do it directly" [label="no - need plan first"];
    "Trivial one-liner?" -> "Just do it directly" [label="yes"];
    "Trivial one-liner?" -> "RALF-IT" [label="no"];
}
```

- Implementation of features, bug fixes, refactors
- Executing written plans or design specs
- Any task where quality matters more than speed
- Multi-file changes where things can fall through cracks

**Don't use for:** Config tweaks, typo fixes, single-line changes, pure research/exploration.

## The Process

```dot
digraph ralf_process {
    rankdir=TB;
    node [shape=box];

    align [label="1. Align on Definition of Done with user"];
    ask_iters [label="2. Ask user for max iterations (default 5)"];
    worktree [label="3. Create worktree\n(using-git-worktrees skill)"];
    foreign_setup [label="3b. Foreign agent setup\n(.ralf/ directory, gitignore ceremony)"];
    implement [label="4. Dispatch implementation subagent(s)\n(./implementer-prompt.md)"];
    quality_gate [label="5. Quality Gate:\ncode-reviewer agent\ncode-simplifier agent\nbuild + typecheck + lint + test"];
    iter_check [label="Iteration 1 or 2?" shape=diamond];
    foreign_eyes [label="6a. Dispatch FOREIGN-EYES subagent\n(./foreign-eyes-prompt.md)\nIter 1: Codex review\nIter 2: Gemini review"];
    fresh_eyes [label="6b. Dispatch FRESH-EYES subagent\n(./fresh-eyes-prompt.md)\nPure Claude fresh-eyes"];
    significant [label="Significant work done?" shape=diamond];
    under_max [label="Under max iterations?" shape=diamond];
    ask_more [label="Report status, ask user\nif they want more cycles" shape=box];
    final_review [label="Final quality gate:\ncode-reviewer + code-simplifier\naddress significant issues"];
    report [label="Full report to user\nwith iteration count"];

    align -> ask_iters;
    ask_iters -> worktree;
    worktree -> foreign_setup;
    foreign_setup -> implement;
    implement -> quality_gate;
    quality_gate -> iter_check;
    iter_check -> foreign_eyes [label="yes - iteration 1 or 2"];
    iter_check -> fresh_eyes [label="no - iteration 3+"];
    foreign_eyes -> significant;
    fresh_eyes -> significant;
    significant -> under_max [label="yes"];
    significant -> final_review [label="no - converged"];
    under_max -> quality_gate [label="yes - loop back\n(new eyes next)"];
    under_max -> ask_more [label="no - max reached"];
    ask_more -> quality_gate [label="user says continue"];
    ask_more -> final_review [label="user says stop"];
    final_review -> report;
}
```

## Step-by-Step

### Step 1: Align on Definition of Done

Before touching code, ensure crystal clarity on the outcome:

1. Read the task/plan/spec completely
2. State back to the user: "Here's what I understand the Definition of Done to be: [list]"
3. Include acceptance criteria: build passes, typecheck passes, tests pass, plus task-specific criteria
4. Get explicit user confirmation before proceeding

**If the input is a bead/issue:** Read it with `bd show <id>` and extract acceptance criteria.
**If the input is a plan file:** Read it and summarize the expected deliverables.
**If the input is verbal:** Restate it precisely and confirm.

### Step 2: Ask for Iteration Count

```
How many RALF iterations would you like? (default: 5)

Each iteration dispatches a fresh-eyes subagent to find and fix
what previous passes missed. Most tasks converge in 2-3 cycles.
Early exit if the fresh-eyes subagent finds nothing significant.
```

Store the answer as `MAX_ITERATIONS`. Proceed with default if user says "default" or doesn't specify.

### Step 3: Create Worktree

**REQUIRED SUB-SKILL:** Use superpowers:using-git-worktrees

Create an isolated worktree for all RALF work. All subagents work in this worktree.

### Step 3b: Foreign Agent Setup

Prepare the `.ralf/` directory for foreign agent artifacts. This runs once, after worktree creation, before any implementation work.

**Variables:**
- `{session_id}`: The main RALF controller's session ID (prevents cross-session collisions)
- `{timestamp}`: Format `YYYYMMDD-HHmmss` (prevents cross-run collisions within a session)

**`.ralf/` directory structure:**

```
.ralf/
├── .no-gitignore-prompt                    # marker: stop asking about .gitignore
└── {session_id}/
    ├── prompt-codex-{timestamp}.md         # instruction file for Codex
    ├── prompt-gemini-{timestamp}.md        # instruction file for Gemini
    ├── codex-review-{timestamp}.md         # Codex review output (stdout capture)
    ├── gemini-review-{timestamp}.md        # Gemini review output (stdout capture)
    ├── codex-errors-{timestamp}.log        # Codex stderr capture
    └── gemini-errors-{timestamp}.log       # Gemini stderr capture
```

**Gitignore ceremony:**

1. Check if `.ralf` or `.ralf/` appears in `.gitignore`
2. If present: proceed silently
3. If missing: check for `.ralf/.no-gitignore-prompt` marker
   - If marker exists: skip silently
   - Otherwise ask user: "Add `.ralf/` to `.gitignore`?"
     - If yes: append `.ralf/` to `.gitignore`
     - If no: ask "Stop asking?" — if yes, create `.ralf/.no-gitignore-prompt` marker file
4. Create `.ralf/{session_id}/` directory

**Foreign CLI invocations reference:**

| Agent | Command |
|-------|---------|
| Codex | `codex exec -s read-only - < {prompt_file} > {review_file} 2>{error_file}` |
| Gemini | `gemini -p "" --approval-mode plan -o text < {prompt_file} > {review_file} 2>{error_file}` |

Both use a 10-minute timeout (600000ms) and run in read-only/plan mode (cannot modify source files).

### Step 4: Dispatch Implementation Subagent(s)

Dispatch one or more subagents to execute the initial implementation using `${CLAUDE_SKILL_DIR}/implementer-prompt.md`.

- For plans with multiple independent tasks, dispatch per task (sequentially, not parallel — avoid conflicts)
- For single tasks, dispatch one implementer
- Subagents should follow TDD, commit their work, and self-review

Wait for all implementation to complete before proceeding.

### Step 5: Quality Gate

Run these in sequence:

1. **code-reviewer agent** — Full code review against the spec/plan
2. **code-simplifier agent** — Simplify and refine for clarity
3. **Build quality checks** — `pnpm build && pnpm typecheck && pnpm lint` (or project equivalent)
4. **Tests** — Run the relevant test suite

If the code-reviewer or code-simplifier finds significant issues, have them fix what they can. Record what was found for the fresh-eyes subagent.

### Step 6: Dispatch Eyes Subagent (Foreign or Fresh)

This is the core RALF innovation. Dispatch a **brand new** subagent for each iteration. The controller selects the prompt template based on iteration number:

**Iteration routing:**

| Iteration | Template | Foreign Agent |
|-----------|----------|---------------|
| 1 | `${CLAUDE_SKILL_DIR}/foreign-eyes-prompt.md` with `{agent_name}=Codex`, `{agent_lower}=codex` | Codex |
| 2 | `${CLAUDE_SKILL_DIR}/foreign-eyes-prompt.md` with `{agent_name}=Gemini`, `{agent_lower}=gemini` | Gemini |
| 3+ | `${CLAUDE_SKILL_DIR}/fresh-eyes-prompt.md` | None (pure Claude) |

**Rules based on MAX_ITERATIONS:**
- `MAX_ITERATIONS == 1`: Only Codex gets a foreign-eyes pass
- `MAX_ITERATIONS == 2`: Codex then Gemini
- `MAX_ITERATIONS >= 3`: Codex, Gemini, then pure Claude for the rest

**If a foreign agent fails** (unavailable, timeout, quota exhausted, no output), the iteration degrades to a pure fresh-eyes pass. The iteration still counts. The failure is reported in the final report.

Key properties of every eyes dispatch (foreign or fresh):
- **New subagent** — no context from previous implementation (fresh perspective)
- **Told the task may be incomplete** — not told "verify this is done," but rather "this may have been started, assess and complete it"
- **No iteration count exposed** — do NOT tell the subagent which iteration it is or how many have run. Knowing "iteration 3 of 5" biases toward shallower assessment ("others already checked this"). The controller tracks iterations internally; the subagent should approach every assessment as if it's the first.
- **Given the original spec/plan** — not the previous agent's summary
- **Empowered to change anything** — not just review, but fix

The subagent reports back:
- What it found (issues, gaps, incomplete work)
- What it changed
- Whether it considers the work complete
- Any remaining concerns
- Foreign agent review status and accepted/rejected recommendations (iterations 1-2 only)

### Step 7: Evaluate and Loop

Set `iteration = 1` before the first fresh-eyes dispatch. After each fresh-eyes report:

```
IF fresh-eyes found nothing significant AND reports work complete:
    → Exit loop early. Proceed to Final Review.

IF fresh-eyes did significant work:
    IF iteration < MAX_ITERATIONS:
        → iteration += 1
        → Go to Step 5 (Quality Gate) with new fresh-eyes next
    ELSE:
        → Report to user: "Reached {MAX_ITERATIONS} iterations.
           Last fresh-eyes subagent still found significant work:
           [summary of what was found/fixed].
           Want to run more cycles?"
        → If user says yes: increase MAX_ITERATIONS, continue loop
        → If user says no: proceed to Final Review
```

**"Significant work"** means: the fresh-eyes subagent made functional changes, fixed bugs, added missing functionality, or addressed gaps in test coverage. Cosmetic-only changes (formatting, minor renames) do NOT count as significant.

### Step 8: Final Review

After the loop exits:

1. Run **code-reviewer agent** one final time
2. Run **code-simplifier agent** one final time
3. Address any significant issues they surface
4. Run full build + typecheck + lint + test one more time

### Step 9: Report

Present a complete report to the user:

```markdown
## RALF-IT Complete

**Task:** [description]
**Iterations:** [N] of [MAX] (early exit: yes/no)
**Definition of Done:** [met/not met, with details]

### Iteration Summary
- **Initial implementation:** [what was built]
- **Iteration 1 (+ Codex review):** [fresh-eyes findings] + [Codex findings]
- **Iteration 2 (+ Gemini review):** [fresh-eyes findings] + [Gemini findings]
- **Iteration 3+:** [standard fresh-eyes findings]
- ...

### Foreign Agent Participation
- **Iteration 1 (Codex):** [COMPLETED/UNAVAILABLE/TIMED_OUT/QUOTA_EXCEEDED/NO_OUTPUT]
  - Findings: [N] ([accepted]/[rejected])
  - Notable: [most impactful accepted recommendation, if any]
- **Iteration 2 (Gemini):** [COMPLETED/UNAVAILABLE/TIMED_OUT/QUOTA_EXCEEDED/NO_OUTPUT]
  - Findings: [N] ([accepted]/[rejected])
  - Notable: [most impactful accepted recommendation, if any]

### Quality Status
- Build: PASS/FAIL
- Typecheck: PASS/FAIL
- Lint: PASS/FAIL
- Tests: PASS/FAIL ([N] tests)
- Code review: [summary]

### Files Changed
[list of files]

### Foreign Agent Artifacts
Review files preserved at: .ralf/{session_id}/

### Remaining Concerns
[any issues the user should be aware of]
```

After reporting, use **superpowers:finishing-a-development-branch** to present merge/PR options.

## Prompt Templates

- `${CLAUDE_SKILL_DIR}/implementer-prompt.md` — Dispatch initial implementation subagent(s)
- `${CLAUDE_SKILL_DIR}/fresh-eyes-prompt.md` — Dispatch fresh-eyes refinement subagent (iteration 3+)
- `${CLAUDE_SKILL_DIR}/foreign-eyes-prompt.md` — Dispatch foreign-eyes subagent (iterations 1-2, includes foreign CLI review)
- `${CLAUDE_SKILL_DIR}/foreign-agent-prompt.md` — Template for instruction file written to `.ralf/` for foreign CLI consumption

## Quick Reference

| Situation | Action |
|-----------|--------|
| User gives a plan | Read it, align on DoD, RALF-IT |
| User gives a bead ID | `bd show`, extract criteria, RALF-IT |
| User gives verbal task | Restate DoD, confirm, RALF-IT |
| Fresh-eyes finds nothing | Early exit, proceed to final review |
| Max iterations reached | Report to user, ask to continue |
| Fresh-eyes only cosmetic | Counts as converged, exit loop |
| Build/test fails in gate | Fix before dispatching fresh-eyes |
| Task is trivial | Don't use RALF-IT, just do it |
| Foreign agent quota hit | Degrade to pure fresh-eyes, report quota status |
| Foreign agent times out | Degrade to pure fresh-eyes, report timeout |
| Foreign agent unavailable | Degrade to pure fresh-eyes, report unavailable |
| MAX_ITERATIONS is 1 | Only Codex gets foreign-eyes pass |
| MAX_ITERATIONS is 2 | Codex then Gemini |

## Red Flags

**Never:**
- Skip Definition of Done alignment (the whole point is knowing when you're done)
- Reuse a subagent for fresh-eyes (must be brand new, no prior context)
- Tell the fresh-eyes subagent which iteration it is (biases toward shallower assessment)
- Tell the fresh-eyes subagent "just verify this is done" (tell it "this may be incomplete, assess and complete")
- Skip quality gates between iterations (that's where issues surface)
- Count cosmetic-only changes as "significant work" (inflates iteration count)
- Run fresh-eyes subagents in parallel (they'd conflict)
- Skip the final review pass (last chance to catch issues)
- Exceed max iterations without asking the user
- Write the foreign agent instruction file after doing implementation work (context contamination)
- Let a foreign agent modify source files directly (review document only — enforced by read-only sandbox)
- Trust foreign agent recommendations blindly (evaluate each against spec/DoD)
- Skip an iteration because the foreign agent failed (degrade to pure fresh-eyes)
- Expose iteration count to foreign agents (no bias)

**Always:**
- Get DoD confirmation before starting
- Use a worktree for isolation
- Give fresh-eyes the ORIGINAL spec, not the previous agent's summary
- Track iteration count and report it
- Exit early when converged (don't waste iterations)
- Write the instruction file from clean spec context before implementation
- Set a 10-minute timeout on foreign CLI invocation
- Check for token quota exhaustion patterns in CLI output
- Report foreign agent status even when it fails (visibility)
- Preserve all `.ralf/` artifacts for debugging

## Integration

**Required workflow skills:**
- **superpowers:using-git-worktrees** — REQUIRED: Isolated workspace
- **superpowers:finishing-a-development-branch** — REQUIRED: After RALF completes

**Quality gate agents:**
- **superpowers:code-reviewer** — Code review between iterations
- **code-simplifier:code-simplifier** — Code simplification between iterations

**Subagents should use:**
- **superpowers:test-driven-development** — TDD for implementation

**Foreign agent CLIs (iterations 1-2 only):**
- **Codex CLI** — `codex exec -s read-only` (read-only sandbox)
- **Gemini CLI** — `gemini --approval-mode plan` (read-only plan mode)

**RALF-IT replaces these for complex work:**
- **superpowers:subagent-driven-development** — RALF-IT adds iterative refinement on top
- **superpowers:executing-plans** — RALF-IT adds fresh-eyes cycles

## Why This Works

Single-pass development has a fundamental flaw: the implementing agent is blind to its own assumptions. It builds a mental model, codes to that model, and reviews against that same model. Bugs and gaps that fit the model are invisible.

Fresh-eyes subagents break this cycle. Each new subagent:
- Has no knowledge of shortcuts taken
- Reads the spec with fresh understanding
- Notices gaps the previous agent rationalized away
- Isn't anchored to "but I already built it this way"

Empirically, most tasks converge in 2-3 iterations. The first fresh-eyes pass catches the most issues. Subsequent passes catch progressively less, until convergence.
