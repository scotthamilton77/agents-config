# PR Review / Merge Policy — two orthogonal axes

- **Date**: 2026-06-30
- **Bead**: agents-config-wgclw.14 (M0)
- **Status**: draft
- **Related**: agents-config-7bk.12 (brainstorm-time review knobs authoring),
  agents-config-abn9.8.19 (prgroom reviewer seeding), agents-config-ukzs
  (overlap external waits), agents-config-7bk.17 (key-naming alignment)

## Problem

The delivery flow treats "wait for PR review feedback" as an unconditional
step and "merge" as always human-performed. Neither is configurable per
project. On a repo with no automated reviewer the agent polls for feedback
that never arrives; on a repo where a clean automated review is sufficient to
ship, a human is forced into the loop for no judgment reason.

A configuration surface exists but is **orphaned**: `project-config.toml`
declares `[review-requirements]` (`copilot-required`,
`human-approvers-required`), citing `bead-pipeline-architecture.md §5.1` — a
doc quarantined to `archive/docs/specs/`. No source reads these keys
(`grep -rl project-config.toml src/` = 0 hits). The keys are also
**overloaded**: `human-approvers-required` encoded both *how much review* and
(via a `== 0` special case) *whether the agent may merge* — conflating two
unrelated concerns.

## Core model: two orthogonal axes

The fix is to separate the two concerns the old keys conflated. A PR's fate is
governed by two independent axes:

- **Axis 1 — Review expectation**: what reviews do we expect, and how long do
  we wait for them? This, and only this, drives the poll / comment-resolution
  cycle.
- **Axis 2 — Merge authorization**: once a PR is *eligible*, who is allowed to
  press merge?

Between them sits one derived concept:

- **Eligibility** — is the PR in a state where merging is safe? Computed one
  way, from Axis 1's expectations plus CI / thread / freshness facts (see
  Eligibility predicate). Eligibility is **not** authorization.

**A merge happens iff the PR is `eligible` AND the action is `authorized`.**
Axis 1 and the eligibility predicate decide the former; Axis 2 decides the
latter. Keeping them separate is what removes the overloading. This invariant
is absolute for every automatic and instructed path. The **only** exception is
an explicit, separately-named human **force-merge** override (see merge-guard
wiring) — a deliberate, logged action that bypasses the eligibility gate; it is
never the default behavior of any Axis-2 value.

## Axis 1 — Review expectation

Drives polling. The cycle is ON **iff** `bot-review-expected` **or**
`human-approvers-required > 0`. If nothing is expected, there is no polling.

