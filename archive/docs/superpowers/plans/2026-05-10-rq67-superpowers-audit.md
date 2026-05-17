# Superpowers Audit & Skill Rationalization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all broken and wrong-namespace superpowers skill references in this repo, and retire two in-repo skills that duplicate superpowers-bundled content.

**Architecture:** Pure documentation changes — no code, no build system. Each task edits markdown files and verifies via grep. No automated tests apply to this change; verification is via grep assertions. Each task ends with a commit.

**Tech Stack:** Markdown, bash (grep/rm), git

**Spec:** `docs/superpowers/specs/2026-05-10-rq67-superpowers-audit-design.md`

---

## File Structure

**Modified:**
- `src/plugins/beads/.agents/agents/bead-implementor.md` — Tasks 1, 2
- `src/plugins/beads/.agents/agents/bug-diagnoser.md` — Task 1
- `src/plugins/beads/.agents/agents/tdd-red-team.md` — Task 2
- `src/plugins/beads/.agents/agents/tdd-green-team.md` — Task 2
- `src/user/.agents/skills/test-review/SKILL.md` — Task 1
- `src/user/.agents/skills/bugfix/SKILL.md` — Task 1
- `src/plugins/beads/.claude/rules/delivery.md` — Task 3

**Deleted:**
- `src/user/.agents/skills/testing-anti-patterns/` (entire directory) — Task 4
- `src/user/.agents/skills/condition-based-waiting/` (entire directory) — Task 5

---

### Task 1: Fix superpowers:root-cause-tracing references

`superpowers:root-cause-tracing` was removed as a standalone skill in superpowers v4.0.0. Its content is now bundled inside `superpowers:systematic-debugging`. All references must be updated to point there instead. If `superpowers:systematic-debugging` is already listed adjacent to `superpowers:root-cause-tracing` in a list, remove the old line rather than duplicating.

**Files:**
- Modify: `src/plugins/beads/.agents/agents/bead-implementor.md`
- Modify: `src/plugins/beads/.agents/agents/bug-diagnoser.md`
- Modify: `src/user/.agents/skills/test-review/SKILL.md`
- Modify: `src/user/.agents/skills/bugfix/SKILL.md`

- [ ] **Step 1: Fix bead-implementor.md**

  Current line 33:
  ```
    - superpowers:root-cause-tracing
  ```
  Change to:
  ```
    - superpowers:systematic-debugging
  ```
  *(If `superpowers:systematic-debugging` is already present in the same list, delete line 33 instead.)*

  Current line 65:
  ```
  Apply `superpowers:systematic-debugging` and `superpowers:root-cause-tracing`.
  ```
  Change to:
  ```
  Apply `superpowers:systematic-debugging`.
  ```

- [ ] **Step 2: Fix bug-diagnoser.md**

  Current line 31:
  ```
    - superpowers:root-cause-tracing
  ```
  Change to (or delete if `superpowers:systematic-debugging` already present in the list):
  ```
    - superpowers:systematic-debugging
  ```

  Current line 54:
  ```
  Apply `superpowers:systematic-debugging` and `superpowers:root-cause-tracing`. Reproduce reliably. Trace to the underlying defect, not the surface symptom.
  ```
  Change to:
  ```
  Apply `superpowers:systematic-debugging`. Reproduce reliably. Trace to the underlying defect, not the surface symptom.
  ```

- [ ] **Step 3: Fix test-review/SKILL.md**

  Current line 27:
  ```
  - Debugging a test failure caused by production code (use `bugfix` or `superpowers:root-cause-tracing`)
  ```
  Change to:
  ```
  - Debugging a test failure caused by production code (use `bugfix` or `superpowers:systematic-debugging`)
  ```

- [ ] **Step 4: Fix bugfix/SKILL.md**

  Current line 118:
  ```
  - `superpowers:root-cause-tracing` — deep call-stack investigation
  ```
  Change to:
  ```
  - `superpowers:systematic-debugging` — deep call-stack investigation (includes root-cause tracing)
  ```

- [ ] **Step 5: Verify no remaining root-cause-tracing references**

  Run:
  ```bash
  grep -r "superpowers:root-cause-tracing" src/ --include="*.md"
  ```
  Expected: no output

- [ ] **Step 6: Commit**

  ```bash
  git add src/plugins/beads/.agents/agents/bead-implementor.md \
          src/plugins/beads/.agents/agents/bug-diagnoser.md \
          src/user/.agents/skills/test-review/SKILL.md \
          src/user/.agents/skills/bugfix/SKILL.md
  git commit -m "fix(agents): replace removed superpowers:root-cause-tracing with superpowers:systematic-debugging"
  ```

