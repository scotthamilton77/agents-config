# Live Codex-Awareness Verification (merge-guard + wait-for-pr-comments)

## Why this exists

wgclw.29 (and its children .1/.2) proved the codex-awareness fixes shipped in
PRs #332–#339 hold under fixture-driven unit tests: a fake `gh` binary fed
static JSON, no network call ever left the box. Those tests are legitimate —
each was verified to fail against the pre-fix script and pass against
shipped HEAD — but they only prove the decision logic is correct *given a
GitHub API response shaped like the ones observed during the original
incidents*. They say nothing about whether the real GitHub API still shapes
its JSON that way, or whether a live Codex reviewer's actual reaction/event
timing still matches those assumptions.

This spec covers the live counterpart: driving the real pipeline (a real PR
on agents-config, a real `@codex review`, real GitHub state) through
`wait-for-pr-comments`'s poll helpers and `merge-guard`'s eligibility check,
end to end, with no mocking anywhere in the path.

## Scope

**In scope:** the full pipeline — PR created → real Codex review → poll
helpers detect start/completion → `check-merge-eligibility.sh` evaluates →
merge (or a deliberate, evidenced block). Runs against **agents-config
itself**, since that's where Codex and the merge-guard/wait-for-pr-comments
skills are already live-configured.

**Out of scope:** fixture-only edge cases that cannot be induced by real bot
or GitHub behavior — malformed timestamps, GitHub endpoint failures, a
synthetic untrusted "evil-bot" identity, exact same-second timing races,
empty-allowlist configuration. Those remain the unit suite's job
(`check-merge-eligibility_test.sh`, `poll-copilot-rereview-start_test.sh`,
`poll-copilot-review_test.sh`, `request-rereview_test.sh`) and are not
re-verified here.

Also out of scope: CI red→green blocking. agents-config enforces required
checks via a GitHub Ruleset (not classic branch protection), and
`check-merge-eligibility.sh` currently sources its required-checks set only
from the legacy classic-protection endpoint — confirmed live to 404 on this
repo, which the script's own fallback reads as "no CI requirement," making
`ci_state` unconditionally `"none"` here regardless of the real ruleset's
required `"ci"` check. This is a real correctness bug, unrelated to
codex-awareness, filed separately as **abn9.44.3** (P1) and fixed on its own
cycle. Testing CI-blocking live is meaningless until that ships.

Also out of scope, for the same reason: **A2's do-not-relitigate context**
(`--disposition-table-file`/`--since-sha` on `request-rereview.sh`). The
resulting multi-line ask-comment body is not recognized by
`check-merge-eligibility.sh`'s trigger-comment exemption (exact-match on the
bare string `"@codex review"`), so using it would trip the
`untriaged_feedback` blocker on the re-review ask itself — a real bug, filed
separately as **abn9.44.4** (P1). A2's re-review ask below uses the bare
`@codex review` comment, not the disposition-table form, to stay clear of
this known-broken path.

**Test content:** each scenario's diff is a trivial, obviously-reversible
edit to its own scratch file under `docs/architecture/` (one file per
scenario — see naming in each scenario below — never a shared path, to avoid
merge conflicts and stale-branch collisions across concurrently-open PRs).
A1/A2's edits may include a deliberately minor rough edge (an ambiguous
sentence, a small factual inconsistency) chosen to plausibly draw a genuine
Codex comment — still trivial and reversible as *content*, just not
frictionless as *prose*.

**Blast radius controls:**
- agents-config has standing autonomous-merge permission via merge-guard.
  Plan A's two PRs are allowed to actually merge — that's the point, it
  proves the merge step fires for real.
- **Plan B PRs never run the merge-guard merge action.** For every Plan B
  scenario, only `check-merge-eligibility.sh` is invoked directly to capture
  its verdict JSON; `merge-guard`'s merge/authorization step is never
  invoked, even if the verdict comes back eligible. This is a hard rule, not
  a judgment call made per scenario — Plan B scenarios are specifically
  designed to reach ELIGIBLE under this repo's rule-based/bot-quiescence
  policy, and running the real merge action on them would defeat "nothing
  from Plan B lands on `main`."
- Every Plan B PR is opened **as a draft**. This repo's ruleset reviews
  drafts too (`copilot_code_review.review_draft_pull_requests: true`), so
  Codex still reviews them, but GitHub's merge API refuses to merge a draft
  outright — a second, independent backstop against C-1-class mistakes if
  the hard rule above is ever violated by accident.
