# Spec: Re-evaluate `ralf-it` form (agents-config-lu3.4)

## Summary

Convert `ralf-it` from a magnetic auto-matching, outer-workflow-embedded skill into an
explicit-invocation, inner-loop-only skill, and teach `implement-feature` / `fix-bug`
formulas to dispatch RALF selectively based on bead labels set during brainstorming.
Two worlds collapse to one skill with one source of truth for iteration defaults.

## Background

`ralf-it` today:

- **Auto-matches aggressively** via its skill description, competing with bead-formula
  workflow and getting pulled in even when a formula should own the flow.
- **Over-specifies outer workflow**: declares `superpowers:using-git-worktrees` and
  `superpowers:finishing-a-development-branch` as REQUIRED sub-skills, conflicting
  with bead formulas that already own isolation and delivery.
- **Docs/reality mismatch**: `src/plugins/beads/.claude/rules/beads.md` describes
  `implement-feature` / `fix-bug` formulas as "RALF-IT feature implementation" and
  "RALF-IT fix" — but their TOML encodes a linear completion gate with NO iteration,
  NO fresh-eyes subagent dispatch, NO convergence logic.
- **Peer-ban contradiction**: `src/plugins/beads/.agents/skills/implement-bead/SKILL.md`
  lists `ralf-it` alongside `executing-plans` / `subagent-driven-development` as a
  peer-banned skill. After this spec lands, `ralf-it` is NOT a peer — it is dispatched
  BY the formula's `implement` step. Leaving the peer-ban in place reintroduces the
  very friction this bead eliminates.

Beads domain expert counsel established that embedding RALF iteration as formula
primitives (conditional steps, loop-until, loop-range) fights the tool: conditions
are cook-time only, loops lack counters or early-exit, and redundant state tracking
emerges. RALF is fundamentally subagent-dispatch behavior — a quality behavior
attached to the `implement` step, not a workflow phase.

## Decision

Two-worlds model collapsed to **one skill**:

- **Bead-driven invocation**: `ralf-it` invoked from inside a formula step
  (`implement` in `implement-feature`, `implement-fix` in `fix-bug`), reading bead
  labels for gating.
- **Standalone invocation**: same `ralf-it` invoked directly (from user prompt
  outside bead flow) with interactive iteration prompt and caller-arranged worktree.

**Separation of concerns:**

- Beads track WHAT (unit of work, AC, state)
- Formulas encode workflow phases (intent → isolation → implement → gate → deliver → housekeep)
- Skills encode HOW quality behaviors work (RALF inner loop)

**Signal design:**

- `ralf:required` label — canonical signal at implement-step dispatch time
- `ralf:cycles=N` label — optional override for `MAX_ITERATIONS`
- Set during `brainstorm-bead.finalize` step (high-stakes assessment moment), not
  at dispatch time
- `MAX_ITERATIONS` default lives ONLY in the skill — formulas never duplicate it
- Labels are read at the `implement`-step dispatch boundary; changing labels
  mid-implementation has NO effect on the current run

## Requirements

### R1. Strip outer-workflow from `ralf-it`

- Remove `superpowers:using-git-worktrees` as REQUIRED sub-skill (current Step 3)
- Remove `superpowers:finishing-a-development-branch` as REQUIRED post-step
  (current Step 9 epilogue)
- Remove the "RALF-IT replaces `subagent-driven-development` / `executing-plans`"
  claim (beads partnership contract owns that boundary now)
- Keep foreign-agent setup (Step 3b — `.ralf/` directory + Codex/Gemini dispatch)
  — inner tooling for review subagents

### R2. Remove magnetism from `ralf-it`

