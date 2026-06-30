# PR Review / Merge Policy — config-driven wait & merge gate

- **Date**: 2026-06-30
- **Bead**: agents-config-wgclw.14 (M0)
- **Status**: draft
- **Related**: agents-config-7bk.12 (brainstorm-time review-requirements authoring),
  agents-config-abn9.8.19 (prgroom reviewer seeding), agents-config-ukzs (overlap external waits),
  agents-config-7bk.17 (key-naming alignment)

## Problem

The delivery flow currently treats "wait for PR review feedback" as an
unconditional step and treats "merge" as always requiring explicit human
authorization. Neither is configurable per project. On a repo where no
automated reviewer (Copilot) is enabled, the agent polls for feedback that
will never arrive; on a repo where a clean automated review is sufficient to
ship, a human is still forced into the loop for no judgment reason.

A configuration surface for this already exists but is **orphaned**:
`project-config.toml` declares `[review-requirements]` with `copilot-required`
and `human-approvers-required`, citing `bead-pipeline-architecture.md §5.1` —
a doc that was quarantined to `archive/docs/specs/` ("cleaner starting state").
No source file reads these keys today (`grep -rl project-config.toml src/` =
0 hits). The schema is correct but dead.

## Intent of the existing keys (recovered from the archived design)

The archived `bead-pipeline-architecture.md` defines a per-stage pipeline
`… → create-pr → review-cycle → merge-or-handoff` where:

- `[review-requirements]` is "Read by review-cycle" — the per-project defaults
  for the review-feedback stage.
- `copilot-required` → the review stage polls/waits for Copilot.
- `human-approvers-required` → feeds the merge-vs-handoff decision.
- Per-bead overrides existed as labels: `review-exit-copilot-only` and
  `review-exit-human-approvers-<n>`.

These keys are therefore **explicitly PR-review settings**. This spec revives
their semantics and gives them live consumers.

## Desired outcome

A project-level policy — overridable per bead — that resolves two independent
decisions, honored by the live delivery path:

| Decision | Driven by | Enforcement point |
|---|---|---|
| **Wait decision** — poll for automated review, or not? | `copilot-required` (+ `review-exit-copilot-only`) | `wait-for-pr-comments` |
| **Merge decision** — auto-merge, or hand off to human? | `human-approvers-required` (+ `review-exit-human-approvers-<n>`) | `merge-guard` |

## Two states, not one: eligible vs. authorized

Two distinct questions get conflated if not named separately:

- **Merge-eligible** — is the PR in a state where merging is safe? (state)
- **Merge-authorized** — may the agent actually invoke the merge action right
  now? (action permission)

`human-approvers-required` and the clean-review predicate determine
*eligibility*. They do **not**, by themselves, authorize the agent to merge —
except the single carved-out case (`required_human_approvers == 0` and the
predicate holds), where policy *is* the authorization (see the law amendment
below). In every other case the agent still needs an explicit in-conversation
merge instruction before invoking `gh pr merge`. A human clicking "Approve" on
the PR satisfies the *review* requirement — the PR becomes eligible — but that
is not the same speech act as telling the agent to merge it, and does not
substitute for the instruction. (This mirrors prgroom's own design: its
`auto_merge_eligible` contract is explicitly a state flag, with "the actual
merge gate and policy overlay … owned by future beads" — this bead is one of
those beads, for the manual/chat path.)

## Behavior matrix

| `copilot-required` | `human-approvers-required` | Wait? | Merge? |
|---|---|---|---|
| true | 0 | Poll Copilot, fix, resolve | Auto-merge **iff** clean-review predicate holds |
| true | ≥1 | Poll Copilot, fix, resolve | Eligible once approved; agent merges only on an explicit in-session instruction |
| false | 0 | No poll | Auto-merge iff (threads resolved ∧ required CI green) |
| false | ≥1 | No poll | Eligible once approved; agent merges only on an explicit in-session instruction |

### Clean-review predicate (gates auto-merge)