- "Runs through the real skills exactly as they'd fire normally" (below)
  means no eligibility-fact overrides and no fixture injection — it does
  **not** mean "let the merge action fire on every scenario." The merge
  action is exclusively an A1/A2 behavior.

## Plan A — Happy path (2 PRs; both merge for real)

### A1. Clean-first-pass merge
Scratch file: `docs/architecture/live-codex-verification-scratch-a1.md`.

1. Open a PR with the trivial scratch-doc edit.
2. Trigger `@codex review` (bare comment).
3. Record which artifact Codex actually produces — a review object, a `+1`
   reaction, or a clean-pass marker comment. These have different
   eligibility consequences (`bot_clean_review_at_head` is set by the
   review or reaction path only; a marker-comment-only response does
   **not** set it). If Codex responds with a marker comment only, that's a
   real, reportable finding, not a silent pass or a silent stall — note it
   and treat A1 as inconclusive until a review/reaction artifact is
   observed on a subsequent trigger.
4. If a reaction is involved, track its lifecycle: an `eyes` reaction must
   be *absent* at evaluation time for `reaction_clean` to be true (an
   `eyes` reaction lingering alongside a `+1` fails the fact). Capture
   both the in-flight and post-clean reaction state as evidence.
5. `poll-copilot-rereview-start.sh` detects the start signal (`--bot-reviewers`
   must include `chatgpt-codex-connector[bot]`).
6. `poll-copilot-review.sh` detects completion.
7. `check-merge-eligibility.sh` reports eligible, with the correct
   `bot_clean_signal_source` matching the artifact recorded in step 3.
8. Autonomous merge fires per standing permission.
9. Confirm: PR merged, branch cleaned up, no stray blockers, `ci` ruleset
   check green (this is GitHub's own gate — merge-guard's own `ci_state`
   fact is inert here per abn9.44.3, so it isn't what's being proven).

### A2. Realistic re-review arc
Scratch file: `docs/architecture/live-codex-verification-scratch-a2.md`.
Split into two falsifiable parts so the ratchet claim (A2b) can't be
accidentally satisfied by ordinary triage (see below).

**Contingency:** if round 1 comes back clean instead of with findings,
A2 is inconclusive, not passed — push a second, more clearly flawed edit
and retry once before reporting a genuine "Codex would not flag this"
result.

**A2a — genuine findings, normal triage (independent of the ratchet):**
1. Open the PR with the deliberately-imperfect scratch-doc edit.
2. Trigger `@codex review` (bare comment).
3. Codex leaves a genuine `review_summary` with findings.
4. Confirm `check-merge-eligibility.sh` blocks with `untriaged_feedback`
   naming that specific `review_id`.
5. Run `wait-for-pr-comments`'s normal classify/reply/resolve flow and give
   the finding a terminal disposition (FIX or SKIP). Confirm the blocker
   clears via the ordinary terminal-disposition path (`$done_review`),
   **not** the ratchet — this is the control case proving normal triage
   still works, and it must NOT be mistaken for ratchet evidence.

