# prgroom Reviewer Registry Seeding — Design

**Date:** 2026-07-19
**Status:** Approved (design)
**Beads:** agents-config-abn9.8.51 (state.reviewers is never populated — reviewer machinery is inert; P1 bug).
**Related:** agents-config-abn9.8.52 (Codex bot support) is blocked on this bead — a per-bot re-review/clean-pass mechanism has nothing to key off while the registry stays empty.

## 1. Problem

`bootstrap_state()` (`prsession/state.py:381-396`) always initializes `reviewers={}`, and
grepping the shipped package for `ReviewerState(` outside tests returns nothing — no
production code path ever constructs one. Three consumers already iterate
`state.reviewers.values()` correctly and are silently inert as a result:

- `rereview_pr` (`lifecycle/rereview.py:60`) — the remove/re-add dance has no required
  reviewer to re-request.
- `_g_reviewers` (`lifecycle/quiescence.py:55-56`) — `all(...)` over an empty dict is
  vacuously `True`, so the reviewer gate never actually blocks quiescence; it just never
  had anything to check.
- `_observe_engagement` / `evaluate_reviewer_timeouts` (`lifecycle/poll.py:317-382`,
  `lifecycle/quiescence.py:106-136`) — same vacuous-no-op shape.

The schema and every consumer are correct; only the seed is missing.

## 2. Decision

Two coordinated changes, both driven by a round of adversarial review that found the
original single-signal design (seed and withdraw purely off GitHub's
`requested_reviewers` array) unsafe. Both are recorded here as the shipped decision —
see §7 for what the review actually found and why it forced this shape.

**A. Reconcile `state.reviewers` every poll from *two* signals, not one:** GitHub's
`requested_reviewers` array (who is currently being asked) AND this poll's `reviews`
collection (`raw_reviews`, already fetched by `_ingest_items` — no new GH call), which
tells us who has actually responded. Neither signal alone is sufficient: GitHub removes
a reviewer from `requested_reviewers` the instant they submit **any** review, including
`COMMENTED` — so absence from that array is the *ordinary* shape of "they just
reviewed," not evidence of withdrawal. `requested_teams` is read but never expanded or
seeded (team objects carry a slug only, not members; GitHub review attribution is
always by individual login, never by team) — out of scope, a follow-on bead if a real
repo needs it.

**B. Extend `_resolve_poll_phase`'s external-push branch** so an `AWAITING_REVIEW` PR
whose external push leaves a required reviewer needing refresh
(`has_required_reviewers_to_refresh`, `lifecycle/predicates.py:30-38`) advances to
`FIXES_PENDING` — the only phase whose pipeline runs the `rereview` step
(`run.py:_build_pipeline`). Without this, a reviewer `flip_stale_required_reviews`
moves to `NOT_REQUESTED` after an external push has no path to ever being re-requested,
because `AWAITING_REVIEW` is a `_WAITING_PHASES` entry (`run.py:91`) that only ever
calls `wait` and never reaches the pipeline.

### 2.1 Reconciliation, in order

`_reconcile_reviewers(state, requested_reviewers, raw_reviews, *, now) -> bool` runs
**after** `_ingest_items` (not before — the original ordering put reconciliation ahead
of the reviews read specifically so a fast reviewer's activity would be visible the
same poll it was seeded on; keeping that goal now requires reconciliation to see
`raw_reviews`, so it must run after that read, not before it). It does three things, in
this order, over the union of logins in `requested_reviewers` and `raw_reviews`
authors:

1. **Seed an absent identity.** A login with no existing `state.reviewers` entry gets
   one. If the login came from a review, seed its status and `last_review_at` directly
   from that review's own verdict — `REVIEW_FOUND` for an `APPROVED`/
   `CHANGES_REQUESTED` entry (matching `_TERMINAL_REVIEW_STATES`, `poll.py:189`),
   `IN_PROGRESS` otherwise (a `COMMENTED` response or a non-review comment authored by
   that login) — with `last_request_at` also backdated to that same timestamp. Seeding
   status directly here (rather than leaving it to `_observe_engagement`) is
   deliberate: `_observe_engagement`'s existing "activity after `last_request_at`" gate
   (`poll.py:356-363`) only counts activity **strictly newer** than the request time;
   a first-sight reviewer discovered purely via an already-submitted review has no real
   request timestamp to compare against, and stamping `last_request_at=now` (later than
   the review) would make that same review permanently fail the `>` comparison,
   silently losing the exact verdict this bead exists to capture. A login present only
   in `requested_reviewers` (never yet reviewed) seeds the same as before:
   `status=REQUESTED`, `required=True`, `last_request_at=now`.
