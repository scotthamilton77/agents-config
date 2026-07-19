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

**Test content:** each scenario's diff is a trivial, obviously-reversible
edit to a single scratch file,
`docs/architecture/live-codex-verification-scratch.md`, created fresh in
whichever PR needs it and never touching any critical path.

**Blast radius:** agents-config has standing autonomous-merge permission via
merge-guard. Plan A's two PRs are allowed to actually merge — that's the
point, it proves the merge step fires for real. Plan B's PRs are closed
without merging once their scenario's evidence is captured; nothing from
Plan B lands on `main`.

## Plan A — Happy path (2 PRs; both merge for real)

### A1. Clean-first-pass merge
1. Open a PR with a trivial scratch-doc edit.
2. Trigger `@codex review`.
3. Codex leaves a genuine clean pass (reaction or review — whichever it
   actually produces).
4. `poll-copilot-rereview-start.sh` detects the start signal.
5. `poll-copilot-review.sh` detects completion.
6. `check-merge-eligibility.sh` reports eligible, with the correct
   `bot_clean_signal_source`.
7. Autonomous merge fires per standing permission.
8. Confirm: PR merged, branch cleaned up, no stray blockers.

### A2. Realistic re-review arc
1. Open a second PR with a change substantial enough that Codex will
   plausibly flag something real (not fabricated to fail).
2. Codex leaves genuine findings.
3. Confirm `wait-for-pr-comments` classifies/replies/resolves correctly and
   `check-merge-eligibility.sh` blocks on `untriaged_feedback`.
4. Push a fix; ask for `@codex review` again, carrying do-not-relitigate
   context per the request-rereview.sh contract.
5. Codex's fresh round is clean.
6. Confirm the review_summary ratchet clears the stale finding
   (author-scoped to Codex's own identity).
7. Confirm eligible → merges.

## Plan B — Edge cases & failure modes reachable via real behavior (each its own PR; closed without merging once evidenced)

### B1. Human review blocks despite Codex-clean (live author-scoping)
Get a human review (Scott) requesting changes on a PR where Codex
separately leaves a clean reaction. Confirm merge-guard still blocks on the
human's untriaged feedback — proves author-scoping (a bot's clean signal
never clears another identity's findings) isn't just a fixture artifact.

### B2. Trigger-comment exemption
Confirm the `@codex review` ask comment itself is never counted as
blocking feedback under the untriaged_feedback check (Component 2b), on a
live PR.

### B3. Codex-only start handshake
Request re-review from Codex only (no Copilot involved in this round).
Confirm `poll-copilot-rereview-start.sh`'s eyes-reaction path is what
unblocks Phase 6 — this is the exact live scenario the #317→#337 defect
broke (a Codex-only ask previously left Phase 6's start gate silently
unfired).

## Execution mechanics

- Every scenario runs through the real skills (`wait-for-pr-comments`,
  `merge-guard`) exactly as they'd fire in normal use. No manual eligibility
  overrides, no shortcuts.
- Evidence captured per scenario: the actual `gh api` responses observed
  (reactions/review/check-runs JSON), each poll helper's JSON output,
  `check-merge-eligibility.sh`'s verdict JSON, and the final merge/close
  outcome.
- Plan B PRs end in an explicit close (not merge) once evidence is
  captured.
- Wall-clock: real Codex rounds take real minutes. This runs in-session
  using the existing poll cadence (zero-token background waits via the
  shipped poll helpers), not scripted mocking.

## Reporting

One report at the end covering all five scenarios: expected vs. observed,
pass/fail per scenario, and the raw evidence artifacts referenced above.
Not a bare "it worked" — each scenario's claim must be traceable to a
specific captured artifact (a verdict JSON, a poll output, a merge/close
event).

## Continuations

- none for this spec's own scenarios — A1–A2/B1–B3 are executed directly
  from the resulting implementation plan, not tracked as separate follow-on
  work items.
- **abn9.44.3** (already filed, P1, open, anchored under abn9.44): fix
  `check-merge-eligibility.sh`'s CI-required-checks source to also read
  GitHub Ruleset `required_status_checks` rules via
  `rules/branches/{base}`, not just the legacy classic-protection endpoint.
  Discovered during this spec's own investigation of live CI-blocking
  testability; tracked and fixed on its own cycle, not part of this plan.