- Rewrite description to remove auto-match trigger phrases (e.g., "Use when
  executing tasks, implementing plans…")
- Description must begin with an explicit-invocation marker
  (e.g., "Explicit invocation only — …") so auto-match scanners do not pull it in
- Add guard language in the skill body: do not invoke from inside a bead-driven
  molecule step as a peer of the formula — invoke only from the formula's dispatch
  contract, or standalone

### R3. Preserve RALF invariants (both modes)

- Four invariants documented explicitly at top of skill:
  iteration / independence / adversarial / convergence
- Iteration-routing table preserved (Codex iter 1, Gemini iter 2, pure Claude iter 3+)
- Subagent-dispatch contract preserved (original spec given, iteration count NOT
  disclosed, "may be incomplete" posture)
- Foreign-agent failure degradation preserved (cleanly falls back to pure fresh-eyes)
- **Convergence-escalation preserved in BOTH modes**:
  - **Standalone**: current "ask user to continue" clause kept
  - **Bead-driven**: when `MAX_ITERATIONS` reached and last pass still found
    significant work, skill calls `bd human <bead-id>` with a summary of remaining
    concerns (agent cannot unilaterally extend; user intervention is the path)

### R4. Contextual awareness

- **Context-detection contract**: the skill treats invocation as bead-driven if
  and only if the first argument parses as a bead ID AND `bd show <id>` succeeds.
  Any other invocation (no argument, free-text argument, bd-show failure) is
  standalone.
- **Bead-driven mode**:
  - Read labels via `bd label list <id> --json`
  - Presence check for `ralf:required`
  - Integer parse for `ralf:cycles=N` (positive integer, range 1..20)
  - On multiple `ralf:cycles=N` labels: use the lowest N (conservative)
  - On malformed / out-of-range `ralf:cycles=N`: warn and fall through to skill default
  - Skip interactive `MAX_ITERATIONS` prompt
  - Defer worktree / PR / delivery to surrounding formula
  - Skip the announcement line (formula step is the boundary — no user-facing
    re-introduction needed)
- **Standalone mode**:
  - Keep interactive "How many iterations?" prompt from current Step 2
  - **Precondition check**: skill verifies it is running inside a worktree (or on
    a non-trunk branch). If not, abort with a message directing the user to
    `superpowers:using-git-worktrees` first. Skill no longer auto-creates worktree.
  - Caller is responsible for delivery post-RALF

### R5. Single source of truth for defaults

- `MAX_ITERATIONS` default lives in `ralf-it` skill, not in formulas
- Formulas read `ralf:cycles=N` label from bead and pass through; skill falls
  back to its internal default when label absent
- The specific default value is decided during the skill rewrite
  (R1–R5 implementation), NOT by this spec. The spec's concern is that ONE place
  holds the number; the rewrite picks which number

### R6. `implement-feature.formula.toml` — `implement` step

Replace the current "Skills: superpowers:test-driven-development, then domain
skill" line with a label-driven skill-selection contract:

```
Check the bead's RALF signal BEFORE dispatching:

  bd label list {{bead-id}} --json

- If label `ralf:required` present:
    → invoke ralf-it (pass {{bead-id}} as argument)
    ralf-it owns the INNER quality loop only: iteration, independence,
    adversarial posture, convergence. It does NOT own worktree or PR
    creation — those belong to this formula. Optional cycle override
    via label `ralf:cycles=N`; skill default applies otherwise.

- Otherwise:
    → invoke superpowers:test-driven-development, then appropriate domain
      skill (typescript-developer, backend-developer, etc.)

Record the dispatch choice for audit:

  bd comments add {{bead-id}} "implement: dispatched <skill-name>"

Rules (apply to whichever skill is dispatched):
- Minimum viable implementation — write only what tests require
- No speculative features, no over-engineering
- No abstractions for hypothetical future requirements
```

**Mandated**: audit breadcrumb uses `bd comments add` (verified supported).
Do NOT use `bd update --notes` — that REPLACES the spec document held at
`brainstorm-bead.formula.toml:122`.

### R7. `fix-bug.formula.toml` — `implement-fix` step

Apply the identical label-driven skill-selection contract from R6. Consistency
between the two formulas is required.

### R8. `brainstorm-bead.formula.toml` — `finalize` step

Add RALF triage to the finalize step BEFORE the existing `brainstormed` /
`implementation-ready` label stamping:

```
RALF triage — assess whether implementation warrants iterative refinement:

- If the spec touches any of: security-sensitive code, authentication/authorization,
  payment processing, data migration, architectural shift, multi-file coordinated
  change, or carries explicit user directive for RALF:
    → bd label add {{bead-id}} ralf:required
    → if a specific cycle count is warranted (differs from skill default):
        bd label add {{bead-id}} ralf:cycles=N

- Otherwise: proceed without RALF labels. Default implementation path is
  TDD + domain skill.
```

### R9. `resolve-pr-comments` boundary fix

- Remove all `ralf-it` invocation (`src/user/.agents/skills/resolve-pr-comments/SKILL.md`
  lines 146 and 281)
- Remove any implied or prescribed downstream steps (delivery, merge, cleanup)
- Scope the skill to pure PR comment resolution — nothing more
- If significant work on a comment is warranted, it is the caller's job to
  arrange that — the skill punts, it does not dispatch RALF

### R10. `src/user/.claude/rules/delegation.md` rewrite

Current text: "Implementation → `ralf-it` skill (preferred for non-trivial work)"

New text reflects two-worlds:

- Default implementation path: `superpowers:test-driven-development` +
  appropriate domain skill
- RALF is opt-in via bead label `ralf:required` (bead-driven) or explicit
  `/ralf-it` invocation (standalone)
- The label is read at the `implement`-step dispatch boundary; changing the
  label mid-implementation has NO effect on the current run
- Non-trivial is the NORM, not a trigger for RALF — most non-trivial work
  does not warrant RALF

### R11. `src/plugins/beads/.claude/rules/beads.md` corrections

- Stop describing formulas as "RALF-IT" (current text:
  `implement-feature — RALF-IT feature implementation`,
  `fix-bug — root-cause diagnosis + RALF-IT fix`). Corrected descriptions
  reflect the label-driven RALF dispatch in the implement step; otherwise
  formulas are TDD + completion gate.
- ADD rows to the existing Bead Lifecycle and Labels table (do not replace
  the table — existing rows including `implementation-readied-session-<sid>`
  remain):

  | Label | Set by | Meaning |
  |-------|--------|---------|
  | `ralf:required` | `brainstorm-bead.finalize` (or manual) | Implement step dispatches `ralf-it` instead of TDD default |
  | `ralf:cycles=N` | `brainstorm-bead.finalize` (or manual) | Override `MAX_ITERATIONS` (optional; skill default otherwise) |

### R12. `bd decision` record

Record a decision with rationale:

- Title: "RALF as quality behavior, not workflow phase"
- Notes: Two-worlds collapsed to one skill. Label-driven dispatch at formula
  `implement` step. `MAX_ITERATIONS` default owned by skill. Rationale: expert
  counsel established in-formula iteration primitives fight the tool; RALF is
  fundamentally subagent-dispatch behavior; one skill prevents drift; labels
  give queryable, compaction-surviving signal.

### R13. Subagent prompt template audit

Review the four template files under `src/user/.agents/skills/ralf-it/`:

- `implementer-prompt.md`
- `fresh-eyes-prompt.md`
- `foreign-eyes-prompt.md`
- `foreign-agent-prompt.md`

Check for outer-workflow references (worktree setup, PR instructions) and remove
them. Keep inner-loop and review contracts. Expect most edits to land in
`foreign-eyes-prompt.md` / `foreign-agent-prompt.md`; `implementer-prompt.md` and
`fresh-eyes-prompt.md` are likely no-ops or minor.

### R14. `implement-bead` skill peer-ban reconciliation

`src/plugins/beads/.agents/skills/implement-bead/SKILL.md` currently lists
`ralf-it` alongside `executing-plans` / `subagent-driven-development` as a
peer-banned skill. After this spec lands:

- `ralf-it` is NOT a peer of the bead workflow — it is dispatched BY the
  formula's `implement` step (R6/R7)
- Update `implement-bead`'s guidance to: "`ralf-it` invocation as a peer of
  the formula is forbidden; `ralf-it` invocation as part of the formula's
  `implement` step is REQUIRED when `ralf:required` label is set on the bead"
- Verify no other text in `implement-bead/SKILL.md` contradicts this

## Out of scope

- Native beads formula iteration primitives (sub-formula, conditional steps,
  loop-until, loop-range) — expert counsel: fights the tool
- Cross-tool parity research for slash commands — skill form chosen, moot
- Command form of `ralf-it` — skill stays a skill
- Formula-level numeric defaults for `MAX_ITERATIONS`
- Per-cycle audit beads — molecule state + skill's final report deliver the
  same visibility at a fraction of the cost

## Open questions

None remaining. (Prior OQ1 resolved: `bd comments add` is supported, mandated
in R6. Prior OQ2 resolved: default value is a skill-rewrite decision, not a
spec decision. Prior OQ3 resolved: `ralf:cycles=N` without `ralf:required`
treated as malformed — skill warns and uses default; see R4.)

## Design notes

- **Two-worlds collapsed** because maintaining two implementations of RALF
  mechanics (skill + in-formula) risks drift. One skill, two callers.
- **Label over variable** because labels are queryable (`bd label list`,
  `bd ready --label`), survive compaction, can be set/adjusted manually at
  any time, and integrate with the existing lifecycle-label pattern
  (`brainstormed`, `implementation-ready`, `implementation-readied-session-<sid>`).
- **Signal set during `brainstorm-bead.finalize`** because that's when the
  spec is assessed — pushing the decision to dispatch time invites per-agent
  prose-parsing drift.
- **Skill owns default** because `MAX_ITERATIONS` is intrinsic to the RALF
  mechanic, not to the workflow it runs in. Duplicate defaults = split-brain bug.
- **Audit via `bd comments add`**, NOT `bd update --notes`.
  Reason: `--notes` REPLACES notes; `bd brainstorm-bead.formula.toml:122`
  convention holds the spec in notes.
- **Context-detection contract (R4)** is deterministic and testable: bead-ID
  argument + `bd show` success. Skills/formulas can verify compliance without
  running the RALF loop.