2. **Reactivate a declined entry.** An existing entry with `status=DECLINED` (any
   `declined_reason` — a prior timeout or a prior withdrawal) whose login reappears in
   `requested_reviewers` this poll resets to `status=REQUESTED`,
   `last_request_at=now`, `declined_at=None`, `declined_reason=None`. Without this, a
   reviewer re-requested after an earlier decline stays permanently `DECLINED` —
   satisfying `G_REVIEWERS` — even though GitHub is actively asking them again.
3. **Decline a withdrawn request — narrowly.** An existing entry declines as
   `DECLINED`/`declined_reason="request-withdrawn"` **only if** its login is absent
   from `requested_reviewers` this poll, has **no** review or comment activity in this
   poll's `raw_reviews`/`new_items`, **and** its current `status` is `REQUESTED` or
   `IN_PROGRESS` — an ask GitHub itself pulled out from under an in-flight request.
   `NOT_REQUESTED` is deliberately excluded from this decline path: under this design
   the only producer of `NOT_REQUESTED` is `flip_stale_required_reviews`
   (`lifecycle/predicates.py`, called from `_apply_sha_attribution` on an external
   push) — it always means "awaiting rereview after invalidation," never "withdrawn,"
   and declining it here would strand it exactly the way finding #3 (§7) described.
   Terminal entries (`REVIEW_FOUND`, `DECLINED`) are untouched, as before.

Bot/human classification (for either a `requested_reviewers` user object or a review's
`user` object — same shape, `login` + optional `type`) mirrors the pinned check in
`human_review.py:88-98` (`user.type == "Bot"`, a `[bot]`-suffixed `login` as a
defensive fallback) as a local 3-line predicate in `poll.py` — duplicated rather than
imported across modules, same reasoning as before: both source predicates are private
and one-purpose, and the coupling isn't worth it at this size.

### 2.2 Phase-resolver change

In `_resolve_poll_phase` (`poll.py:473-506`), the `external_push` branch gains one more
arm, checked after the existing `QUIESCED`/`HUMAN_GATED` arms and before the
unconditional `return phase`:

```python
if phase is PRPhase.AWAITING_REVIEW and has_required_reviewers_to_refresh(state):
    return PRPhase.FIXES_PENDING
```

`has_required_reviewers_to_refresh` (already public, already imported by `run.py`) is
evaluated against the state *after* reconciliation runs, so it reflects this poll's
freshly-flipped `NOT_REQUESTED` entries. This is self-resolving, not a ping-pong: once
in `FIXES_PENDING`, the pipeline's `rereview` step (guarded by `_rereview_guard`, the
same predicate) re-requests the stale reviewer and flips them to `REQUESTED`, so the
next end-of-cycle resolution has nothing left to refresh. Returning `FIXES_PENDING`
with no new items to fix is not a new pattern — bootstrap already does this
(`_resolve_poll_phase`'s `phase is IDLE` arm returns `FIXES_PENDING` whenever
`has_items`, regardless of whether those items are new); the existing resolver
(`resolver.py:resolve_end_of_cycle_phase`) already returns a fixes-pending PR to
`AWAITING_REVIEW` once its pipeline has nothing left to do, so no resolver change is
needed beyond this one new arm.

## 3. What "required" means here

There is no config surface for a required-reviewer allowlist today (grepped
`config.py` — nothing). The only signal prgroom has for "should this reviewer block
quiescence" is GitHub's own requested-reviewers list, so every seeded `ReviewerState`
gets `required=True` uniformly. If a future need arises to mark some requested
reviewers as optional (an allowlist config key, say), that is a separate, additive
change — this bead does not block it and does not attempt to anticipate its shape.

## 4. Out of scope

- `requested_teams` expansion (§2) — follow-on bead if needed.
- Any config surface for reviewer requiredness — none exists; not invented here.
- Changes to `rereview_pr`, `_g_reviewers`, `_observe_engagement`, or
  `evaluate_reviewer_timeouts` themselves — all four already do the right thing once
  the dict is populated correctly; this bead's code changes are confined to
  `poll.py` (`_reconcile_reviewers` plus the one `_resolve_poll_phase` arm in §2.2).
- agents-config-abn9.8.52 (Codex bot support) — this bead unblocks it but does not
  implement per-bot re-review mechanism selection or reaction-based clean-pass
  detection.

## 5. Test plan and acceptance criteria

Extends `tests/unit/test_lifecycle_poll.py`, which already has a fake `GhCli` builder
(`_gh()`) queuing REST responses in `poll_pr`'s exact call order, plus reviewer
fixtures (`_required_reviewer`, `_requested_at`) already shaped as `ReviewerState`
dicts.

New behaviors:

