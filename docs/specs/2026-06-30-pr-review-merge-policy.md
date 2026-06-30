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
those beads, for the manual/chat path.) Eligibility itself is computed from
independently-verified facts, not by trusting prgroom's rolled-up boolean
wholesale — see Clean-review predicate.

## Behavior matrix

| `copilot-required` | `human-approvers-required` | Wait? | Merge? |
|---|---|---|---|
| true | 0 | Poll Copilot, fix, resolve | Auto-merge **iff** clean-review predicate holds |
| true | ≥1 | Poll Copilot, fix, resolve | Eligible once approved; agent merges only on an explicit in-session instruction |
| false | 0 | No poll | Auto-merge iff (threads resolved ∧ required CI green) |
| false | ≥1 | No poll | Eligible once approved; agent merges only on an explicit in-session instruction |

### Clean-review predicate (gates auto-merge)

prgroom's `auto_merge_eligible` (`docs/architecture/prgroom/design.md` §4.5:
`phase_is_quiesced` ∧ `last_error_clear` ∧ `no_blocker_items` ∧
`human_review_satisfied`) is **not consumed as a single rolled-up boolean**.
Two of its four components are unsuitable for this policy as-is:

- `phase_is_quiesced` embeds prgroom's own reviewer-quiescence wait, which
  agents-config-abn9.8.19 documents as currently broken (`state.reviewers` is
  never seeded, so the wait is vacuously satisfied). Trusting it would let a
  PR auto-merge with `wait_for_copilot = true` and no completed Copilot
  review — exactly the failure this spec exists to prevent.
- `human_review_satisfied` is binary (one non-bot `APPROVED` review, or a
  `human-approved` label) and has no notion of `required_human_approvers > 1`.
  It cannot represent this resolver's per-bead `n` requirement.

Instead, `merge-guard`'s eligibility check composes the predicate from four
**independently-sourced** atomic facts:

| Atomic check | Source |
|---|---|
| Copilot review complete | **Always** a direct GitHub query (the existing `check-merge-eligibility.sh` Copilot-status check) — never read from prgroom's `phase_is_quiesced`, given the known seeding gap. Required iff `wait_for_copilot`. |
| `N` distinct current non-bot approvers | **Always** a direct query (`gh pr view --json reviews` or equivalent): reduce to one entry per non-bot login using that login's most recent review by submission order, count logins whose latest state is `APPROVED`, compare to `required_human_approvers`. **Not** sourced from prgroom's `human_review.candidates_seen` — that list is documented as one row per `APPROVED` review, not deduped by approver and not latest-state-aware, so a single reviewer re-approving repeatedly (or an approval superseded by a later `CHANGES_REQUESTED`) would overcount. |
| No outstanding blockers | prgroom's `no_blocker_items` when state exists (no item disposition is `ESCALATED`/`FAILED` — unaffected by the reviewer-seeding gap); else a local FIX-class-items-outstanding / threads-resolved check. |
| No terminal lifecycle error | prgroom's `last_error_clear` when state exists; else not applicable (no-op) for the prgroom-less path. |
| Required CI checks green | **Always** a direct check — not part of prgroom's `auto_merge_eligible` contract at all. This is the gate this work **adds** to `check-merge-eligibility.sh`. |

The predicate is the AND of all rows applicable under the resolved policy.
Three of the five checks (Copilot-completion, approver count, CI-green) are
always verified directly and never delegate to prgroom; only the
blocker/terminal-error pair is prgroom-sourced when available. This design
does not depend on agents-config-abn9.8.19 landing — the one known-degraded
prgroom gate (`phase_is_quiesced`) is simply never relied upon.

**Freshness invariant:** Neither `check-merge-eligibility.sh` nor
`poll-copilot-review.sh` tracks head SHA today — this is new surface, not
reused tooling. Two distinct freshness rules apply:

1. **Review identity (Copilot-completion, approver count)**: fetch the PR's
   current `headRefOid`. A Copilot review or human approval counts **only**
   if its `commit_id` equals that head. There is **no timestamp fallback**: a
   review can be *submitted* after a push while still carrying a *stale*
   `commit_id` (it was started against the old diff), so `submitted_at` can
   never distinguish that case from a genuine fresh review. If `commit_id` is
   ever unavailable for a review object, treat it as indeterminate and **fail
   closed** — that review does not count, and auto-merge does not proceed —
   rather than accept it on timestamp alone.
2. **All five atomic checks, recomputed live**: there is no separate
   "compute eligibility now, merge later" phase. `merge-guard` evaluates the
   full predicate (including blocker/thread state and the lifecycle-error
   check, whether sourced from prgroom or the local fallback) **synchronously,
   immediately before** invoking `gh pr merge` — never from an earlier
   cached result. This closes the check-then-merge race for every component,
   not only the two review-identity checks: a new unresolved thread or
   blocking item that appears after an earlier "looks clean" read is caught
   by the live re-evaluation, because there is no earlier read to go stale.
3. **The merge call itself is bound to the checked head**: re-evaluating the
   predicate immediately before merging narrows the race window but does not
   close it — a push can still land between the predicate's `headRefOid`
   read and the `gh pr merge` call. `merge-guard` therefore invokes
   `gh pr merge --match-head-commit <headRefOid>` (the same SHA the predicate
   was just evaluated against); GitHub itself rejects the merge if the head
   changed in that window, and `merge-guard` re-evaluates eligibility from
   scratch on that rejection rather than retrying blindly.

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
  by `merge-guard`'s eligibility check (which sources individual atomic facts
  from `prgroom status --json` when available, never the rolled-up
  `auto_merge_eligible` boolean — see Clean-review predicate); the resolver
  decides *policy*, the eligibility check decides *state*. The merge proceeds
  iff `merge_mode == "auto" AND clean_predicate()`.

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
   `wait_for_copilot == false`, skip the Copilot poll, then branch on
   `merge_mode`:
   - `auto` (no automated reviewer, but policy permits auto-merge) — continue
     directly into `merge-guard`'s eligibility check. Do **not** emit a
     human-handoff status; there is no human to hand off to under this policy.
   - `handoff` — emit a terminal "no automated reviewer configured — PR
     awaiting human review" status and stop. (Reply/resolve still runs if
     human threads already exist.)