| Setting | Meaning |
|---|---|
| `bot-review-expected` (bool) | Expect a bot reviewer. Poll until the bot quiesces (reviewed, then inactive for the timeout). |
| `bot-reviewers` (list) | The **trusted** bot identities whose review satisfies the bot-review fact — matched by **exact** login / app identity, not substring. Defaults to Copilot's identity. A review from a bot not on this list does not count. This is the trust boundary for `bot-quiescence` autonomous merge; a substring match (as the current script does with `test("copilot"; "i")`) is insufficient. |
| `bot-inactivity-timeout` | Bot silence that counts as "bot is done" (reuses prgroom's review-finish-timeout concept). |
| `human-approvers-required` (int) | How many human approvals to wait for. |
| `human-review-timeout` | How long to wait for slow humans before giving up. Empty = wait indefinitely (interactive); autonomous runs park the molecule rather than block (see agents-config-ukzs). |

A timeout means "stop waiting," not "treat the review as satisfied." A bot
that never reviewed, or humans who never approved, do **not** become
satisfied by their timeout elapsing — the wait simply ends and the PR is
handed off / parked. Absence never authorizes a merge.

## Axis 2 — Merge authorization

Once eligible, who may merge?

| Value | Meaning |
|---|---|
| `never` | The agent never merges — not even on an in-session instruction. A human merges in the GitHub UI (max control / audit-trail repos). |
| `explicit` *(default)* | The agent merges only on an explicit in-session human instruction ("merge it" / "ship it"). This is today's global merge-authorization law, unchanged. |
| `rule-based` | The agent merges autonomously when the selected **merge-rule** holds. Requires a `merge-rule` value. |

### Merge-rule vocabulary (used only when `merge-authorization = rule-based`)

Every rule applies **on top of** the eligibility predicate (CI green, threads
resolved, fresh head — see below). The rule names *what additionally
authorizes the autonomous merge*:

| Rule | Authorizes merge when… |
|---|---|
| `bot-quiescence` | An expected bot **actually reviewed** and quiesced clean. A bot that merely timed out without reviewing does **not** satisfy this — the "real review" floor is structural to the rule, not a separate toggle. |
| `human-approvals` | `human-approvers-required` distinct current non-bot approvals are present (see Eligibility predicate for the counting rules). |
| `agent-ruling` | An independent, cross-model agent evaluates the diff and renders a merge go/no-go verdict. **Design-reserved; implementation deferred** to a follow-up bead (the judge harness reuses the RALF / codex-review machinery). |

`merge-rule` takes a single value for now. It is shaped as a scalar the config
parser treats as one selection, so a future rule engine (boolean combinations
/ expressions — TBD) can extend the field without a breaking rename.

### AI reviewer vs. AI merge-judge — do not conflate

Two distinct roles an AI can play, deliberately on different axes:

- **AI reviewer** — a bot that leaves *comments to address*. This is an Axis-1
  reviewer; `bot-review-expected` already generalizes beyond Copilot to any
  bot review (including a codex/RALF review bot).
- **AI merge-judge** — `agent-ruling`, an agent that renders a *merge
  verdict*. This is an Axis-2 authorization source, invoked at the merge gate.

Same technology family, different jobs. The cross-model principle (the judge
should not be the same model that wrote the code) lives with `agent-ruling`.

### Safety property: no zero-review auto-merge is possible

The original design's critical flaw — a repo auto-merging with no review at all
— is now **structurally impossible**, not merely discouraged. Autonomous merge
requires `merge-authorization = rule-based` *and* a `merge-rule`, and every
implemented rule requires a *real* review to have occurred. The resolver's
validation enforces this so a rule cannot be vacuously satisfied:
`human-approvals` is rejected unless `human_approvers_required >= 1`
(a zero-approval rule would be trivially true); `bot-quiescence` is rejected
unless a trusted `bot-reviewers` identity is configured and
`bot-review-expected` is true, and it counts only an *actual* clean review from
that identity (a no-show/timeout never satisfies it). A repo that expects no
reviewers therefore has **no satisfiable rule** and cannot auto-merge — it
falls through to handoff. No rule authorizes on nothing. (`agent-ruling`, when
built, is itself a real review.) The zero-review merge path is closed by
construction.

### Worked examples

| Repo intent | Axis 1 | Axis 2 |
|---|---|---|
| **agents-config** (auto-merge on clean Copilot) | `bot-review-expected=true`, `humans=0` | `rule-based` / `bot-quiescence` |
| **Human-gated** (no bot, one human approves, human ships) | `bot-review-expected=false`, `humans=1` | `explicit` |
| **Autonomous on human sign-off** (1 human approves → agent merges) | `bot-review-expected=false`, `humans=1` | `rule-based` / `human-approvals` |
| **Compliance / audit** (agent must never touch merge) | any | `never` |
| **Today's default** (poll Copilot, human ships on instruction) | defaults | `explicit` (default) |

## Eligibility predicate

Eligibility is the AND of the applicable atomic facts below, each
**independently sourced**. prgroom's rolled-up `auto_merge_eligible` boolean
(`docs/architecture/prgroom/design.md` §4.5) is **never** consumed wholesale —
two of its four components are unsuitable (`phase_is_quiesced` embeds the
reviewer-quiescence wait that agents-config-abn9.8.19 documents as unseeded /
vacuously true; `human_review_satisfied` is binary with no notion of `N > 1`).

| Atomic fact | Source |
|---|---|
| Expected bot reviewed & clean | **Always** a direct GitHub query (the existing `check-merge-eligibility.sh` Copilot-status check) — never prgroom's `phase_is_quiesced`. Applies iff `bot-review-expected`. |
| `N` distinct current non-bot approvers | **Always** a direct query (`gh pr view --json reviews`): reduce to one entry per non-bot login (latest review by submission order wins), count logins whose latest state is `APPROVED`, compare to `human-approvers-required`. Never prgroom's `human_review.candidates_seen` (one row per review, not deduped, not latest-state-aware → overcounts). |
| No unresolved review threads | **Always** a live GitHub query at merge time. prgroom state is **never** a substitute — a thread opened after prgroom last quiesced would be absent from state yet unresolved on GitHub. Zero unresolved threads required. |
| No internal blocker items | prgroom's `no_blocker_items` when prgroom state exists (no disposition `ESCALATED`/`FAILED`) — an **additional** internal-blocker source layered on top of the live thread check, never a replacement for it. n/a without prgroom. |
| No terminal lifecycle error | prgroom's `last_error_clear` when prgroom state exists; else n/a. |
| Required CI checks green | **Always** a direct check — not part of prgroom's contract. New gate added to `check-merge-eligibility.sh`. |

Four of the six (bot-review, approver count, unresolved threads, CI) are
always verified directly and never delegate to prgroom, so the design does not
depend on agents-config-abn9.8.19 landing.

### Freshness invariant

Neither `check-merge-eligibility.sh` nor `poll-copilot-review.sh` tracks head
SHA today — this is new surface.

1. **Review identity** (bot-review, approver count): fetch the PR's current
   `headRefOid`. A bot review or human approval counts **only** if its
   `commit_id` equals that head. There is **no timestamp fallback** — a review
   pending on an old diff can be *submitted* after a push while carrying a
   *stale* `commit_id`, so `submitted_at` cannot distinguish it. If a review's
   `commit_id` is unavailable, **fail closed** (it does not count).
2. **Recompute live**: `merge-guard` evaluates the full predicate
   synchronously immediately before merging — never from a cached earlier
   read — so new unresolved threads / blockers that appear after an earlier
   "looks clean" read are caught.
3. **Bind the merge to the checked head**: the merge is issued as
   `gh pr merge --match-head-commit <headRefOid>` (the SHA the predicate was
   evaluated against). GitHub rejects the merge if the head changed in the
   final window; `merge-guard` re-evaluates from scratch on rejection rather
   than retrying blind.

## Architecture

### A tested policy-resolver helper (not inline-per-skill)

Per the repo's "code over prose / Python over Bash for testable logic"
principle, resolution lives in one code unit the consuming skills call.

```
resolve_policy(
    project_config: ProjectReviewMergeConfig,   # parsed [review-expectations] + [merge-policy]
    bead_labels: list[str],                      # per-bead overrides
) -> ReviewMergePolicy

ReviewMergePolicy = {
    # Axis 1
    bot_review_expected: bool,
    bot_reviewers: list[str],          # trusted bot identities (exact match)
    bot_inactivity_timeout: Duration,
    human_approvers_required: int,
    human_review_timeout: Duration | None,
    # Axis 2
    merge_authorization: "never" | "explicit" | "rule-based",
    merge_rule: "bot-quiescence" | "human-approvals" | "agent-ruling" | None,  # required iff rule-based
}
```

- Outside-world inputs (config, labels) are arguments — no module globals.
- Output is a typed value, not an untyped dict, at the boundary.
- Invalid combinations fail loud (resolver error, never a silent fallback to
  merging or to a different rule):
  - `rule-based` without a `merge-rule`, or `merge-rule` set while not
    `rule-based`.
  - `merge-rule = human-approvals` with `human_approvers_required < 1` — a
    zero-approval rule is vacuously true and would authorize an unreviewed
    merge. The rule requires at least one required approver.
  - `merge-rule = bot-quiescence` with no trusted bot in `bot-reviewers` (no
    identity could satisfy the rule) or with `bot-review-expected = false`.
  - `agent-ruling` selected before its implementation lands → explicit "not
    yet implemented" error.

### Resolution precedence

`per-bead label` > project config > built-in default.

Per-bead override labels (consumed here; *authored* at brainstorm time by
agents-config-7bk.12 — add a dependency edge):

- `review-exit-copilot-only` → `bot_review_expected = true` **regardless** of
  project config (its purpose is to wait for the bot; it must not degrade to
  no-review), and `human_approvers_required = 0`.
- `review-exit-human-approvers-<n>` → `human_approvers_required = n`.
  Mutually exclusive with `review-exit-copilot-only`; both present → resolver
  error.

Built-in defaults (section/key absent):

- `bot-review-expected = true` (most repos run Copilot; a repo without it
  times out via `bot-inactivity-timeout` and proceeds, or sets this false).
- `human-approvers-required = 0`.
- `merge-authorization = "explicit"` — the safe, backward-compatible default:
  identical to today's "merge only on explicit instruction" law.

### Live consumer wiring

1. **`wait-for-pr-comments`** — call the resolver at entry; run the
   poll/resolve cycle per Axis 1. If nothing is expected, skip polling. On
   timeout, emit a terminal "awaiting human review" / "parked" status; do not
   block. Never emit a human-handoff status when nothing human is expected and
   `merge-authorization` permits proceeding.
2. **`merge-guard`** — the enforcement point. Compute the eligibility
   predicate (above), then apply Axis 2:
   - `never` → never merge; hand off. An in-session "merge it" is refused with
     an explanation (this repo's policy is human-manual merge).
   - `explicit` → merge iff eligible **and** the human gave an in-session
     instruction. **Fail-closed on ineligibility**: an ineligible PR is not
     merged even when instructed — merge-guard reports why it is ineligible and
     stops.
   - `rule-based` → merge iff eligible **and** the selected `merge-rule` holds.
   - **Force-merge (the one eligibility-bypass path)** → a distinct, explicitly
     named human override ("force merge"), valid only in `explicit` mode, only
     on a fresh in-session human instruction that names the ineligibility being
     overridden. It is logged and never available to `never`, to `rule-based`,
     or to any autonomous path. (This replaces today's merge-guard behavior
     where any ineligible PR could be force-merged as an undifferentiated
     "proceed anyway.")
   - All merges issued with `--match-head-commit`.
3. **`finishing-a-development-branch`** — unchanged for PR creation; hands off
   to `merge-guard` for the gated merge decision.

### The merge-authorization law

The standing global rule ("merge requires explicit human authorization")
becomes the `explicit` value of Axis 2 — preserved verbatim as the default.
The law is amended to name the two opt-outs:

> The agent's merge authority for a repository is set by its merge-authorization
> policy: `never` (the agent never merges), `explicit` (default — the agent
> merges only on an explicit in-session human instruction), or `rule-based`
> (the agent merges autonomously only when the configured merge-rule and the
> eligibility predicate both hold). Absent configuration, `explicit` applies,
> and the existing explicit-authorization requirement stands unchanged.

Applied to the merge-authorization content in the delivery and completion-gate
rules and the `<constraints>` block, by concept (installed assets are
flattened at install time — no file-path citations in the amended text).

## Deliverables

1. **HLD** — `docs/architecture/review-merge-policy/` (`index.md` + the
   two-axis model, eligibility predicate, resolver contract, the merge-rule
   vocabulary incl. the reserved `agent-ruling` slot). Evergreen. Replaces the
   stale `§5.1` toml reference.
2. **Policy-resolver helper** — code + unit tests (the typed resolver).
3. **Eligibility-check extension** — `check-merge-eligibility.sh` gains: the
   always-direct bot-review check matched against the trusted `bot-reviewers`
   allowlist by **exact** identity (replacing the current
   `test("copilot"; "i")` substring filter); the distinct-current-approver
   check (fail closed on unresolvable `commit_id`); an always-live
   unresolved-review-threads check (never delegated to prgroom state); the
   freshness invariant + `--match-head-commit` merge binding; prgroom-sourced
   internal blocker/error checks when available; and the required-CI-green gate.
4. **Live wiring** — `wait-for-pr-comments`, `merge-guard`,
   `finishing-a-development-branch`.
5. **Per-bead label parsing** — `review-exit-copilot-only`,
   `review-exit-human-approvers-<n>` (dependency edge to agents-config-7bk.12).
6. **Law amendment** — the merge-authorization axis (above).
7. **toml restructure** — replace `[review-requirements]` with
   `[review-expectations]` (Axis 1) and `[merge-policy]` (Axis 2); fix the
   stale `§5.1` reference (point at the new HLD). agents-config's own settings,
   expressed cleanly with no overloading:
   `bot-review-expected = true`, `bot-reviewers = ["Copilot"]` (matched to
   Copilot's exact reviewer app identity — the implementation resolves the
   precise `login`), `human-approvers-required = 0`,
   `merge-authorization = "rule-based"`, `merge-rule = "bot-quiescence"` (this
   repo auto-merges on a clean Copilot review — a deliberate, named choice).

## Testing

- **Resolver** — the two-axis space, precedence (label > config > default),
  invalid combinations (rule-based w/o rule; rule set while not rule-based;
  both override labels; `agent-ruling` → not-implemented error;
  `human-approvals` with required approvers omitted / 0 / negative → error;
  `bot-quiescence` with empty `bot-reviewers` or `bot-review-expected=false`
  → error).
- **Eligible-vs-authorized** — a PR eligible under `explicit` with no in-session
  instruction must not merge; an *ineligible* PR under `explicit` must not merge
  even when instructed (fail-closed), and must merge only via the distinct
  named force-merge override; a PR under `never` must not merge even when
  instructed (force-merge unavailable).
- **Eligibility atoms** — bot-review read directly even when prgroom reports
  `phase_is_quiesced = true`, and only a trusted `bot-reviewers` identity
  counts (exact match, not substring; an untrusted bot's review is ignored);
  distinct-current-approver counting for `N > 1` (same login twice = one;
  `APPROVED` superseded by later `CHANGES_REQUESTED` = zero; bots excluded);
  unresolved review threads read live even when prgroom `no_blocker_items` is
  clean (a post-quiescence thread must block); internal blocker/error checks
  prgroom-present vs absent; CI-green (green / red / no-CI).
- **Freshness** — stale `commit_id` never satisfies even with a later
  `submitted_at`; missing `commit_id` fails closed; a push between predicate
  and merge triggers `--match-head-commit` rejection → fresh re-evaluation.
- **Axis-1 timeouts** — bot no-show timeout ends the wait without satisfying
  the bot-review fact; human timeout parks/hands off without merging.
- **Skills** — verified via the existing skill smoke-test suite.

## Risks / notes

- **The law amendment is the highest-blast-radius change.** `explicit` must
  remain the default so no repo silently gains merge autonomy; the wording
  must make `rule-based` a deliberate opt-in.
- **agents-config self-auto-merges** under its chosen settings
  (`rule-based` / `bot-quiescence`). Deliberate and named — not an accident of
  zeroed review knobs.
- **`agent-ruling` is design-reserved, not implemented.** The resolver must
  error explicitly if it is selected before the follow-up bead lands — never
  silently degrade to a different rule or to merging unreviewed.
- **`merge-rule` is scalar-now, engine-later.** Keep the field shaped so a
  future rule engine (boolean combinations / expressions — TBD) can extend it
  without a breaking rename.
- **Never trust prgroom's `auto_merge_eligible` boolean or naively count
  `human_review.candidates_seen`** — see Eligibility predicate. Any future
  reuse of prgroom review data must re-derive distinct-current-approver state.

## Out of scope

- `agent-ruling` implementation (design-reserved here; follow-up bead).
- A merge-rule engine / boolean rule combinations (future; field shaped for it).
- Resurrecting the full quarantined pipeline architecture.
- Multi-PR / overnight queue overlap (agents-config-ukzs).
- Fixing prgroom's reviewer-seeding gap (agents-config-abn9.8.19) — not a
  prerequisite; the bot-review fact is verified directly regardless.