`wait-for-pr-comments`/`merge-guard` (the manual/chat path) and
`monitor-pr`/`prgroom` (the deterministic CLI-driven grooming loop) are
parallel mechanisms for reaching a "PR is ready" state — neither currently
calls the other. prgroom already owns a more rigorous four-gate
`auto_merge_eligible` contract (`docs/architecture/prgroom/design.md` §4.5:
`phase_is_quiesced` ∧ `last_error_clear` ∧ `no_blocker_items` ∧
`human_review_satisfied`), exposed read-only via `prgroom status --json`.
Reinventing a parallel, looser predicate in `merge-guard` would let the two
drift apart. `merge-guard`'s eligibility check therefore resolves the
predicate as:

1. **PR has prgroom state** (`prgroom status <pr> --json` succeeds) — use its
   `auto_merge_eligible` boolean directly. prgroom's `human_review_satisfied`
   gate (§4.4: a `human-approved` label or a non-bot `APPROVED` review)
   already folds in human-approval semantics; this resolver's
   `required_human_approvers` policy maps onto whether that gate is required
   at all (see Live consumer wiring).
2. **No prgroom state** (PR handled purely through `wait-for-pr-comments`) —
   fall back to a local check: Copilot review complete (if
   `copilot-required`) ∧ all review threads resolved ∧ no FIX-class items
   outstanding ∧ required CI checks green. This is the archived `quiesced`
   terminal state, reproduced locally for the prgroom-less path. This is the
   gate this work **adds** to `check-merge-eligibility.sh` (today it only
   checks the first three components).

**Caveat**: agents-config-abn9.8.19 documents that `state.reviewers` is never
seeded in prgroom today, so `_g_reviewers` is vacuously true in practice — the
Copilot-quiescence-wait portion of `auto_merge_eligible` is currently a no-op
until that bead lands. The other three gates (`phase_is_quiesced`,
`last_error_clear`, `no_blocker_items`) are unaffected. Consuming the contract
here does not fix that gap; it is read-only.

## Architecture

### Decision: a tested policy-resolver helper (not inline-per-skill)

Per the repo's "code over prose / Python over Bash for testable logic"
principle, resolution lives in one code unit rather than being duplicated
across the three consuming skills.

**Contract (designed before the body):**

```
resolve_policy(
    project_config: ReviewRequirements,   # parsed [review-requirements]
    bead_labels: list[str],               # for per-bead overrides
) -> ReviewMergePolicy

ReviewMergePolicy = {
    wait_for_copilot: bool,
    required_human_approvers: int,
    merge_mode: "auto" | "handoff",       # "auto" only when required_human_approvers == 0
}
```

- Outside-world inputs (config, labels) are passed as arguments — no module
  globals.
- Output is a typed value, not an untyped dict, at the boundary.
- The predicate evaluation (is the PR *clean*?) is a **separate** concern owned
  by `merge-guard`'s eligibility check (which defers to `prgroom status --json`
  when available — see Clean-review predicate); the resolver decides *policy*,
  the eligibility check decides *state*. The merge proceeds iff
  `merge_mode == "auto" AND clean_predicate()`.

### Resolution precedence

`per-bead label` > `project-config.toml [review-requirements]` > built-in default.

- `review-exit-copilot-only` → forces `wait_for_copilot = true` **regardless**
  of the project's `copilot-required` setting (the label's whole point is to
  wait specifically for Copilot — it must not silently degrade to no review
  when a project has `copilot-required = false`) and sets
  `required_human_approvers = 0` (Copilot-only exit).
- `review-exit-human-approvers-<n>` → sets `required_human_approvers = n`.
  Mutually exclusive with `review-exit-copilot-only`; presence of both is a
  resolver error (fail loud).

Built-in defaults (when key/section absent): `copilot-required = true`,
`human-approvers-required = 1` (conservative — no surprise self-merges for
repos that never set the section).

### Live consumer wiring

1. **`wait-for-pr-comments`** — call the resolver at entry. When
   `wait_for_copilot == false`, skip the Copilot poll and emit a terminal
   "no automated reviewer configured — PR awaiting human review" status; do not
   block. (Reply/resolve still runs if human threads already exist.)
2. **`merge-guard`** — call the resolver in its eligibility step. Gate:
   - `merge_mode == "handoff"` → never auto-proceed without an explicit
     in-session human instruction to merge. A human PR approval (or prgroom's
     `human_review_satisfied`) makes the PR *eligible* but is not itself
     authorization — see Two states, not one.
   - `merge_mode == "auto"` → proceed **iff** the clean-review predicate holds
     (prgroom's `auto_merge_eligible` when available, else the extended
     `check-merge-eligibility.sh` fallback).