1. First-seen reviewer seeded from `requested_reviewers` only (no review yet):
   `_gh(requested_reviewers=["alice"])` against an otherwise-empty `state.reviewers` →
   after `poll_pr`, `state.reviewers["alice"]` exists with `status=REQUESTED`,
   `required=True`, `kind=HUMAN`, `last_request_at==now`.
2. **First-poll-after-response (the critical-finding regression guard):** a reviewer
   absent from `requested_reviewers` but present in this poll's `reviews` with an
   `APPROVED`/`CHANGES_REQUESTED` verdict, no pre-existing `state.reviewers` entry →
   seeded directly to `status=REVIEW_FOUND`, `last_review_at` == that review's own
   timestamp, `last_request_at` backdated to the same value. `_g_reviewers` sees them
   as done on this very first poll — never vacuously empty.
3. Same case with a `COMMENTED` verdict (the P1 regression guard): seeds to
   `status=IN_PROGRESS`, not `REVIEW_FOUND` and not declined.
4. Bot classification: a `requested_reviewers` **or** a review's `user` object with
   `type="Bot"` (or a `[bot]`-suffixed login, no `type` field) seeds `kind=BOT`.
5. Already-known, still-requested reviewer is left alone: a reviewer already in
   `state.reviewers` with a non-default `last_request_at`/`status`, still present in
   `requested_reviewers`, no new review activity → unchanged (no reset, no duplicate).
6. **Reactivation on re-request:** a `DECLINED` entry (either `declined_reason`) whose
   login reappears in `requested_reviewers` → resets to `REQUESTED`,
   `last_request_at=now`, `declined_at`/`declined_reason` cleared.
7. **Withdrawal is narrow:** a `REQUESTED`/`IN_PROGRESS` reviewer absent from
   `requested_reviewers` **and** with no review/comment activity this poll → declines
   to `DECLINED`/`request-withdrawn`.
8. **`NOT_REQUESTED` never auto-declines (the P1 regression guard):** a reviewer
   `flip_stale_required_reviews` has already moved to `NOT_REQUESTED` (simulating a
   post-external-push invalidation), absent from `requested_reviewers` this poll →
   stays `NOT_REQUESTED`, is not declined.
9. **Activity masks a spurious decline (the other P1 regression guard):** a `REQUESTED`
   reviewer absent from `requested_reviewers` this poll, but present in `raw_reviews`
   with a `COMMENTED` verdict → engages to `IN_PROGRESS` (existing `_observe_engagement`
   behavior), is never declined, even though they are simultaneously absent from
   `requested_reviewers`.
10. `requested_teams` is read and ignored: a payload carrying `requested_teams` but no
    matching `requested_reviewers`/`reviews` entry does not seed anything from the team
    array.
11. Reconciliation contributes to `activity`: a poll that seeds, reactivates, or
    declines at least one reviewer advances `last_activity_at`; a poll where the
    reviewer set is unchanged does not.
12. **Phase-resolver arm (§2.2):** a PR in `AWAITING_REVIEW` with a required reviewer
    in `NOT_REQUESTED` and an external push observed this poll → `poll_pr` returns
    `phase=FIXES_PENDING`, not `AWAITING_REVIEW`. A PR in the same state but with no
    `NOT_REQUESTED` required reviewer (nothing to refresh) stays `AWAITING_REVIEW` — no
    regression to the existing `external_push` no-op arms (`QUIESCED`→
    `AWAITING_REVIEW`, `HUMAN_GATED`→`FIXES_PENDING`, unconditional `return phase`).

