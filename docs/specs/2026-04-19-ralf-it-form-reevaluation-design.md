# Spec: Re-evaluate `ralf-it` form — split into `ralf-review` + `ralf-implement` (agents-config-lu3.4)

## Summary

Split the current `ralf-it` skill into two explicit-invocation skills —
**`ralf-review`** (adversarial fresh-eyes passes over a target; read-only w.r.t. the
codebase) and **`ralf-implement`** (iterative same-working-copy implementation with
fresh-eyes cycles between passes). Push worktree and delivery responsibility
OUTSIDE both skills — they are inner methodology only. Teach
`implement-feature` / `fix-bug` formulas to dispatch `ralf-implement` selectively
based on a single `ralf:required` bead label set during brainstorming, with
`brainstorm-bead`'s existing `ralf-spec-review` step rewritten to dispatch
`ralf-review` against the spec document.

## Background

The current `ralf-it` skill:

- **Auto-matches aggressively** via its skill description, competing with bead-formula
  workflow.
- **Over-specifies outer workflow**: declares `superpowers:using-git-worktrees` and
  `superpowers:finishing-a-development-branch` as REQUIRED sub-skills.
- **Conflates two distinct behaviors** — iterative implementation AND adversarial
  review — into a single skill where the only separation is iteration number.
- **Docs/reality mismatch**: `src/plugins/beads/.claude/rules/beads.md` calls
  `implement-feature` / `fix-bug` "RALF-IT" — but their TOML is a linear completion
  gate with NO iteration, NO fresh-eyes subagent dispatch, NO convergence logic.
- **Peer-ban contradiction**: `src/plugins/beads/.agents/skills/implement-bead/SKILL.md`
  lists `ralf-it` alongside `executing-plans` / `subagent-driven-development` as a
  peer-banned skill. After this spec, RALF is dispatched BY formula steps — the
  ban must be reframed.

Beads domain expert counsel established that embedding RALF iteration as formula
primitives (conditional steps, loop-until, loop-range) fights the tool. RALF is
subagent-dispatch behavior — a quality behavior attached to specific formula
steps, not a workflow phase.

The two behaviors RALF blends naturally split along concern lines:

- **Review** — adversarial multi-pass fresh-eyes evaluation of a target
  (spec doc, design doc, code). Read-only w.r.t. the codebase. May write feedback
  to a doc. Applicable to specs, designs, or code.
- **Implement** — iterative refinement of code in the working copy. Writes code.
  Each cycle: implement → fresh-eyes review → evaluate → loop or converge.

Splitting yields cleaner consumers: `brainstorm-bead.ralf-spec-review` (already
exists) becomes a clean dispatch of `ralf-review`. `implement-feature.implement`
dispatches `ralf-implement` when warranted. Neither skill touches worktrees or PRs.

## Decision

**Two skills, both inner-methodology only**:

- **`ralf-review`**: dispatches one or more adversarial fresh-eyes subagents
  against a target. Read-only w.r.t. the codebase (may write feedback doc).
  Iterates up to a bounded cycle count; converges when findings are non-significant.
- **`ralf-implement`**: iterative same-working-copy implementation with
  fresh-eyes review passes between cycles. Writes code. Worktree is NOT its
  concern — caller arranges isolation if needed.

