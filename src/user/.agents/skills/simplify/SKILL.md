---
name: simplify
description: Review changed code for reuse, quality, and efficiency, then fix any issues found.
---
<!-- Source: /simplify slash command (sidekick injection — outside this repo); Drift policy: (C) accept periodic re-sync as known cost; Last sync: 2026-05-02 -->

# Simplify: Code Review and Cleanup

Review all changed files for reuse, quality, and efficiency. Fix any issues found.

## Operating Discipline

These rules govern HOW the simplify pass runs. They apply to every invocation regardless of dispatch shape — see Phase 2 for parallel vs. serial execution.

### Worktree scoping

- When the caller supplies a worktree path, operate inside that worktree — not the main tree.
- When no worktree is specified, operate in the current working directory.
- Never reach across worktree boundaries to "tidy up" unrelated trees.

### Apply vs. flag classification

Behavior preservation is the bright line. Classify every candidate finding before acting on it.

- **Apply directly** — behavior-preserving cleanups: renames, dead-code removal, trivially-redundant-branch collapse, clearly-duplicated helper extraction.
  - **renames** (variables, parameters, locals — when the new name is unambiguously clearer)
  - **dead-code removal** (unreferenced functions, imports, branches)
  - **trivially-redundant-branch collapse** (e.g. `if (x) return true; else return false;` → `return x;`)
  - **clearly-duplicated helper extraction** (only when ≥2 existing call sites already exhibit the duplication — see "No abstractions without ≥2 call sites" below)

- **Flag for review** — anything that could change observable behavior, including changes touching return values, side effects, error paths, exported APIs, or runtime ordering.
  - changes touching **return values**
  - changes touching **side effects**
  - changes touching **error paths**
  - changes touching **exported APIs** (signatures, types, public surface)
  - changes touching **runtime ordering** (sequencing, async timing, evaluation order)

When uncertain whether a change is behavior-preserving, flag it. The orchestrator decides; this skill does not.

### No abstractions without ≥2 call sites

Do not introduce new helpers, type aliases, or wrapper functions on speculation. New abstractions require **concrete duplication evidence** in the diff or surrounding code — at least two existing call sites that the abstraction would unify. "Might be reused later" is not evidence; YAGNI applies.

### Boundary rules

- **No scope creep into untouched files.** Review and modify only files in the diff (or recently-modified files when no diff exists).
- **Tests are not refactor targets.** Do not rewrite or restructure test files. Surface flaky or over-mocked tests in the summary instead.
- **No new dependencies.** Do not add packages, imports of new modules, or external services.
- **No commits, no pushes.** The orchestrator owns delivery. This skill edits files in place and reports.

### Memory persistence (with no-memory fallback)

When a recurring pattern surfaces (the same anti-pattern showing up across multiple files, or a project-specific convention worth remembering):

- **If the host runtime has a memory mechanism** (Claude project memory, managed `MEMORY.md`, Codex/Gemini equivalents), persist the pattern there so future simplify passes — and other agents in the project — benefit from the lesson. Do NOT use `bd remember` for this — that mechanism is for bead-tracker context, not agent/project memory.
- **If the host runtime has no persistent memory mechanism**, surface the recurring pattern in the final summary under a `Recurring pattern observed:` line so the user can record it manually. Do not silently drop the observation.

## Phase 1: Identify Changes

Run `git diff HEAD` to see all uncommitted changes (both staged and unstaged) since the last commit. If you only need one or the other, use `git diff` (unstaged only) or `git diff --staged` (staged only). If there are no git changes, review the most recently modified files that the user mentioned or that you edited earlier in this conversation.

## Phase 2: Review on Three Axes (Reuse, Quality, Efficiency)

If your runtime supports concurrent subagent dispatch in a single turn (Claude `Agent`, Codex `Task`, Gemini equivalents), dispatch the three reviewers in parallel. Otherwise, execute the three reviews serially in this context.

Both paths produce equivalent findings — the reviewer checklist runs identically; only the dispatch shape differs. Pass each reviewer the full diff so it has the complete context.

### Agent 1: Code Reuse Review

For each change:

1. **Search for existing utilities and helpers** that could replace newly written code. Look for similar patterns elsewhere in the codebase — common locations are utility directories, shared modules, and files adjacent to the changed ones.
2. **Flag any new function that duplicates existing functionality.** Suggest the existing function to use instead.
3. **Flag any inline logic that could use an existing utility** — hand-rolled string manipulation, manual path handling, custom environment checks, ad-hoc type guards, and similar patterns are common candidates.

### Agent 2: Code Quality Review

Review the same changes for hacky patterns:

1. **Redundant state**: state that duplicates existing state, cached values that could be derived, observers/effects that could be direct calls
2. **Parameter sprawl**: adding new parameters to a function instead of generalizing or restructuring existing ones
3. **Copy-paste with slight variation**: near-duplicate code blocks that should be unified with a shared abstraction
4. **Leaky abstractions**: exposing internal details that should be encapsulated, or breaking existing abstraction boundaries
5. **Stringly-typed code**: using raw strings where constants, enums (string unions), or branded types already exist in the codebase
6. **Unnecessary JSX nesting**: wrapper Boxes/elements that add no layout value — check if inner component props (flexShrink, alignItems, etc.) already provide the needed behavior
7. **Nested conditionals**: ternary chains (`a ? x : b ? y : ...`), nested if/else, or nested switch 3+ levels deep — flatten with early returns, guard clauses, a lookup table, or an if/else-if cascade
8. **Unnecessary comments**: comments explaining WHAT the code does (well-named identifiers already do that), narrating the change, or referencing the task/caller — delete; keep only non-obvious WHY (hidden constraints, subtle invariants, workarounds)

### Agent 3: Efficiency Review

Review the same changes for efficiency:

1. **Unnecessary work**: redundant computations, repeated file reads, duplicate network/API calls, N+1 patterns
2. **Missed concurrency**: independent operations run sequentially when they could run in parallel
3. **Hot-path bloat**: new blocking work added to startup or per-request/per-render hot paths
4. **Recurring no-op updates**: state/store updates inside polling loops, intervals, or event handlers that fire unconditionally — add a change-detection guard so downstream consumers aren't notified when nothing changed. Also: if a wrapper function takes an updater/reducer callback, verify it honors same-reference returns (or whatever the "no change" signal is) — otherwise callers' early-return no-ops are silently defeated
5. **Unnecessary existence checks**: pre-checking file/resource existence before operating (TOCTOU anti-pattern) — operate directly and handle the error
6. **Memory**: unbounded data structures, missing cleanup, event listener leaks
7. **Overly broad operations**: reading entire files when only a portion is needed, loading all items when filtering for one

## Phase 3: Aggregate and Fix

Wait for all three reviewers to complete (or, in serial mode, finish all three reviews). Aggregate their findings and fix each issue directly, respecting the apply-vs-flag classification in Operating Discipline. If a finding is a false positive or not worth addressing, note it and move on — do not argue with the finding, just skip it.

### Output format

Produce a terse summary with the following structure (omit any section that does not apply):

- **Simplifications applied** — list each item with `path:line` and a one-line "what".
- **Flagged for review** — list each item with `path:line`, the candidate change, and the reason it was held back (touches return values, error paths, exported API, runtime ordering, etc.).
- **None warranted** — when no changes are needed, say so explicitly. Do not invent work.

If a recurring pattern was observed:

- **Host has memory mechanism** — persist the pattern via the host's memory tool, then append:
  `> Memory updated: <one-line description of the pattern persisted>`
- **Host has no memory mechanism** — append a `Recurring pattern observed:` line in the summary describing the pattern so the user can record it manually.