**Existing-test ripple** (mechanical — `_gh()` gains a `requested_reviewers: list[str]
| None = None` parameter defaulting to an empty GitHub array; every existing call site
that pre-seeds a `REQUESTED`/`IN_PROGRESS` reviewer via
`_required_reviewer(ReviewerStatus.REQUESTED)` / `_requested_at(...)` and then calls
`poll_pr` **without** matching review/comment activity for that login must also pass
`requested_reviewers=["copilot"]` to its `_gh(...)` call, or the new narrow-withdrawal
path (behavior 7) declines that reviewer before the test's own engagement/timeout
assertion runs. Call sites seeding `NOT_REQUESTED` or `REVIEW_FOUND`/`DECLINED`
reviewers need no change (behaviors 8, 5's terminal counterpart). Enumerate the exact
call sites during implementation with
`grep -n "_required_reviewer(ReviewerStatus.REQUESTED\|_requested_at(" tests/unit/test_lifecycle_poll.py`
— a spot-check this session found at least `test_requested_reviewer_past_start_timeout_auto_declines`
(`test_lifecycle_poll.py:923`) and every `_requested_at(...)`-based engagement test
(`test_lifecycle_poll.py:500-624` region) as certain hits.

**AC (agents-config-abn9.8.51):** behaviors 1–12 covered, one red-green cycle each; the
existing-test ripple applied in full; `make ci-prgroom` green from the package
worktree root. Restated against the bug report: `state.reviewers` is non-empty after a
real poll wherever GitHub reports a pending request **or** an already-submitted review,
including on the very first poll a fast reviewer is seen (behaviors 2–3); `rereview_pr`
has required reviewers to act on, and the `AWAITING_REVIEW` phase itself no longer
blocks that step from ever running (behavior 12); `_g_reviewers` evaluates over real
entries instead of vacuously passing; a reviewer's request being pulled mid-flight is
distinguished from them simply having reviewed or being mid-rereview (behaviors 7–9);
`ReviewerKind.BOT` and `is_bot` in the `status --json` envelope carry real data.

## 6. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` GitHub's `requested_reviewers` array is a complete, current snapshot of
  pending review requests on every `pulls/{n}` read (no pagination needed — GitHub does
  not paginate this sub-array; unlike the issue comments / reviews / review-comments
  collections, which do need `--paginate`, per `poll.py`'s existing docstring at
  lines 19-22).
- `ASSUMPTION:` `required=True` for every seeded reviewer is correct with no config
  surface to override it (§3) — if a real repo later wants an optional-reviewer
  concept, that is new, additive config, not a revision of this bead's seeding logic.
- `ASSUMPTION:` Duplicating the 3-line bot-classification logic locally in `poll.py`,
  rather than importing `human_review._is_bot` across module boundaries, is the right
  call at this size — it is a private, one-purpose helper whose cross-module reuse
  would trade a few duplicated lines for a coupling its docstring doesn't advertise.
  Revisit only if a third seeding-adjacent site needs the same logic.
- `ASSUMPTION:` Backdating `last_request_at`/`last_review_at` to a review's own
  timestamp for a first-poll-after-response reviewer (§2.1.1) is sufficient for every
  downstream consumer of those fields. Checked: `evaluate_reviewer_timeouts` only acts
  on `REQUESTED`/`IN_PROGRESS` (a `REVIEW_FOUND`-seeded reviewer is exempt);
  `_g_idle`/quiescence's idle timer reads `state.last_activity_at`, not a per-reviewer
  field, so it is untouched by this backdating.
- `ASSUMPTION:` `has_required_reviewers_to_refresh` evaluated *after* reconciliation
  (§2.2) is the correct read order — it must see this poll's freshly-flipped
  `NOT_REQUESTED` entries (from `flip_stale_required_reviews`, which runs earlier in
  `_apply_sha_attribution`) to decide whether `AWAITING_REVIEW` should advance.

## 7. Review findings applied here

This design's §2 differs from the version first approved conversationally. A Codex
review pass and an adversarial Codex review pass, both run against the initially
committed spec, independently converged on the same root defect: the original design
used presence/absence in `requested_reviewers` as the sole signal for both reviewer
*identity* and every state transition, when that set changes for at least three
unrelated reasons (the reviewer responded; their prior review was invalidated by our
own push-tracking and awaits re-request; an operator actually pulled the request) —
and conflated all three into one "declare withdrawn" rule.

Four findings, all addressed in §2 above:

- **Critical (adversarial pass):** a reviewer who already submitted any review before
  prgroom's first poll is never seeded at all — GitHub had already removed them from
  `requested_reviewers` by the time of that first read. Fixed by §2.1's dual-signal
  seeding (behaviors 2–3).
- **P1 (standard pass):** a reviewer submitting a `COMMENTED` review mid-poll-cycle
  would be declared withdrawn before their (non-terminal, per this codebase's MVP
  model) engagement was observed. Fixed by reordering reconciliation after
  `_ingest_items` and excluding any login with this-poll activity from the decline path
  (behavior 9).
- **P1 (standard pass):** a reviewer invalidated by `flip_stale_required_reviews` after
  an external push had no path back to being re-requested — `AWAITING_REVIEW` never
  reaches the `rereview` pipeline step — so the next poll would wrongly declare them
  withdrawn instead of stale-pending-rereview. Fixed by excluding `NOT_REQUESTED` from
  the decline path (behavior 8) and by §2.2's phase-resolver arm, which gives that
  reviewer an actual path to re-request.
- **P2 (standard pass):** a reactivated (re-requested) reviewer whose prior state was
  `DECLINED` stayed permanently declined. Fixed by §2.1.2's reactivation rule
  (behavior 6).

## Continuations

- none — this spec is the deliverable for agents-config-abn9.8.51. (agents-config-abn9.8.52,
  Codex bot support, is an existing sibling bead this work unblocks, not a new
  continuation to mint.)
