# RALF-IT Foreign Agent Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add foreign agent (Codex, Gemini) review passes to RALF-IT iterations 1-2, with graceful degradation and artifact preservation.

**Architecture:** Claude subagents orchestrate foreign CLI invocations within their iteration, piping prompt files via stdin and capturing stdout to review files in `.ralf/{session_id}/`. Foreign agents run in read-only mode. All failures degrade to standard fresh-eyes behavior.

**Tech Stack:** Markdown skill files, Codex CLI (`codex exec -s read-only`), Gemini CLI (`gemini -p "" --approval-mode plan -o text`)

**Design doc:** `docs/plans/2026-03-15-ralf-foreign-agents-design.md`

---

### Task 1: Update Design Doc with CLI Discovery

**Files:**
- Modify: `docs/plans/2026-03-15-ralf-foreign-agents-design.md` (lines 211-218)

**Step 1: Replace the CLI Discovery section with verified findings**

Replace the "CLI Discovery (Implementation Time)" section with:

```markdown
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
```

**Step 2: Commit**

```bash
git add docs/plans/2026-03-15-ralf-foreign-agents-design.md
git commit -m "docs: update design with verified CLI invocation syntax"
```

---

### Task 2: Create `foreign-agent-prompt.md`

**Files:**
- Create: `src/user/.claude/skills/ralf-it/foreign-agent-prompt.md`

**Step 1: Write the foreign agent instruction file template**

This is the template for the instruction file that gets written to `.ralf/{session_id}/prompt-{agent}-{timestamp}.md` and piped to the foreign CLI via stdin. The Claude subagent fills in the `{placeholders}` when writing the file.

```markdown
# Code Review Request

You are reviewing code in this repository as an external reviewer. Your job is to assess the implementation against the spec and Definition of Done below, and produce a structured review.

## CRITICAL INSTRUCTIONS

- Do NOT modify any source files — you are running in read-only mode
- Output your complete review to stdout
- Be specific: reference file paths, line numbers, and code snippets
- Be honest: if the implementation is good, say so; if it has problems, detail them

## Definition of Done

{dod}

## Original Specification

{spec}

## Your Review Should Cover

1. **Correctness:** Does the implementation match the spec? Are all requirements addressed?
2. **Bugs:** Any logical errors, off-by-one mistakes, race conditions, or unhandled edge cases?
3. **Quality:** Code clarity, naming conventions, structure, consistency with project patterns?
4. **Tests:** Are tests meaningful, covering key behaviors and edge cases? Any missing coverage?
5. **Missing:** Anything the spec requires that isn't implemented or is only partially done?
6. **Security:** Any injection vectors, unsafe operations, or data handling concerns?

## Review Output Format

For each finding:

### [SEVERITY: critical|major|minor|nit] — Short descriptive title
- **File:** path/to/file.ext
- **Lines:** N-M (if applicable)
- **Issue:** Clear description of what's wrong or missing
- **Recommendation:** Specific suggested fix or improvement (with code if helpful)

After all findings, end with:

## Summary
- **Overall:** PASS / PASS_WITH_CONCERNS / NEEDS_WORK
- **Critical issues:** [count]
- **Major issues:** [count]
- **Minor issues:** [count]
- **Nits:** [count]
- **Brief assessment:** [1-2 sentences on overall quality]
```

**Step 2: Commit**

```bash
git add src/user/.claude/skills/ralf-it/foreign-agent-prompt.md
git commit -m "feat(ralf-it): add foreign agent instruction file template"
```

---

### Task 3: Create `foreign-eyes-prompt.md`

**Files:**
- Create: `src/user/.claude/skills/ralf-it/foreign-eyes-prompt.md`

**Step 1: Write the foreign-eyes subagent prompt template**

This is used by the RALF controller to dispatch Claude subagents for iterations 1-2 (the ones that include foreign agent consultation). It replaces `fresh-eyes-prompt.md` for those iterations only.