---

### Task 2: Fix superpowers:testing-anti-patterns and superpowers:writing-unit-tests references

`superpowers:testing-anti-patterns` is not a superpowers skill — it is an in-repo skill being retired (Task 4). References to it should redirect to `superpowers:test-driven-development`, which is the superpowers skill that bundles testing anti-patterns content.

`superpowers:writing-unit-tests` is also an in-repo skill, not a superpowers skill. Drop the `superpowers:` prefix — correct reference is `writing-unit-tests`.

**Files:**
- Modify: `src/plugins/beads/.agents/agents/bead-implementor.md`
- Modify: `src/plugins/beads/.agents/agents/tdd-red-team.md`
- Modify: `src/plugins/beads/.agents/agents/tdd-green-team.md`

- [ ] **Step 1: Fix bead-implementor.md**

  Current line 28:
  ```
    - superpowers:writing-unit-tests
  ```
  Change to:
  ```
    - writing-unit-tests
  ```

  Current line 29:
  ```
    - superpowers:testing-anti-patterns
  ```
  **Delete this line.** `superpowers:test-driven-development` is already present on line 27; adding it again would duplicate it.

  Current lines 83-84:
  ```
  Apply `superpowers:test-driven-development`, `superpowers:writing-unit-tests`,
  `superpowers:testing-anti-patterns`.
  ```
  Change to:
  ```
  Apply `superpowers:test-driven-development` and `writing-unit-tests`.
  ```

- [ ] **Step 2: Fix tdd-red-team.md**

  Current line 30:
  ```
    - superpowers:writing-unit-tests
  ```
  Change to:
  ```
    - writing-unit-tests
  ```

  Current line 31:
  ```
    - superpowers:testing-anti-patterns
  ```
  **Delete this line.** `superpowers:test-driven-development` is already present on line 29.

  Current line 64:
  ```
  - Apply `superpowers:writing-unit-tests` and `superpowers:testing-anti-patterns`. No mock-driven design. No test-only methods on production classes.
  ```
  Change to:
  ```
  - Apply `writing-unit-tests` and `superpowers:test-driven-development`. No mock-driven design. No test-only methods on production classes.
  ```

- [ ] **Step 3: Fix tdd-green-team.md**

  Current line 33:
  ```
    - superpowers:testing-anti-patterns
  ```
  **Delete this line.** `superpowers:test-driven-development` is already present on line 31.

  Current line 59:
  ```
  - Apply `superpowers:test-driven-development` and `superpowers:verification-before-completion`. Apply `superpowers:testing-anti-patterns` to your production code: no test-only hooks, no shortcuts that satisfy assertions while degrading design.
  ```
  Change to:
  ```
  - Apply `superpowers:test-driven-development` and `superpowers:verification-before-completion`. No test-only hooks, no shortcuts that satisfy assertions while degrading design.
  ```

- [ ] **Step 4: Verify no remaining wrong-namespace testing references**

  Run:
  ```bash
  grep -r "superpowers:testing-anti-patterns\|superpowers:writing-unit-tests" src/ --include="*.md"
  ```
  Expected: no output

- [ ] **Step 5: Commit**

  ```bash
  git add src/plugins/beads/.agents/agents/bead-implementor.md \
          src/plugins/beads/.agents/agents/tdd-red-team.md \
          src/plugins/beads/.agents/agents/tdd-green-team.md
  git commit -m "fix(agents): fix superpowers namespace on testing-anti-patterns and writing-unit-tests refs"
  ```

---

### Task 3: Fix wrong-namespace refs in delivery.md

`wait-for-pr-comments` and `reply-and-resolve-pr-threads` are in-repo skills (`src/user/.agents/skills/`), not superpowers skills. The `superpowers:` prefix must be dropped.

**Files:**
- Modify: `src/plugins/beads/.claude/rules/delivery.md`

- [ ] **Step 1: Fix delivery.md**

  There are three occurrences across lines 7, 8, and 11. Make the following replacements throughout the file (replace all):

  `superpowers:wait-for-pr-comments` → `wait-for-pr-comments`

  `superpowers:reply-and-resolve-pr-threads` → `reply-and-resolve-pr-threads`

  After editing, the affected lines should read:
  ```
  - `implement-feature` ... the `review-cycle` step invokes `wait-for-pr-comments`, which internally chains to `reply-and-resolve-pr-threads` for thread reply + resolve ...
  - `fix-bug` — same pattern: ... `review-cycle` → `wait-for-pr-comments` (internally chains to `reply-and-resolve-pr-threads`).
  **Do NOT** invoke `superpowers:finishing-a-development-branch`, `wait-for-pr-comments`, or `reply-and-resolve-pr-threads` as peers ...
  ```