2. **`merge-guard`** — call the resolver in its eligibility step. Gate:
   - `merge_mode == "handoff"` → never auto-proceed without an explicit
     in-session human instruction to merge. Reaching `required_human_approvers`
     non-bot approvals (see Clean-review predicate) makes the PR *eligible*
     but is not itself authorization — see Two states, not one.
   - `merge_mode == "auto"` → proceed **iff** the clean-review predicate holds
     (the composed atomic-fact check above — never the rolled-up
     `auto_merge_eligible` boolean).
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
3. **Eligibility-check extension** — `check-merge-eligibility.sh` gains: a
   direct, always-on Copilot-completion check (already present — kept as the
   source of truth, never superseded by prgroom state); a direct,
   always-on distinct-current-approver count against `required_human_approvers`
   (dedup by login, latest review state wins — never prgroom's
   `candidates_seen`, fail closed on unresolvable `commit_id`); the freshness
   invariant binding review identity to `commit_id == headRefOid` (no
   timestamp fallback) and recomputing all five atomic checks live,
   immediately before merge, with no earlier cached result; the merge call
   itself issued as `gh pr merge --match-head-commit <headRefOid>` so GitHub
   rejects a last-instant race rather than merging an unreviewed head; a
   prgroom-aware no-outstanding-blockers / no-terminal-error check (prgroom's
   `no_blocker_items` / `last_error_clear` when present, else the local
   fallback); and the required-CI-green gate (always direct, new).
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
- **Eligibility-check** — test each atomic check independently: Copilot
  status is read directly even when prgroom reports `phase_is_quiesced = true`
  (must not short-circuit on prgroom's value); distinct-current-approver
  counting against `required_human_approvers > 1` — same login approving
  twice counts once, an `APPROVED` review superseded by a later
  `CHANGES_REQUESTED` from the same login does not count, bot logins are
  excluded; blocker/error checks (prgroom-present vs absent); and the
  CI-green gate (green / red / no-CI).
- **Freshness invariant** — a Copilot review or approval with a stale
  `commit_id` must not satisfy its check even when `submitted_at` is after
  the latest push (the pending-review-on-old-diff case); a review with no
  resolvable `commit_id` must fail closed (does not count), never fall back
  to timestamp; a new unresolved thread or blocking item appearing after an
  earlier "clean" read must be caught because eligibility is recomputed live,
  not reused from that earlier read; a push landing between the predicate's
  head read and the merge call must cause `gh pr merge --match-head-commit`
  to reject, triggering a fresh re-evaluation rather than a blind retry.
- **Auto-vs-handoff branch** — `copilot-required = false` with
  `human-approvers-required = 0` must proceed directly to `merge-guard`
  without ever emitting the human-handoff status.
- **Skills** — kept thin enough to verify via the existing skill smoke-test
  suite.

## Risks / notes

- **Highest blast radius is the law amendment.** Wording must make auto-merge
  conditional and non-default; a careless edit reads as "agents merge freely."
- **BLOCKING (escalated from OPEN) — overloaded policy fields enable
  no-review auto-merge by side-effect.** `copilot-required = false` +
  `human-approvers-required = 0` was chosen (brainstorm decision: reuse the
  two existing keys, not add a third) to mean both "skip the unavailable
  reviewer" *and* "merge with no review at all" via the same two settings.
  Two independent adversarial review passes flagged this — the second rating
  it **critical, no-ship** — as conflating two distinct intents: disabling a
  wait vs. affirmatively authorizing a no-review merge. Recommended fix: a
  separate explicit opt-in (e.g. `auto-merge-authorized = true`) so
  `copilot-required = false` means only "do not wait for Copilot," never
  "and also you may merge with zero review." Revisiting the reuse-the-two-keys
  decision is out of this spec's authority to resolve unilaterally — this is
  the one open item requiring an explicit decision before implementation
  begins.
- **agents-config self-auto-merges** under its chosen defaults. Acceptable and
  intended; called out so it is never mistaken for an accident.
- The autonomous-pipeline `review-cycle` / `merge-or-handoff` stages remain
  future work; this spec wires the **live** skills, but the resolver contract
  is shaped so those stages can reuse it unchanged.
- **Never trust `auto_merge_eligible` as a single boolean, and never naively
  count `human_review.candidates_seen`.** Both are documented to embed the
  known-broken Copilot-quiescence wait (`phase_is_quiesced`) and a per-review
  (not per-distinct-approver, not latest-state-aware) record list,
  respectively — see Clean-review predicate. Any future change reusing
  prgroom's review data must re-derive distinct-current-approver state
  itself; it must not sum or trust these fields directly.
- **`auto_merge_eligible`'s Copilot-quiescence component is degraded today**
  (agents-config-abn9.8.19's seeding gap) but this design does not depend on
  it — Copilot-completion is always verified directly. Fixing abn9.8.19 is
  not a prerequisite for this bead.

## Out of scope

- Resurrecting the full quarantined pipeline architecture.
- Multi-PR orchestration / overnight queue overlap (agents-config-ukzs).
- Fixing prgroom's reviewer-state seeding gap (agents-config-abn9.8.19) — not
  a prerequisite here (see Risks); tracked separately.