```markdown
# RALF-IT Foreign-Eyes Subagent Prompt Template

This template is used for RALF iterations that include foreign agent (Codex/Gemini) consultation.
The Claude subagent performs fresh-eyes implementation work AND coordinates a foreign CLI review.

**Used for:** Iterations 1 (Codex) and 2 (Gemini) only. Iterations 3+ use `fresh-eyes-prompt.md`.

**Critical:** Like fresh-eyes, this subagent gets NO context from previous iterations.
It sees only the original spec and the current code state.

## Dispatch Template

` ` `
Agent tool (general-purpose, mode: "auto"):
  description: "RALF foreign-eyes: {agent_name} review"
  prompt: |
    You are a foreign-eyes assessor in a RALF-IT refinement cycle. You will do fresh-eyes
    implementation work AND coordinate a review by an external AI agent ({agent_name}).

    ## Phase 1: Setup

    Read the spec and DoD below. BEFORE examining any code, write the foreign agent
    instruction file. This must happen first so your implementation work doesn't
    contaminate what the foreign agent is told.

    1. Create directory: `mkdir -p .ralf/{session_id}`
    2. Write the instruction file to: `.ralf/{session_id}/prompt-{agent_lower}-{timestamp}.md`

    Use this template for the instruction file — fill in the DoD and spec sections:

    [PASTE contents of ./foreign-agent-prompt.md here, with {dod} and {spec} filled in]

    ## Phase 2: Fresh-Eyes Implementation

    NOW examine the code. A task has been started by another agent, but we are NOT
    confident it is truly complete or at acceptable quality.

    3. Examine the current state of the code
    4. Assess whether the work meets the Definition of Done
    5. Fix, complete, or improve whatever is necessary
    6. Run build + typecheck + lint + tests — all must pass
    7. Commit your changes (if any)

    You are NOT just a reviewer. You are an implementer with fresh eyes. If something
    needs fixing, fix it. If something is missing, build it.

    ## Phase 3: Foreign Agent Consultation

    After your own implementation work is committed, invoke the foreign agent CLI:

    **For Codex:**
    ```bash
    codex exec -s read-only - < .ralf/{session_id}/prompt-codex-{timestamp}.md \
      > .ralf/{session_id}/codex-review-{timestamp}.md \
      2> .ralf/{session_id}/codex-errors-{timestamp}.log
    ```
    Use a 10-minute timeout (timeout: 600000).

    **For Gemini:**
    ```bash
    gemini -p "" --approval-mode plan -o text \
      < .ralf/{session_id}/prompt-gemini-{timestamp}.md \
      > .ralf/{session_id}/gemini-review-{timestamp}.md \
      2> .ralf/{session_id}/gemini-errors-{timestamp}.log
    ```
    Use a 10-minute timeout (timeout: 600000).

    **After the CLI finishes:**

    8. Check the error log for failures:
       - "command not found" → report UNAVAILABLE
       - Exit timeout → report TIMED_OUT
       - Patterns: "quota", "rate limit", "rate_limit", "exceeded", "429",
         "resource_exhausted", "too many requests" → report QUOTA_EXCEEDED
       - Empty or missing review file → report NO_OUTPUT
    9. If any failure: skip to Phase 5 (report the failure, your own work still counts)
    10. Read the review file

    ## Phase 4: Evaluate & Apply Foreign Feedback

    For each recommendation in the foreign agent's review:

    11. Evaluate against the original spec/DoD (not your own opinions about the code)
    12. Check if the recommendation is technically correct
    13. Apply changes you agree with
    14. Note recommendations you reject and why
    15. Run build + typecheck + lint + tests again — all must pass
    16. Commit any additional changes from foreign agent feedback

    **Important:** Do NOT blindly apply all recommendations. The foreign agent may
    hallucinate, misunderstand the spec, or suggest changes that conflict with project
    conventions. You are the decision-maker.

    ## Phase 5: Report

    ## Definition of Done

    [PASTE the agreed Definition of Done — the ORIGINAL, not any previous agent's interpretation]

    ## Original Task/Spec

    [PASTE the ORIGINAL task/plan/spec — the source of truth, not a summary]

    ## Context

    [Architectural context, conventions, related files]

    ## Quality Criteria

    In addition to the Definition of Done, verify:
    - Build passes
    - Typecheck passes
    - Lint passes
    - Tests pass and have meaningful coverage
    - Code follows existing project patterns and conventions
    - No TODO/FIXME/HACK comments left behind (unless pre-existing)
    - No dead code or unused imports introduced

    Work from: [worktree directory]

    ## Report Format

    When done, report:

    ### Assessment
    - Overall status: COMPLETE / INCOMPLETE / NEEDS_WORK
    - Confidence: HIGH / MEDIUM / LOW

    ### What I Found
    - [List of issues, gaps, or concerns discovered during Phase 2]
    - [Or: "No significant issues found"]

    ### What I Changed
    - [List of changes made during Phase 2, with reasoning]
    - [Or: "No changes necessary"]

    ### Foreign Agent Review ({agent_name})
    - Status: COMPLETED / UNAVAILABLE / TIMED_OUT / QUOTA_EXCEEDED / NO_OUTPUT
    - Findings: [N] total ([critical] / [major] / [minor] / [nit])
    - Accepted: [list of recommendations applied, with reasoning]
    - Rejected: [list of recommendations not applied, with reasoning]
    - Review file: .ralf/{session_id}/{agent_lower}-review-{timestamp}.md

    ### Quality Status
    - Build: PASS/FAIL
    - Typecheck: PASS/FAIL
    - Lint: PASS/FAIL
    - Tests: PASS/FAIL ([N] tests)

    ### Remaining Concerns
    - [Anything the user should know about]
    - [Or: "None — work meets Definition of Done"]
` ` `

## Interpreting the Report

Same logic as fresh-eyes-prompt.md, with one addition: foreign agent status is reported
to the main controller but does NOT affect the convergence decision. Convergence is based
solely on whether the Claude subagent found significant work to do.

| Foreign Status | Impact on Iteration |
|---|---|
| COMPLETED | Foreign findings factored into subagent's changes |
| UNAVAILABLE / TIMED_OUT / QUOTA_EXCEEDED / NO_OUTPUT | Iteration proceeds as pure fresh-eyes |
```

**Step 2: Commit**

```bash
git add src/user/.claude/skills/ralf-it/foreign-eyes-prompt.md
git commit -m "feat(ralf-it): add foreign-eyes subagent prompt template"
```

---

### Task 4: Update SKILL.md — Loop Structure and Foreign Agent Sections

**Files:**
- Modify: `src/user/.claude/skills/ralf-it/SKILL.md`

This is the largest change. Update these sections of SKILL.md:

**Step 1: Update the process flow diagram (lines 39-69)**

Replace the existing `digraph ralf_process` with the updated flow that shows foreign-eyes for iterations 1-2 and fresh-eyes for 3+. Key changes:
- After quality gate, decision node: "Iteration 1 or 2?" → foreign-eyes-prompt.md / fresh-eyes-prompt.md
- Add foreign agent names to the iteration 1/2 paths

**Step 2: Add new section "Foreign Agent Configuration" after Step 3 (worktree)**

Add the `.ralf/` directory structure, gitignore ceremony, and CLI invocation reference as a new subsection. Place it between Step 3 and Step 4 as "Step 3b: Foreign Agent Setup" — runs the gitignore check, creates `.ralf/{session_id}/` directory.

**Step 3: Update Step 6 (Fresh-Eyes dispatch) to describe iteration routing**

The controller now checks the iteration number:
- Iteration 1: dispatch using `foreign-eyes-prompt.md` with `{agent_name}=Codex`
- Iteration 2: dispatch using `foreign-eyes-prompt.md` with `{agent_name}=Gemini`
- Iteration 3+: dispatch using `fresh-eyes-prompt.md` (unchanged behavior)

**Step 4: Update the report template (lines 179-204)**

Add the "Foreign Agent Participation" and "Foreign Agent Artifacts" sections from the design doc.

**Step 5: Update Red Flags section (lines 227-244)**

Add all foreign-agent-specific red flags from the design doc.

**Step 6: Update Integration section (lines 248-262)**

Add the new prompt templates to the list and note the CLI dependencies.

**Step 7: Update Quick Reference table (lines 215-224)**

Add entries for foreign agent scenarios:
- Foreign agent quota hit → degrade to pure fresh-eyes
- Foreign agent times out → degrade to pure fresh-eyes
- Foreign agent unavailable → degrade to pure fresh-eyes

**Step 8: Commit**

```bash
git add src/user/.claude/skills/ralf-it/SKILL.md
git commit -m "feat(ralf-it): integrate foreign agent review into RALF loop"
```

---

### Task 5: Verification

**Step 1: Read all modified files end-to-end**

Read each file to verify internal consistency:
- `SKILL.md` references to `foreign-eyes-prompt.md` and `foreign-agent-prompt.md` are correct
- `foreign-eyes-prompt.md` CLI invocations match design doc
- `foreign-agent-prompt.md` output format matches what `foreign-eyes-prompt.md` expects to parse
- Iteration routing logic (1=Codex, 2=Gemini, 3+=standard) is consistent everywhere
- `.ralf/` path patterns are consistent across all files

**Step 2: Verify no broken cross-references**

Grep for all `./` references in the skill directory and confirm targets exist.

**Step 3: Final commit if any fixes needed**

```bash
git add -A src/user/.claude/skills/ralf-it/
git commit -m "fix(ralf-it): address cross-reference issues from verification"
```