**A2b — the ratchet itself (deterministic, decoupled from A2a's triage):**
Re-run from a fresh PR/finding (do not reuse a A2a item that already
received a terminal disposition — that would exercise `$done_review`, not
the ratchet):
1. Get a genuine `review_summary` with findings (same mechanism as A2a
   step 3), but do **not** run the normal triage/reply flow on it — leave
   it un-triaged and stale on purpose.
2. Push a fix commit; ask for `@codex review` again (bare comment, per the
   do-not-relitigate exclusion above).
3. Codex's fresh round at the new head is clean (reaction or review).
4. Confirm the blocker clears via the **ratchet** specifically: assert the
   stale `review_summary`'s `review_id` is **absent** from `$done_review`
   (no terminal disposition was ever recorded) while `check-merge-eligibility.sh`
   still reports eligible, because the reaction's/review's `created_at`
   postdates the stale summary's `submitted_at`. This is the assertion
   that actually falsifies a ratchet regression — "eligible → merges"
   alone does not.
5. Confirm eligible → merges.

## Plan B — Edge cases & failure modes reachable via real behavior (each its own draft PR; eligibility-checked only, never merge-guard-merged, then closed)

### B1. Human review blocks despite Codex-clean (live author-scoping)
Scratch file: `docs/architecture/live-codex-verification-scratch-b1.md`.

Get a human review (Scott) that leaves a **COMMENTED** review with a
findings body (not "Request changes" — that trips the separate, unrelated
`requested_changes_active` blocker and would muddy which mechanism is
actually holding the block) on a PR where Codex separately leaves a clean
reaction. Confirm `check-merge-eligibility.sh`'s `untriaged_feedback` list
still names Scott's `review_id` specifically, while `reaction_clean=true`
— proving author-scoping (a bot's clean signal never clears another
identity's findings) isn't just a fixture artifact.

### B2. Trigger-comment exemption
Scratch file: `docs/architecture/live-codex-verification-scratch-b2.md`.

Confirm the bare `@codex review` ask comment itself is never counted as
blocking feedback under the untriaged_feedback check (Component 2b), on a
live PR. (This scenario intentionally does not use the disposition-table
form — see abn9.44.4.)

### B3. Codex-only start handshake
Scratch file: `docs/architecture/live-codex-verification-scratch-b3.md`.

Request re-review with `--bot-reviewers` set to a **Codex-only** allowlist
(no Copilot identity in the list — this specifically forces
`HAS_COPILOT_CAPABLE_BOT=false`). Confirm `poll-copilot-rereview-start.sh`'s
eyes-reaction path (`signal == "eyes_reaction"`) is what unblocks Phase 6 —
this is the exact live scenario the #317→#337 defect broke (a Codex-only
ask previously left Phase 6's start gate silently unfired).

## Execution mechanics

- Every scenario runs through the real skills (`wait-for-pr-comments`,
  `merge-guard`'s eligibility check) exactly as they'd fire in normal use —
  no manual eligibility-fact overrides, no fixture injection. This does
  **not** extend to the merge action itself for Plan B (see Blast radius
  controls above).
- Load-bearing flags are pinned per scenario, not left implicit:
  `--bot-reviewers` must include `chatgpt-codex-connector[bot]` for every
  scenario except B3, which uses a Codex-only allowlist deliberately.
- Evidence captured per scenario: the actual `gh api` responses observed
  (reactions/review/check-runs JSON), each poll helper's JSON output,
  `check-merge-eligibility.sh`'s verdict JSON (with the specific fields the
  scenario's pass criterion names — not just "it looked fine"), and the
  final merge/close outcome.
- Plan B PRs are opened as drafts, eligibility-checked directly (never
  merge-guard-merged), and end in an explicit close once evidence is
  captured.
- Wall-clock: real Codex rounds take real minutes. This runs in-session
  using the existing poll cadence (zero-token background waits via the
  shipped poll helpers), not scripted mocking.

## Cleanup

- The scratch files that land on `main` via A1/A2 are removed by a small
  follow-up housekeeping commit once both Plan A PRs have merged — they
  have no reason to persist in the repo's real history.
- Every Plan B branch is deleted after its PR is closed.
- Any real human review left on a Plan B PR (B1) is dismissed/resolved
  before that PR is closed, so no stale `CHANGES_REQUESTED` or unresolved
  thread lingers against a closed PR.

## Reporting

One report at the end covering A1, A2a, A2b, B1, B2, B3: expected vs.
observed, pass/fail per scenario, and the raw evidence artifacts referenced
above. Not a bare "it worked" — each scenario's claim must be traceable to
a specific captured artifact (a verdict JSON field, a poll output, a
merge/close event), and A2b's claim specifically must cite the
`$done_review` absence + timestamp ordering, not just the final eligible
verdict.

## Continuations

- none for this spec's own scenarios — A1/A2a/A2b/B1–B3 are executed
  directly from the resulting implementation plan, not tracked as separate
  follow-on work items.
- **abn9.44.3** (already filed, P1, open, anchored under abn9.44): fix
  `check-merge-eligibility.sh`'s CI-required-checks source to also read
  GitHub Ruleset `required_status_checks` rules via
  `rules/branches/{base}`, not just the legacy classic-protection endpoint.
  Discovered during this spec's own investigation of live CI-blocking
  testability; tracked and fixed on its own cycle, not part of this plan.
- **abn9.44.4** (already filed, P1, open, anchored under abn9.44): broaden
  `is_trigger_comment` to recognize a disposition-table-rendered re-ask
  body, not just the bare string, so the do-not-relitigate feature doesn't
  block its own PR's merge. Discovered while designing A2; tracked and
  fixed on its own cycle, not part of this plan.
