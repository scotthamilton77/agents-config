# ralf-implement foreign-agent prompt template

Template for foreign CLI review instruction files used by `ralf-implement`.

Written to `.ralf/{session_id}/prompt-{agent}-{timestamp}.md` before foreign review execution.

## Template

```markdown
# External Implementation Review Request

You are reviewing repository changes against the original implementation target.

## Constraints

- Read-only review
- Do not modify files
- Output structured findings to stdout

## Definition of Done

{dod}

## Original Target

{spec}

## Review dimensions

1. Correctness against target behavior
2. Missing implementation scope
3. Test adequacy and edge-case coverage
4. Security and failure-path handling
5. Code quality and maintainability risks

## Output format

### [SEVERITY: critical|major|minor|nit] — <title>
- File: <path>
- Lines: <line(s)>
- Issue: <description>
- Recommendation: <specific fix>

## Summary
- Overall: PASS / PASS_WITH_CONCERNS / NEEDS_WORK
- Critical: <count>
- Major: <count>
- Minor: <count>
- Nits: <count>
```
