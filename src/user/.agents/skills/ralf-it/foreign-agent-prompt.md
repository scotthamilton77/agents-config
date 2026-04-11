# RALF-IT Foreign Agent Instruction File Template

This template is used by the foreign-eyes subagent to create the instruction file handed
to a foreign CLI (Codex via the Claude Code Codex plugin, or Gemini via the `gemini`
binary). The subagent fills in `{dod}` and `{spec}` from the original task before writing
the file.

**Written to:** `.ralf/{session_id}/prompt-{agent}-{timestamp}.md`

**Consumed by:**
- **Codex:** `codex-companion.mjs task < <path>` (read-only sandbox)
- **Gemini:** `gemini -p "" --approval-mode plan -o text < <path>` (plan mode)

**Critical:** This file is written BEFORE the subagent does any implementation work,
so it reflects the clean spec/DoD without implementation bias.

---

## Template

The subagent writes the following content (with placeholders filled in) to the prompt file:

```markdown
# Code Review Request

You are reviewing code in this repository as an external reviewer. Your job is to assess
the implementation against the specification and Definition of Done below, and produce a
structured review.

## CRITICAL INSTRUCTIONS

- Do NOT modify any source files — you are running in read-only mode
- Output your complete review to stdout (it will be captured automatically)
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
