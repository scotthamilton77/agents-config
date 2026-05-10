# Superpowers Audit & Skill Rationalization — Design Spec

**Bead:** agents-config-rq67
**Date:** 2026-05-10
**Status:** Approved for implementation

## Context

Superpowers plugin is at v5.1.0. During an audit against the release notes (v4.0.0 through v5.1.0), two classes of reference errors were found in this repo's templates and agent files:

1. **Broken references** — skill names that no longer exist as standalone superpowers skills (removed or bundled in v4.0.0)
2. **Wrong-namespace references** — in-repo skills incorrectly prefixed with `superpowers:` when they live in this repo's `src/user/.agents/skills/`

Additionally, two in-repo skills duplicate content now bundled inside superpowers and should be retired.

## Scope

### 1. Fix broken superpowers references

`superpowers:root-cause-tracing` was removed as a standalone skill in v4.0.0 and bundled as a reference doc inside `superpowers:systematic-debugging`. All references must point to `superpowers:systematic-debugging` instead.

**Files to update:**
- `src/plugins/beads/.agents/agents/bead-implementor.md`
- `src/plugins/beads/.agents/agents/bug-diagnoser.md`
- `src/user/.agents/skills/test-review/SKILL.md`
- `src/user/.agents/skills/bugfix/SKILL.md`

### 2. Fix wrong-namespace in-repo skill references

The following skills live in `src/user/.agents/skills/` — not in the superpowers plugin. The `superpowers:` prefix must be removed.

| Wrong reference | Correct reference | Files |
|---|---|---|
| `superpowers:testing-anti-patterns` | `superpowers:test-driven-development` | `tdd-red-team.md`, `tdd-green-team.md`, `bead-implementor.md` |
| `superpowers:writing-unit-tests` | `writing-unit-tests` | `tdd-red-team.md`, `bead-implementor.md` |
| `superpowers:wait-for-pr-comments` | `wait-for-pr-comments` | `src/plugins/beads/.claude/rules/delivery.md` |
| `superpowers:reply-and-resolve-pr-threads` | `reply-and-resolve-pr-threads` | `src/plugins/beads/.claude/rules/delivery.md` |

Note: `testing-anti-patterns` redirects to `superpowers:test-driven-development` rather than the bare name because the in-repo skill is being retired (Section 3).

### 3. Retire in-repo skills that duplicate bundled superpowers content

Two in-repo skills duplicate content that superpowers v4.0.0 bundled into `systematic-debugging/` and `test-driven-development/` respectively:

**`testing-anti-patterns`** (`src/user/.agents/skills/testing-anti-patterns/`)
- Superpowers equivalent: `test-driven-development/testing-anti-patterns.md`
- Process: diff content; if nothing unique, delete the skill directory and update any remaining references to `superpowers:test-driven-development`

**`condition-based-waiting`** (`src/user/.agents/skills/condition-based-waiting/`)
- Superpowers equivalent: `systematic-debugging/condition-based-waiting.md` + `condition-based-waiting-example.ts`
- Process: diff content; if nothing unique, delete the skill directory and update any remaining references to `superpowers:systematic-debugging`

If either skill contains content not present in the superpowers bundle, that unique content must be either contributed upstream or absorbed into another in-repo skill before deletion.

## Out of Scope

- Upgrading superpowers beyond 5.1.0 (already current)
- Auditing beads-plugin skills (`create-bead`, `implement-bead`, `run-queue`, `start-bead`) — these have no superpowers equivalents and are not affected
- Auditing in-repo skills with no superpowers analogs (`merge-guard`, `ralf-implement`, `ralf-review`, `self-improving-agent`, `simplify`, `verify-checklist`, `optimize-agents-md`, `test-review`, `reply-and-resolve-pr-threads`, `wait-for-pr-comments`, `writing-unit-tests`) — correct references, keep as-is

## Acceptance Criteria

- No file in `src/` references `superpowers:root-cause-tracing`
- No file in `src/` references `superpowers:testing-anti-patterns`, `superpowers:writing-unit-tests`, `superpowers:wait-for-pr-comments`, or `superpowers:reply-and-resolve-pr-threads`
- `src/user/.agents/skills/testing-anti-patterns/` is deleted (or unique content extracted first)
- `src/user/.agents/skills/condition-based-waiting/` is deleted (or unique content extracted first)
- All modified files render valid markdown and pass any install dry-run checks