3. **`finishing-a-development-branch`** — unchanged for PR creation; it hands
   off to `merge-guard` for the gated merge decision.

### The merge-authorization law amendment

The standing global rule ("merge requires explicit human authorization") is
amended with a single carve-out, worded to prevent misreading:

> Merging requires explicit human authorization, **unless** the resolved
> review/merge policy yields `required_human_approvers == 0` **and** the
> clean-review predicate holds — in which case the configured policy *is* the
> authorization. In every other case, the explicit-authorization rule stands.

Applied to the merge-authorization content in the delivery and completion-gate
rules and the `<constraints>` block (referenced by concept, since these are
installed assets flattened at install time — no file-path citations in the
amended text).

## Deliverables

1. **HLD** — `docs/architecture/review-merge-policy/` (`index.md` + the
   two-decision model, the resolver contract, the clean-review predicate /
   state machine). Evergreen. Replaces the stale `§5.1` toml reference.
2. **Policy-resolver helper** — code + unit tests (the typed resolver above).
3. **Eligibility-check extension** — `check-merge-eligibility.sh` gains (a) a
   prgroom-aware path that shells out to `prgroom status --json` and uses
   `auto_merge_eligible` directly when present, and (b) the required-CI-green
   gate for the no-prgroom fallback path.
4. **Live wiring** — `wait-for-pr-comments`, `merge-guard`,
   `finishing-a-development-branch`.
5. **Per-bead label parsing** — `review-exit-copilot-only`,
   `review-exit-human-approvers-<n>` consumed by the resolver. Boundary with
   `7bk.12`: this bead owns label **consumption**; `7bk.12` owns label
   **authoring** at brainstorm time. Add a dependency edge.
6. **Law amendment** — merge-authorization carve-out (above).
7. **toml cleanup** — fix the stale `§5.1` reference (point at the new HLD);
   set agents-config's own defaults deliberately:
   `copilot-required = true`, `human-approvers-required = 0` (this repo
   auto-merges on a clean automated review — a deliberate, recorded choice).

## Testing

- **Resolver unit tests** — the full behavior matrix, precedence
  (label > config > default), and override edge cases (both labels present →
  error; malformed `-<n>`).
- **Eligible-vs-authorized**: a PR with `required_human_approvers >= 1` that
  has a human approval but no explicit in-session merge instruction must
  resolve to "do not merge."
- **Eligibility-check** — test both predicate paths: prgroom-present (mock
  `prgroom status --json` output, assert `auto_merge_eligible` is used
  directly) and prgroom-absent (the added CI-green gate: green / red / no-CI).
- **Skills** — kept thin enough to verify via the existing skill smoke-test
  suite.

## Risks / notes

- **Highest blast radius is the law amendment.** Wording must make auto-merge
  conditional and non-default; a careless edit reads as "agents merge freely."
- **agents-config self-auto-merges** under its chosen defaults. Acceptable and
  intended; called out so it is never mistaken for an accident.
- The autonomous-pipeline `review-cycle` / `merge-or-handoff` stages remain
  future work; this spec wires the **live** skills, but the resolver contract
  is shaped so those stages can reuse it unchanged.
- **Two clean-review predicates exist** (prgroom's `auto_merge_eligible` and
  `merge-guard`'s local fallback) until prgroom adoption is universal. They
  must stay equivalent in spirit; retiring the fallback is future work once
  every project runs prgroom.
- **`auto_merge_eligible`'s Copilot-quiescence gate is degraded today** —
  agents-config-abn9.8.19's seeding gap means it's vacuously satisfied. This
  bead consumes the contract read-only and does not fix that gap.

## Out of scope

- Resurrecting the full quarantined pipeline architecture.
- Multi-PR orchestration / overnight queue overlap (agents-config-ukzs).
- Fixing prgroom's reviewer-state seeding gap (agents-config-abn9.8.19) — this
  bead consumes `auto_merge_eligible` read-only; the seeding fix is tracked
  separately (see Caveat under Clean-review predicate).
