# ralf-implement foreign-agent prompt template

Template for foreign CLI review instruction files used by `ralf-implement`.

Written to `.ralf/{session_id}/prompt-{agent}-{timestamp}.md` before foreign review execution.

Consumed by:
- Codex: `codex-companion.mjs task < path` in read-only mode
- Gemini: `gemini -p "" --approval-mode plan -o text < path`

This file is written before the fresh-eyes implementer inspects or changes code, so the foreign reviewer sees the clean original spec and Definition of Done without implementation bias.

## Template

```markdown
# External Implementation Review Request

You are reviewing repository changes against the original implementation target.

## Critical Instructions

- Do not modify any source files. You are running in read-only mode.
- Output your complete review to stdout. It will be captured automatically.
- Be specific: reference file paths, line numbers, and code snippets where applicable.
- Be honest: if the implementation is good, say so; if it has problems, detail them.
- Assess against the original specification and Definition of Done, not prior agent summaries.
- Treat the work as possibly incomplete; do not assume previous agents finished it correctly.

## Definition of Done

{dod}

## Original Target

{spec}

## Review Dimensions

1. Correctness against target behavior
2. Missing implementation scope
3. Test adequacy and edge-case coverage
4. Security and failure-path handling
5. Code quality and maintainability risks
6. Consistency with existing project patterns
7. Operational, migration, and dependency risks where applicable

## Severity Rubric

- BLOCKING: prevents execution, validation, installation, or required delivery
- CRITICAL: violates explicit requirements, creates security/data-loss risk, or makes the implementation materially incorrect
- MAJOR: leaves important behavior, edge cases, tests, maintainability, or integration contracts incomplete
- MINOR: localized quality issue, documentation gap, naming issue, or small missing guard that does not threaten correctness

## Output format

### [SEVERITY: blocking|critical|major|minor] — <title>
- File: <path>
- Lines: <line(s)>
- Issue: <description>
- Recommendation: <specific fix>

## Summary
- Score: PASS / PASS_WITH_RESERVATIONS / FAIL
- Score rationale: <1-2 concrete sentences>
- Blocking: <count>
- Critical: <count>
- Major: <count>
- Minor: <count>
- Brief assessment: <1-2 sentences on overall quality>
```
