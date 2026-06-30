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

## Behavior matrix

| `copilot-required` | `human-approvers-required` | Wait? | Merge? |
|---|---|---|---|
| true | 0 | Poll Copilot, fix, resolve | Auto-merge **iff** clean-review predicate holds |
| true | ≥1 | Poll Copilot, fix, resolve | Handoff: merge only on explicit human instruction **or** a human PR approval |
| false | 0 | No poll | Auto-merge iff (threads resolved ∧ required CI green) |
| false | ≥1 | No poll | Handoff to human |

### Clean-review predicate (gates auto-merge)

Auto-merge is permitted only when **all** hold:

1. Copilot review complete — if `copilot-required`
2. All review threads resolved
3. No FIX-class items outstanding
4. Required CI checks green

This is the archived `quiesced` terminal state. `merge-guard`'s existing
`check-merge-eligibility.sh` already verifies (1)–(3) (pending reviewers,
Copilot status, comment triage); this work **adds the required-CI-green gate**
(4) to that check.

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
  by `merge-guard`'s eligibility check; the resolver decides *policy*, the
  eligibility check decides *state*. The merge proceeds iff
  `merge_mode == "auto" AND clean_predicate()`.

### Resolution precedence

`per-bead label` > `project-config.toml [review-requirements]` > built-in default.

- `review-exit-copilot-only` → forces `wait_for_copilot` per copilot config but
  sets `required_human_approvers = 0` (Copilot-only exit).
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
   - `merge_mode == "handoff"` → never auto-proceed; require explicit human
     instruction or a recorded human PR approval (existing law path).
   - `merge_mode == "auto"` → proceed **iff** the clean-review predicate holds
     (extended `check-merge-eligibility.sh`, now incl. required-CI-green).
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
3. **Eligibility-check extension** — add required-CI-green to
   `merge-guard/check-merge-eligibility.sh`.
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
- **Eligibility-check** — test the added CI-green gate (green / red / no-CI).
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

## Out of scope

- Resurrecting the full quarantined pipeline architecture.
- Multi-PR orchestration / overnight queue overlap (agents-config-ukzs).
- prgroom reviewer-state seeding (agents-config-abn9.8.19) — complementary but
  separate.
