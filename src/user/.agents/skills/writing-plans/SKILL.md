---
name: writing-plans
description: Use when you have a spec or requirements for a multi-step task, before touching code
---

<!--
Source: oss-snapshots/superpowers/writing-plans/
Upstream: https://github.com/obra/superpowers @ f2cbfbefebbfef77321e4c9abc9e949826bea9d7 (v5.1.0)
Last sync: 2026-05-23
Drift policy: accept-periodic-resync. Byte-identical copy of upstream at initial import; the in-tree copy is now authoritative and may diverge. To inspect drift, diff against oss-snapshots/superpowers/writing-plans/.
-->

# Writing Plans

## Overview

Write comprehensive implementation plans assuming the engineer has zero context for our codebase and questionable taste. Document everything they need to know: which files to touch for each task, code, testing, docs they might need to check, how to test it. Give them the whole plan as bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume they are a skilled developer, but know almost nothing about our toolset or problem domain. Assume they don't know good test design very well.

**Announce at start:** "I'm using the writing-plans skill to create the implementation plan."

**Context:** If working in an isolated worktree, it should have been created via the `using-git-worktrees` skill at execution time.

**Save plans to:** `docs/plans/YYYY-MM-DD-<feature-name>.md`
- (User preferences for plan location override this default)

## Scope Check

If the spec covers multiple independent subsystems, it should have been broken into sub-project specs during brainstorming. If it wasn't, suggest breaking this into separate plans — one per subsystem. Each plan should produce working, testable software on its own.

## File Structure

Before defining tasks, map out which files will be created or modified and what each one is responsible for. This is where decomposition decisions get locked in.

- Design units with clear boundaries and well-defined interfaces. Each file should have one clear responsibility.
- You reason best about code you can hold in context at once, and your edits are more reliable when files are focused. Prefer smaller, focused files over large ones that do too much.
- Files that change together should live together. Split by responsibility, not by technical layer.
- In existing codebases, follow established patterns. If the codebase uses large files, don't unilaterally restructure - but if a file you're modifying has grown unwieldy, including a split in the plan is reasonable.

This structure informs the task decomposition. Each task should produce self-contained changes that make sense independently.

## Bite-Sized Task Granularity

**Each step is one action (2-5 minutes):**
- "Write the failing test" - step
- "Run it to make sure it fails" - step
- "Implement the minimal code to make the test pass" - step
- "Run the tests and make sure they pass" - step
- "Commit" - step

## Plan Document Header

**Every plan MUST start with this header:**

```markdown
# [Feature Name] Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

## Task Structure

````markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

## No Placeholders

Every step must contain the actual content an engineer needs. These are **plan failures** — never write them:
- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "add validation" / "handle edge cases"
- "Write tests for the above" (without actual test code)
- "Similar to Task N" (repeat the code — the engineer may be reading tasks out of order)
- Steps that describe what to do without showing how (code blocks required for code steps)
- References to types, functions, or methods not defined in any task

## Remember
- Exact file paths always
- Complete code in every step — if a step changes code, show the code
- Exact commands with expected output
- DRY, YAGNI, TDD, frequent commits

## Self-Review

After writing the complete plan, look at the spec with fresh eyes and check the plan against it. This is a checklist you run yourself — not a subagent dispatch.

**1. Spec coverage:** Skim each section/requirement in the spec. Can you point to a task that implements it? List any gaps.

**2. Placeholder scan:** Search your plan for red flags — any of the patterns from the "No Placeholders" section above. Fix them.

**3. Type consistency:** Do the types, method signatures, and property names you used in later tasks match what you defined in earlier tasks? A function called `clearLayers()` in Task 3 but `clearFullLayers()` in Task 7 is a bug.

If you find issues, fix them inline. No need to re-review — just fix and move on. If you find a spec requirement with no task, add the task.

## Plan Review Gate

After the plan self-review, run the same two-step gate the brainstorming skill
defines for specs, flavored for plans.

**Routing criteria:** the plan deviates from the spec; scope was discovered during
planning that the spec does not cover; the plan contains irreversible or migration
steps; the task graph is large or has subtle ordering constraints. No criterion
hit → announce `Review routing: lean (no criteria hit)`. Any hit → announce
`Review routing: deep (criteria: <names>)` and apply the brainstorming skill's
Review-Depth Routing mechanics to the plan (a deliberate cross-skill
read; both skills deploy together) — single `ralf-review` invocation, findings
fixed inline but the recorded verdict final and never re-earned, fail-closed
where the harness cannot dispatch an independent reviewer — with target = the
plan file and review criteria = coverage of the spec plus this skill's quality
bar (no placeholders, type consistency, exact paths).

**Attention routing:** apply the brainstorming skill's Attention Routing
to the plan — waiver conditions (a) recorded outcome clean (lean route or recorded `PASS` — not `PASS_WITH_RESERVATIONS` or `FAIL`), (b) no divergence from
the spec and the approved design, (c) frontier-tier session per the declaration in
the brainstorming skill's Attention Routing section (a deliberate cross-skill
read; both skills deploy together). A plan that silently absorbed a surprising
change never auto-proceeds. Waived or approved → Execution Handoff. Changes
requested → revise the plan and return to the attention stop, never back through
routing.

## Execution Handoff

Do not ask which execution approach to use. State a recommendation with one line
of reasoning:

- **Subagent-driven per-task dispatch** — the default where the harness supports
  independent dispatch: one fresh subagent per task, each receiving the task,
  required context, and instructions to use the `test-driven-development` skill;
  review output between tasks.
- **Workflow-orchestrated execution** — where the harness additionally supports
  workflow orchestration and the task graph is large or parallelizable.
- **Inline execution** — sequential in-session with per-task checkpoints
  (`test-driven-development` red → green → refactor → commit per task); for
  trivially small plans, and the degraded default on runtimes without independent
  dispatch.

Then recommend a clean-context start — compact the session or begin a fresh one,
so execution starts free of planning residue — and emit a copyable kickoff prompt
filled with the session's actual artifact locations (project conventions override
shipped defaults), varying the body with the recommended mode. Subagent-mode
template:

> Execute the implementation plan at `<plan-file path>` (spec: `<spec-file path>`).
> Work on a feature branch in an isolated worktree. Dispatch one fresh subagent
> per task; each task follows the `test-driven-development` skill. Start at Task 1.

This is the pipeline's single terminal pause: everything is pre-decided, and the
prompt exists to be handed to the user, who chooses when and where to clear
context and start execution.
