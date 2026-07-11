# Explain-Diff Quiz Contract Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every explain-diff quiz question contain one persona-consistent, visibly absurd wrong answer that is structurally verifiable.

**Architecture:** Keep presentation guidance in `SKILL.md`, keep copyable HTML in `assets/palette.md`, and record the behavioral contract in a skill-local evaluation. The generated explainer remains self-contained; no runtime JavaScript changes are needed.

**Tech Stack:** Markdown, JSON, self-contained HTML attributes.

---

### Task 1: Define the quiz contract evaluation

**Files:**
- Create: `src/user/.agents/skills/explain-diff/evals/evals.json`

- [x] **Step 1: Add an evaluation for an ambiguous technical quiz**

Define expectations for four option roles, exactly one `data-comic="true"` false option, an immediately contradictory premise, and persona-consistent visible wording and feedback.

- [x] **Step 2: Verify the current generated explainer fails the contract**

Run: `rg -o 'data-comic="true"' /private/tmp/2026-07-11-explanation-workcli-transport.html | wc -l | tr -d ' '`

Expected: `0`, because the reported output has no marker for a dedicated comic foil.

### Task 2: Tighten the source guidance and template

**Files:**
- Modify: `src/user/.agents/skills/explain-diff/SKILL.md`
- Modify: `src/user/.agents/skills/explain-diff/assets/palette.md`

- [x] **Step 1: Define the required four option roles**

Require two plausible distractors, one correct answer, and one false comic foil. Require the comic foil's visible text to be factually incompatible with the change and voiced in the resolved persona.

- [x] **Step 2: Make the template carry the semantic marker**

Add `data-comic="true"` to the comic foil and show a persona-shaped example in both the option text and feedback.

- [x] **Step 3: Extend the self-check**

Require exactly four options, exactly one correct option, and exactly one false comic option per question; verify that the latter is persona-consistent in visible text and feedback.

- [x] **Step 4: Run focused structural checks**

Run: `rg -n 'data-comic="true"|four options|persona-consistent' src/user/.agents/skills/explain-diff/SKILL.md src/user/.agents/skills/explain-diff/assets/palette.md`

Expected: Every required contract element appears in the source guidance and copyable template.