**Caller owns outer workflow**: worktree setup, PR creation, delivery. Whether
the caller is a bead formula step (formula owns the outer workflow) or a user
running `/ralf-implement …` (user arranges their own isolation, OR runs the
skill against their current working copy if that's what they want).

**Separation of concerns:**

- Beads track WHAT (unit of work, AC, state)
- Formulas encode workflow phases (intent → isolation → implement → gate → deliver → housekeep)
- Skills encode HOW quality behaviors work (`ralf-review` = adversarial multi-pass
  review; `ralf-implement` = iterative refinement loop)

**Signal design:**

- `ralf:required` label on a bead — canonical signal that formula steps should
  dispatch their corresponding RALF variant where applicable. Step-type routes:
  an `implement`-type step dispatches `ralf-implement`; a `review`-type step
  dispatches `ralf-review`. No separate labels per variant — the step is the
  disambiguator.
- `ralf:cycles=N` label — optional override for the invoked skill's
  `MAX_ITERATIONS`. Applies to whichever variant runs at the step.
- Labels are read at the step's dispatch boundary; changing labels
  mid-implementation has NO effect on the current run.
- **Setter contract (R15)**: any actor setting `ralf:cycles=N` MUST first
  `bd label remove` any existing `ralf:cycles=*` to prevent duplicates.
- Default values (`MAX_ITERATIONS`) live in each skill, not in formulas.

## Requirements

### R1. Split `ralf-it` into two skills; push outer-workflow OUT of both

- Create `src/user/.agents/skills/ralf-review/SKILL.md` — adversarial multi-pass
  review skill; read-only w.r.t. codebase; takes a target (spec/design/code)
  as argument
- Create `src/user/.agents/skills/ralf-implement/SKILL.md` — iterative
  same-working-copy implementation skill with fresh-eyes review cycles
- Retire `src/user/.agents/skills/ralf-it/` (delete directory OR leave only a
  short deprecation stub pointing at the successor skills — pick during rewrite)
- Neither skill requires `superpowers:using-git-worktrees` or
  `superpowers:finishing-a-development-branch` as sub-skills — worktree and
  delivery are the caller's concern
- Keep foreign-agent setup (`.ralf/` directory + Codex/Gemini dispatch) —
  inner tooling; distribute between the two skills as each needs it

### R2. Remove magnetism from both new skills

- Each skill's description begins with an explicit-invocation marker
  (e.g., "Explicit invocation only — …"); contains no auto-match trigger
  phrases ("use when executing", "use when implementing", "use when reviewing", etc.)
- Skill bodies include guard language: invoke only from explicit request,
  or from a formula step's dispatch contract — not as a peer of a bead workflow

### R3. Preserve RALF invariants in both skills

Four invariants apply to both skills, documented explicitly at the top of each:

- **Iteration** — multi-pass, bounded by `MAX_ITERATIONS`; not one-shot
- **Independence** — each cycle's subagent is brand-new (no prior cycle context);
  given the original target, not the previous cycle's summary
- **Adversarial posture** — seek gaps; never rubber-stamp
- **Convergence** — explicit termination when findings are non-significant OR
  budget exhausted

Additional per-skill preservation:

- **`ralf-review`**: the iteration pattern currently embedded in
  `brainstorm-bead.ralf-spec-review` (up to 2 cycles, early-exit on clean) is
  the reference
- **`ralf-implement`**: iteration-routing preserved (Codex iter 1, Gemini iter 2,
  pure Claude iter 3+); subagent-dispatch contract preserved (iteration count
  NOT disclosed; "may be incomplete" posture); foreign-agent failure degrades
  cleanly to pure fresh-eyes
- **Convergence escalation**:
  - **Standalone invocation**: each skill asks the user to continue if `MAX_ITERATIONS`
    is reached and last pass still found significant work
  - **Bead-driven invocation** (argument is a valid bead ID): skill calls
    `bd human <bead-id>` with a summary of remaining concerns; agent does NOT
    unilaterally extend

### R4. Argument/context handling — no worktree detection

Each skill accepts a target argument. Neither skill detects or creates worktrees:

- **`ralf-review`** — target can be: bead ID (reviews the bead's spec/description),
  file path (reviews the doc), or free text (reviews the described artifact).
  Treated as bead-driven if the argument is a valid bead ID AND `bd show <id>` succeeds.
- **`ralf-implement`** — target can be: bead ID (works against the bead's AC) or
  free text (works against a user-described goal). Same bead-driven detection.
- **No worktree precondition check**. If the caller wants isolation, the caller
  arranges it first. This preserves current standalone UX (the user's working
  copy is the working copy — no abort, no magic worktree creation).
- **Bead-driven mode** reads labels via `bd label list <id> --json`:
  - Presence check: `ralf:required` (gating happens at the formula step, not
    inside the skill — the formula decides to invoke)
  - `ralf:cycles=N`: positive integer, range 1..20
  - On multiple `ralf:cycles=N` labels (setter violated R15 or user manually
    added duplicates): warn, use skill default, recommend the user clean up
  - On malformed/out-of-range `ralf:cycles=N`: warn, use skill default

### R5. Single source of truth for defaults

- `MAX_ITERATIONS` default lives in each skill's SKILL.md; formulas never
  duplicate it. Each skill may pick its own default — `ralf-review` and
  `ralf-implement` need not share the number.
- Formulas read `ralf:cycles=N` label and pass to the invoked skill; skill
  falls back to its internal default when the label is absent
- Specific default values are skill-rewrite decisions, NOT spec decisions

### R6. `implement-feature.formula.toml` — `implement` step

Replace the current flat "Skills: superpowers:test-driven-development, then domain
skill" line with a label-driven skill-selection contract:

```
Check the bead's RALF signal BEFORE dispatching:

  bd label list {{bead-id}} --json

- If label `ralf:required` present:
    → invoke ralf-implement (pass {{bead-id}} as argument)
    ralf-implement owns the INNER quality loop only: iteration, independence,
    adversarial posture, convergence. It does NOT own worktree or PR creation
    — those belong to this formula. Optional cycle override via label
    `ralf:cycles=N`; skill default applies otherwise.

- Otherwise:
    → invoke superpowers:test-driven-development, then appropriate domain skill
      (e.g. typescript-developer)

Record the dispatch choice for audit:

  bd comments add {{bead-id}} "implement: dispatched <skill-name>"

Rules (apply to whichever skill is dispatched):
- Minimum viable implementation — write only what tests require
- No speculative features, no over-engineering
- No abstractions for hypothetical future requirements
```

**Mandated**: audit breadcrumb uses `bd comments add` (verified supported).
Do NOT use `bd update --notes` — replaces the spec.

### R7. `fix-bug.formula.toml` — `implement-fix` step

Identical label-driven skill-selection contract as R6. Consistency required.

### R8. `brainstorm-bead.formula.toml` — two changes

**R8a. Rewrite `ralf-spec-review` step to dispatch `ralf-review`:**

```
Dispatch ralf-review against this bead's spec document.

Skill: ralf-review
Target: {{bead-id}}

ralf-review runs bounded adversarial fresh-eyes cycles against the spec
(completeness, ambiguity, feasibility, consistency). It converges when
findings are non-significant or the cycle budget is exhausted. Review
the findings it reports; revise the spec if warranted (return to write-spec).
Run at most 2 spec review cycles before proceeding with remaining concerns
documented as open questions.
```

The step's behavior is preserved; what changes is that the inline review
logic is now encapsulated in the `ralf-review` skill, so the step body
shrinks to a dispatch.

**R8b. Add RALF triage to `finalize` step (before the existing label stamping):**

```
RALF triage — assess whether implementation warrants iterative refinement:

- If the spec touches any of: security-sensitive code, authentication/authorization,
  payment processing, data migration, architectural shift, multi-file coordinated
  change, or carries explicit user directive for RALF:
    → bd label add {{bead-id}} ralf:required
    → if a specific cycle count is warranted (differs from skill default):
        → bd label remove {{bead-id}} ralf:cycles=*   # R15: prevent duplicates
        → bd label add {{bead-id}} ralf:cycles=N

- Otherwise: proceed without RALF labels. Default implementation path is
  TDD + domain skill.
```

### R9. `resolve-pr-comments` boundary fix

- Remove all `ralf-it` invocation. Use `grep -n 'ralf-it'
  src/user/.agents/skills/resolve-pr-comments/SKILL.md` as authoritative
  locator (currently at lines 146, 281).
- Skill does NOT dispatch any RALF variant (neither `ralf-review` nor
  `ralf-implement`)
- Remove any implied or prescribed downstream steps (delivery, merge, cleanup)
- Scope the skill to pure PR comment resolution — nothing more
- If significant work on a comment is warranted, it is the caller's job to
  arrange that — the skill punts

### R10. `src/user/.claude/rules/delegation.md` rewrite

Current text: "Implementation → `ralf-it` skill (preferred for non-trivial work)"

Rewritten delegation rule reflects the two-skill split:

- Default implementation path: `superpowers:test-driven-development` +
  appropriate domain skill
- **`ralf-implement`** is opt-in via bead label `ralf:required` (bead-driven)
  OR explicit `/ralf-implement` invocation (standalone)
- **`ralf-review`** is used by formula review-type steps (e.g., `brainstorm-bead`'s
  `ralf-spec-review`) or invoked explicitly (`/ralf-review <target>`)
- Labels are read at the step's dispatch boundary; changing labels
  mid-implementation has NO effect on the current run
- Non-trivial is the NORM, not a trigger for RALF — most non-trivial work
  does not warrant `ralf-implement`

### R11. `src/plugins/beads/.claude/rules/beads.md` corrections

- Stop calling formulas "RALF-IT" (current text:
  `implement-feature — RALF-IT feature implementation`,
  `fix-bug — root-cause diagnosis + RALF-IT fix`). Corrected descriptions
  reflect the label-driven `ralf-implement` dispatch in the implement step;
  otherwise formulas are TDD + completion gate.
- ADD rows to the existing Bead Lifecycle and Labels table (do not replace
  the table — existing rows including `implementation-readied-session-<sid>`
  remain). Final expected table (6 rows):

  | Label | Set by | Meaning |
  |-------|--------|---------|
  | `brainstormed` | `brainstorm-bead.finalize` | Spec written and reviewed |
  | `implementation-ready` | `brainstorm-bead.finalize` | Ready for implement-bead / run-queue |
  | `implementation-readied-session-<sid>` | `brainstorm-bead.finalize` | Session marker for Route A gating |
  | `human` | Any agent via `bd human <id>` | Needs human attention |
  | `ralf:required` | `brainstorm-bead.finalize` (or manual) | Formula step dispatches `ralf-implement` (implement step) or `ralf-review` (review step) |
  | `ralf:cycles=N` | `brainstorm-bead.finalize` (or manual) | Override `MAX_ITERATIONS` (optional; skill default otherwise). Setters MUST remove any existing `ralf:cycles=*` first. |

### R12. `bd decision` record

- Title: "RALF split into ralf-review + ralf-implement; both inner-methodology only"
- Notes: Two-worlds collapsed to one family of two skills. `ralf-review`
  (read-only adversarial multi-pass) and `ralf-implement` (iterative
  same-working-copy implementation). Worktree / delivery are caller concerns,
  not skill concerns. Label-driven dispatch at formula steps via single
  `ralf:required` label; step type routes to the correct variant.
  `MAX_ITERATIONS` defaults owned by each skill. `ralf:cycles=N` duplicates
  prevented by setter-enforced cleanup (R15). Rationale: expert counsel
  established in-formula iteration primitives fight the tool; RALF is
  subagent-dispatch behavior; splitting mirrors the natural concern boundary;
  one skill family prevents drift; labels give queryable, compaction-surviving
  signal.

### R13. Subagent prompt template distribution

Current templates under `src/user/.agents/skills/ralf-it/`:

- `implementer-prompt.md` → move to `ralf-implement/`; strip the outer-workflow
  directive at line 7 (`isolation: "worktree"`)
- `fresh-eyes-prompt.md` → duplicate into both `ralf-implement/` and
  `ralf-review/` with appropriate scope (review-focus vs implement-cycle);
  strip `Work from: [worktree directory]` directives (currently at line 72 in
  the source)
- `foreign-eyes-prompt.md` → primarily for `ralf-implement/`; may be reused
  by `ralf-review/` if foreign-agent review of spec/design docs is desired
  (decide during rewrite)
- `foreign-agent-prompt.md` → move alongside foreign-eyes wherever it ends up

### R14. `implement-bead` skill peer-ban reconciliation

`src/plugins/beads/.agents/skills/implement-bead/SKILL.md:169` currently lists
`ralf-it` alongside `executing-plans` / `subagent-driven-development` as a
peer-banned skill. After this spec:

- **Remove** `ralf-it` from that peer-ban row entirely (leaving
  `executing-plans` and `subagent-driven-development`)
- **Add a NEW row** clarifying: `ralf-review` and `ralf-implement` are
  dispatched BY formula steps (not invoked as peers). Invocation as a peer
  of the bead workflow is forbidden; invocation from within a formula step's
  dispatch contract is REQUIRED when `ralf:required` label is set.
- Verify no other text in `implement-bead/SKILL.md` contradicts this

### R15. Setter-enforced `ralf:cycles=*` deduplication

Any actor (formula step, skill, user) setting `ralf:cycles=N` MUST first
remove any existing `ralf:cycles=*` label:

```
bd label remove <bead-id> ralf:cycles=*    # remove any existing
bd label add    <bead-id> ralf:cycles=N    # add the new one
```

This is the contract; consumers treat multiple coexisting `ralf:cycles=*`
labels as user error (warn + skill default, per R4). Beads labels are pure
strings — the system does NOT overwrite on re-add (verified empirically:
`bd label add bead test:foo=1` then `bd label add bead test:foo=2` leaves
both labels on the bead). Setter discipline is how we enforce "single effective
value."

## Out of scope

- Native beads formula iteration primitives (sub-formula, conditional steps,
  loop-until, loop-range) — expert counsel: fights the tool
- Cross-tool parity research for slash commands — skill form chosen, moot
- Command form of the RALF skills — both stay as skills
- Formula-level numeric defaults for `MAX_ITERATIONS`
- Per-cycle audit beads — molecule state + skill's final report suffice
- Upgrading the formula completion-gate `code-review` step to use `ralf-review`
  (potential future improvement; not in this bead's scope — file as a
  follow-on bead if desired)

## Open questions

None remaining. (Prior OQ1 resolved: `bd comments add` is supported, mandated
in R6. Prior OQ2 resolved: default values are skill-rewrite decisions, not a
spec decision. Prior OQ3 resolved: `ralf:cycles=N` without `ralf:required` is
a no-op — formula step only dispatches when `ralf:required` is present.
Duplicate-label concern resolved by R15 setter contract.)

## Design notes

- **Skill split** because review and implement are distinct concerns that
  currently share a body only because the original skill grew that way.
  Separating them yields clean consumers: `brainstorm-bead.ralf-spec-review`
  dispatches `ralf-review`; `implement-feature.implement` dispatches
  `ralf-implement` when labeled.
- **Worktree responsibility OUT of both skills** because worktree/isolation
  is a caller concern, not an inner-methodology concern. Bead formulas own
  their worktree step; standalone users own their own checkout state.
- **Single `ralf:required` label, step-type routes** because the formula
  step already knows whether it's an implement-type or review-type step.
  Separate labels would be redundant disambiguation.
- **Setter-enforced deduplication (R15)** because beads labels are strings —
  `bd label add` does NOT overwrite like key=value. Pushing the complexity to
  the setter keeps the consumer contract simple.
- **Label over variable** because labels are queryable (`bd label list`,
  `bd ready --label`), survive compaction, can be set/adjusted manually,
  and integrate with the existing lifecycle-label pattern.
- **Signal set during `brainstorm-bead.finalize`** because that's when the
  spec is assessed — pushing the decision to dispatch time invites per-agent
  prose-parsing drift.
- **Skills own their defaults** because `MAX_ITERATIONS` is intrinsic to the
  RALF mechanic, not to the workflow it runs in.
- **Audit via `bd comments add`**, NOT `bd update --notes`. Reason: `--notes`
  REPLACES notes (`brainstorm-bead.formula.toml:122` convention holds the spec).
- **Context-detection contract (R4)** is deterministic: bead-ID argument +
  `bd show` success. No worktree detection, no magic.