- [ ] **Step 2: Verify**

  Run:
  ```bash
  grep "superpowers:wait-for-pr-comments\|superpowers:reply-and-resolve" src/plugins/beads/.claude/rules/delivery.md
  ```
  Expected: no output

- [ ] **Step 3: Commit**

  ```bash
  git add src/plugins/beads/.claude/rules/delivery.md
  git commit -m "fix(beads): drop superpowers namespace from in-repo skill refs in delivery.md"
  ```

---

### Task 4: Retire testing-anti-patterns skill

The in-repo `testing-anti-patterns` skill covers the same concepts as the `testing-anti-patterns.md` reference bundled inside `superpowers:test-driven-development` (confirmed by content delta review). No unique content requires preservation.

**Files:**
- Delete: `src/user/.agents/skills/testing-anti-patterns/` (entire directory)

- [ ] **Step 1: Confirm no remaining callers**

  Run:
  ```bash
  grep -r "testing-anti-patterns" src/ --include="*.md"
  ```
  Expected: zero matches (Task 2 removed all callers). If any remain, fix them before proceeding.

- [ ] **Step 2: Delete the skill directory**

  Run:
  ```bash
  rm -rf src/user/.agents/skills/testing-anti-patterns
  ```

- [ ] **Step 3: Verify deletion**

  Run:
  ```bash
  ls src/user/.agents/skills/testing-anti-patterns 2>&1
  ```
  Expected: `No such file or directory`

- [ ] **Step 4: Commit**

  ```bash
  git add -A src/user/.agents/skills/testing-anti-patterns
  git commit -m "chore(skills): retire testing-anti-patterns — content covered by superpowers:test-driven-development"
  ```

---

### Task 5: Retire condition-based-waiting skill

The in-repo `condition-based-waiting` skill covers the same concepts as `condition-based-waiting.md` + `condition-based-waiting-example.ts` bundled inside `superpowers:systematic-debugging` (confirmed by content delta review). No unique content requires preservation.

**Files:**
- Delete: `src/user/.agents/skills/condition-based-waiting/` (entire directory)

- [ ] **Step 1: Confirm no remaining callers**

  Run:
  ```bash
  grep -r "condition-based-waiting" src/ --include="*.md"
  ```
  Expected: zero matches referencing the skill by name. If any remain, update them to `superpowers:systematic-debugging` before proceeding.

- [ ] **Step 2: Delete the skill directory**

  Run:
  ```bash
  rm -rf src/user/.agents/skills/condition-based-waiting
  ```

- [ ] **Step 3: Verify deletion**

  Run:
  ```bash
  ls src/user/.agents/skills/condition-based-waiting 2>&1
  ```
  Expected: `No such file or directory`

- [ ] **Step 4: Commit**

  ```bash
  git add -A src/user/.agents/skills/condition-based-waiting
  git commit -m "chore(skills): retire condition-based-waiting — content covered by superpowers:systematic-debugging"
  ```

---

### Task 6: Final verification

- [ ] **Step 1: Run full audit grep**

  Run:
  ```bash
  grep -r "superpowers:root-cause-tracing\|superpowers:testing-anti-patterns\|superpowers:writing-unit-tests\|superpowers:wait-for-pr-comments\|superpowers:reply-and-resolve-pr-threads" src/ --include="*.md"
  ```
  Expected: no output

- [ ] **Step 2: Verify retired skill directories are gone**

  Run:
  ```bash
  ls src/user/.agents/skills/ | grep -E "testing-anti-patterns|condition-based-waiting"
  ```
  Expected: no output

- [ ] **Step 3: Verify superpowers skills still valid**

  Confirm these skills still exist in the installed plugin (spot-check two):
  ```bash
  ls ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.1.0/skills/ | grep -E "systematic-debugging|test-driven-development"
  ```
  Expected:
  ```
  systematic-debugging
  test-driven-development
  ```

- [ ] **Step 4: Update bead status**

  ```bash
  bd close agents-config-rq67 --reason "All broken/wrong-namespace superpowers refs fixed; testing-anti-patterns and condition-based-waiting skills retired"
  ```
