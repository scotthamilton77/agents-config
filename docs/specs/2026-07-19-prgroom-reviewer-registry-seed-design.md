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

Three coordinated changes, driven by two rounds of independent review (Codex + an
adversarial Codex pass, then a GLM-5.2 pass) that each found the reconciliation design
unsafe in a new way. All three are recorded here as the shipped decision — see §7 for
what each round found and why it forced this shape.

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

**B. Extend `_resolve_poll_phase`** with two new arms, both driven by state
reconciliation produces rather than by `state` itself (the function's existing
signature is scalar-only, `(phase, *, merged, new_item, external_push, has_items)` —
this stays true; two more caller-computed booleans join `has_items`):

- An `AWAITING_REVIEW` PR whose external push leaves a required reviewer needing
  refresh (`needs_reviewer_refresh`, sourced from `has_required_reviewers_to_refresh`,
  `lifecycle/predicates.py:30-38`, evaluated post-reconciliation) advances to
  `FIXES_PENDING` — the only phase whose pipeline runs the `rereview` step
  (`run.py:_build_pipeline`). Without this, a reviewer `flip_stale_required_reviews`
  moves to `NOT_REQUESTED` after an external push has no path to ever being
  re-requested, because `AWAITING_REVIEW` is a `_WAITING_PHASES` entry (`run.py:91`)
  that only ever calls `wait` and never reaches the pipeline.
- A `QUIESCED` PR whose reviewer gate would now fail (`reviewers_gate_open`, sourced
  from a newly-public `reviewers_gate_satisfied` predicate in `quiescence.py` — the
  existing `_g_reviewers` logic, renamed and exported) reopens to `AWAITING_REVIEW`,
  independent of whether a push happened this poll. A reviewer can be newly requested
  (or reactivated, §2.1.2) on a PR with no new commits at all — an operator manually
  requesting review on an already-quiesced PR — and the existing resolver only ever
  reopened `QUIESCED` via `external_push` or `new_item`, neither of which fires for
  that case.

**C. Narrow "refreshable" so it excludes a deliberate withdrawal.**
`_REFRESHABLE_STATUSES` (`predicates.py:25-27`) and `_REFRESHABLE`
(`rereview.py:38`) both currently treat *any* `DECLINED` reviewer — regardless of
`declined_reason` — as eligible for a fresh ask. Combined with change A/B this becomes
actively wrong: a reviewer explicitly declined as `request-withdrawn` (§2.1.3) would
still be re-requested by `rereview_pr` the next time a push makes
`has_required_reviewers_to_refresh` true, silently overriding an operator's deliberate
pull. Both call sites move to one new shared predicate,
`reviewer_needs_refresh(r: ReviewerState) -> bool` in `predicates.py`:
`r.status is NOT_REQUESTED or (r.status is DECLINED and r.declined_reason !=
"request-withdrawn")` — replacing the two near-duplicate frozenset checks with one
definition instead of two that must be kept in sync.

### 2.1 Reconciliation, in order

`_reconcile_reviewers(state, requested_reviewers, raw_reviews, *, now) -> bool` runs
**after** `_ingest_items` (not before — the original ordering put reconciliation ahead
of the reviews read specifically so a fast reviewer's activity would be visible the
same poll it was seeded on; keeping that goal now requires reconciliation to see
`raw_reviews`, so it must run after that read, not before it). It does three things, in
this order, over the union of logins in `requested_reviewers` and `raw_reviews`
authors:

1. **Seed an absent identity.** A login with no existing `state.reviewers` entry gets
   one. **A pending request outranks any historical verdict.** A login present in
   `requested_reviewers` this poll seeds `status=REQUESTED`, `required=True`,
   `last_request_at=now`, **regardless of any `APPROVED`/`CHANGES_REQUESTED` review it
   also carries in `raw_reviews`**. GitHub removes a login from `requested_reviewers`
   the instant it submits **any** review, so a login *still* listed there that also has
   reviews on record can only mean the request post-dates every one of those reviews — a
   re-request whose wanted fresh review has not landed yet. Seeding it `REVIEW_FOUND`
   from the stale verdict would let `_g_reviewers` pass and the PR quiesce behind the
   reviewer's back. (The one theoretical race — a review submitted between the PR-resource
   GET and the reviews GET within a single poll, making both signals true with the review
   fresher — is out of scope here: presence-in-`requested_reviewers` wins by design, no
   request/head-freshness timestamp heuristic is built at seed time.)

   Only a login present **exclusively** in `raw_reviews` (absent from
   `requested_reviewers` this poll — a fast reviewer GitHub already cleared, or a drive-by)
   is seeded directly from that review's own verdict: `REVIEW_FOUND` for an
   `APPROVED`/`CHANGES_REQUESTED` entry (matching `_TERMINAL_REVIEW_STATES`,
   `poll.py:189`), `IN_PROGRESS` otherwise (a `COMMENTED` response — the only other
   authored-by-this-login signal `raw_reviews` itself carries; a plain issue/review
   comment is a different collection this reconciliation does not consult, so it is
   never this branch's trigger) — with both `last_review_at` and `last_request_at`
   backdated to that review's own timestamp. Seeding status directly here (rather than
   leaving it to `_observe_engagement`) is deliberate: `_observe_engagement`'s existing
   "activity after `last_request_at`" gate (`poll.py:356-363`) only counts activity
   **strictly newer** than the request time; a first-sight reviewer discovered purely via
   an already-submitted review has no real request timestamp to compare against, and
   stamping `last_request_at=now` (later than the review) would make that same review
   permanently fail the `>` comparison, silently losing the exact verdict this bead
   exists to capture. **`required` is `True` only if the login is present in
   `requested_reviewers` this poll; a login seeded purely from `raw_reviews` (never
   formally requested — a drive-by review) seeds `required=False`.** Per §3, the only
   signal prgroom has for "should this block quiescence" is GitHub actually asking —
   a reviewer nobody requested cannot be allowed to block it just by having an
   opinion.
2. **Reactivate a declined entry — only a genuine withdrawal.** An existing entry with
   `status=DECLINED` **and `declined_reason=="request-withdrawn"` specifically**
   whose login reappears in `requested_reviewers` this poll resets to
   `status=REQUESTED`, `last_request_at=now`, `declined_at=None`,
   `declined_reason=None`. This is deliberately **not** "any `declined_reason`":
   a timeout-declined reviewer (`timeout-no-start`/`timeout-stalled`, set by
   `evaluate_reviewer_timeouts`, `quiescence.py:106-136`) was never removed from
   GitHub's `requested_reviewers` in the first place — that decline is a purely local
   state mutation with no GitHub call (`_decline`, `quiescence.py:138-141`) — so their
   login is *continuously* present in `requested_reviewers`, every poll, forever.
   Reactivating on bare presence would read as "reappeared" every single poll for a
   silent reviewer and instantly undo the timeout decline within the same cycle,
   making the timeout gate impossible to durably satisfy. `request-withdrawn`
   (§2.1.3) is the one decline reason that is *itself defined* by the login having
   been observed absent from `requested_reviewers` — so a later reappearance for that
   reason, specifically, is a genuine transition, not a static presence.
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

`_resolve_poll_phase` (`poll.py:473-506`) gains two new scalar parameters, computed by
`poll_pr` immediately after reconciliation (same style as the existing `has_items`) —
not `state` itself, keeping the function's existing scalar-only signature intact:

- `reviewers_gate_open: bool` — `reviewers_gate_satisfied(state)` (§2's change B; the
  renamed, exported `_g_reviewers`).
- `needs_reviewer_refresh: bool` — `has_required_reviewers_to_refresh(state)`
  (already public, already imported by `run.py`).

Two new arms:

```python
if phase is PRPhase.QUIESCED and not reviewers_gate_open:
    return PRPhase.AWAITING_REVIEW
...
if external_push:
    if phase is PRPhase.QUIESCED:
        return PRPhase.AWAITING_REVIEW
    if phase is PRPhase.HUMAN_GATED:
        return PRPhase.FIXES_PENDING
    if phase is PRPhase.AWAITING_REVIEW and needs_reviewer_refresh:
        return PRPhase.FIXES_PENDING
    return phase
```

The `QUIESCED`/`reviewers_gate_open` arm is placed early (checked unconditionally,
ahead of the `external_push` block) because its trigger — a reviewer newly requested
or reactivated on an already-quiesced PR — has nothing to do with a push; the existing
`external_push`-gated `QUIESCED → AWAITING_REVIEW` arm stays, covering the
push-triggered reopen case (new commits landing on a quiesced PR), and `new_item`'s
existing unconditional arm already reopens `QUIESCED` for a fresh comment — this bead
changes neither.

The `AWAITING_REVIEW`/`needs_reviewer_refresh` arm is self-resolving, not a
ping-pong, **once change C (§2) lands**: `needs_reviewer_refresh` and the pipeline's
`_rereview_guard` (`run.py:441`, `push_awaiting_rereview AND
has_required_reviewers_to_refresh` — a conjunction, not the identical predicate this
arm uses alone) both read the same underlying `reviewer_needs_refresh` set after
change C, so a reviewer this arm considers refreshable is the same one `rereview_pr`
will actually act on. Before change C, a `DECLINED/request-withdrawn` entry alone
could satisfy `needs_reviewer_refresh` without `push_awaiting_rereview` (which tracks
SHA invalidation, not withdrawal) ever being true, sending the pipeline into
`FIXES_PENDING` on every external push with nothing to actually refresh there — change
C's narrowing removes withdrawn entries from `needs_reviewer_refresh` entirely, so
this can no longer happen. Returning `FIXES_PENDING` with no new items to fix is not a
new pattern — bootstrap already does this (`_resolve_poll_phase`'s `phase is IDLE` arm
returns `FIXES_PENDING` whenever `has_items`, regardless of whether those items are
new); the existing resolver (`resolver.py:resolve_end_of_cycle_phase`) already returns
a fixes-pending PR to `AWAITING_REVIEW` once its pipeline has nothing left to do, so no
resolver change is needed beyond these two new arms.

## 3. What "required" means here

There is no config surface for a required-reviewer allowlist today (grepped
`config.py` — nothing). The only signal prgroom has for "should this reviewer block
quiescence" is GitHub actually asking them — presence in `requested_reviewers` — so
`required=True` iff that is true this poll, `False` otherwise (§2.1.1: this is what
excludes a drive-by `raw_reviews`-only reviewer from blocking quiescence). If a future
need arises to mark some requested reviewers as optional (an allowlist config key,
say), that is a separate, additive change — this bead does not block it and does not
attempt to anticipate its shape.

## 4. Out of scope

- `requested_teams` expansion (§2) — follow-on bead if needed.
- Any config surface for reviewer requiredness — none exists; not invented here.
- Changes to `_observe_engagement` / `evaluate_reviewer_timeouts` themselves — both
  already do the right thing once the dict is populated correctly.
- agents-config-abn9.8.52 (Codex bot support) — this bead unblocks it but does not
  implement per-bot re-review mechanism selection or reaction-based clean-pass
  detection.

**Scope note (revised from the first-committed version of this spec):** this bead's
code changes are **not** confined to `poll.py`. Two rounds of review (§7) surfaced
real correctness gaps that only close by also touching `predicates.py` (the new
`reviewer_needs_refresh` predicate, change C), `rereview.py` (consuming it instead of
`_REFRESHABLE`), and `quiescence.py` (exporting `_g_reviewers` as
`reviewers_gate_satisfied`). All three are small, mechanical extractions/renames of
existing logic — no new behavior in those modules beyond narrowing an existing
frozenset check — but they are real file-count growth from the originally-scoped
"purely additive to `poll.py`," recorded honestly here rather than glossed over.

**Production plumbing this pulls in** (also unacknowledged in the first-committed
version): `_pr_is_merged` (`poll.py:180-183`) currently reads `pulls/{n}` and discards
everything but `merged_at` — it must instead return (or a sibling helper must expose)
the full payload so `requested_reviewers` reaches reconciliation without a second GET.
`_ingest_items` (`poll.py:192-248`) currently returns `(new_items, terminal_reviews)`
and discards `raw_reviews` itself — its return shape gains `raw_reviews` (or an
equivalent) so reconciliation can see full review authorship, not just the
already-reduced terminal-verdict map.

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
6. **Reactivation on re-request:** a `DECLINED/request-withdrawn` entry whose login
   reappears in `requested_reviewers` → resets to `REQUESTED`, `last_request_at=now`,
   `declined_at`/`declined_reason` cleared. (Scoped to this reason only — see behavior
   14 for the `timeout-*` counter-case this excludes, and why.)
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
12. **Phase-resolver arm, push case (§2.2):** a PR in `AWAITING_REVIEW` with a required
    reviewer in `NOT_REQUESTED` and an external push observed this poll → `poll_pr`
    returns `phase=FIXES_PENDING`, not `AWAITING_REVIEW`. A PR in the same state but
    with no `NOT_REQUESTED` required reviewer (nothing to refresh) stays
    `AWAITING_REVIEW` — no regression to the existing `external_push` no-op arms
    (`QUIESCED`→`AWAITING_REVIEW`, `HUMAN_GATED`→`FIXES_PENDING`, unconditional
    `return phase`).
13. **Phase-resolver arm, no-push case (§2.2, GLM finding):** a PR in `QUIESCED` gains
    a newly-`requested_reviewers`-present reviewer with **no** commits/push involved
    this poll → `poll_pr` returns `phase=AWAITING_REVIEW`. A `QUIESCED` PR whose
    reviewer set is fully satisfied stays `QUIESCED`.
14. **Reactivation is withdrawal-only (GLM critical-finding regression guard):** a
    `DECLINED/timeout-no-start` reviewer whose login is (and always was) present in
    `requested_reviewers` this poll — the timeout never removed them from GitHub's
    side — stays `DECLINED`; it is not reactivated. A `DECLINED/request-withdrawn`
    reviewer whose login reappears in `requested_reviewers` **does** reactivate
    (behavior 6, now scoped to this reason only).
15. **Drive-by reviewer is not required (GLM finding):** a login present only in
    `raw_reviews` (never in `requested_reviewers`) seeds with `required=False`; their
    continued `COMMENTED` activity across polls never blocks `G_REVIEWERS` and never
    trips `evaluate_reviewer_timeouts` in a way that matters for quiescence.
16. **`request-withdrawn` is never re-requested (GLM finding, `predicates.py`/
    `rereview.py`):** a `DECLINED/request-withdrawn`, `required=True` reviewer, with an
    external push that would otherwise trigger `has_required_reviewers_to_refresh` →
    `reviewer_needs_refresh` excludes them; `rereview_pr` issues no DELETE/POST for
    that login. A `DECLINED/timeout-no-start` reviewer in the same setup **is** still
    refreshed — the narrowing is specific to the withdrawal reason.
17. **A pending request outranks a historical verdict (Codex P2 regression guard):** a
    first-seen login present in `requested_reviewers` this poll **and** also carrying an
    older `APPROVED`/`CHANGES_REQUESTED` review in `raw_reviews` → seeds
    `status=REQUESTED`, `required=True`, `last_request_at=now` (NOT `REVIEW_FOUND`), and
    `reviewers_gate_satisfied` is **False** — the re-request's fresh review is still
    pending. The negative control (behavior 2) is unchanged: the same verdict with the
    login *absent* from `requested_reviewers` still seeds `REVIEW_FOUND`.

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

**AC (agents-config-abn9.8.51):** behaviors 1–16 covered, one red-green cycle each; the
existing-test ripple applied in full; `make ci-prgroom` green from the package
worktree root. Restated against the bug report: `state.reviewers` is non-empty after a
real poll wherever GitHub reports a pending request **or** an already-submitted review,
including on the very first poll a fast reviewer is seen (behaviors 2–3); `rereview_pr`
has required reviewers to act on, and neither `AWAITING_REVIEW` nor `QUIESCED` blocks
that step or a re-open from ever happening (behaviors 12–13); `_g_reviewers` evaluates
over real entries instead of vacuously passing, and its internal timeout mechanism is
not immediately self-defeating (behavior 14); a reviewer's request being pulled
mid-flight is distinguished from them simply having reviewed, being mid-rereview, or
having merely commented uninvited (behaviors 7–9, 15); a deliberate withdrawal is
never silently undone by the existing refresh machinery (behavior 16);
`ReviewerKind.BOT` and `is_bot` in the `status --json` envelope carry real data.

## 6. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` GitHub's `requested_reviewers` array is a complete, current snapshot of
  pending review requests on every `pulls/{n}` read (no pagination needed — GitHub does
  not paginate this sub-array; unlike the issue comments / reviews / review-comments
  collections, which do need `--paginate`, per `poll.py`'s existing docstring at
  lines 19-22).
- `ASSUMPTION:` `required` tracking `requested_reviewers` presence exactly (`True` iff
  requested this poll, `False` for a `raw_reviews`-only drive-by — §2.1.1, §3) is
  correct with no config surface to override it — if a real repo later wants an
  optional-*requested* reviewer concept, that is new, additive config, not a revision
  of this bead's seeding logic.
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
- `ASSUMPTION:` `has_required_reviewers_to_refresh` / `reviewers_gate_satisfied`
  evaluated *after* reconciliation (§2.2) is the correct read order for both new
  resolver arms — they must see this poll's freshly-flipped `NOT_REQUESTED` entries
  and freshly-seeded/reactivated `REQUESTED` entries to decide whether
  `AWAITING_REVIEW`/`QUIESCED` should advance.
- `ASSUMPTION:` Restricting reactivation to `declined_reason=="request-withdrawn"`
  (§2.1.2) is exhaustive — no other `declined_reason` value can mean "GitHub is
  actively re-asking." The only two producers of `DECLINED` in this design are
  `evaluate_reviewer_timeouts` (`timeout-no-start`/`timeout-stalled`, GitHub-side
  request untouched) and §2.1.3's withdrawal path (GitHub-side request actually
  removed) — if a third decline reason is ever added, it must be classified against
  this same "did GitHub's own list change" test before deciding whether it
  reactivates.
- `ASSUMPTION:` Promoting `_g_reviewers` to a public `reviewers_gate_satisfied` in
  `quiescence.py`, and replacing the two `_REFRESHABLE`/`_REFRESHABLE_STATUSES`
  frozensets with one shared `reviewer_needs_refresh` predicate in `predicates.py`, are
  correctly-scoped extractions — not behavior changes to the modules that already
  worked, just de-duplication of logic this bead's correctness now depends on holding
  in exactly one place.

## 7. Review findings applied here

This design's §2 differs from the version first approved conversationally, across two
independent review rounds.

**Round 1 — Codex review + adversarial Codex review** (run against the
initially-committed spec) independently converged on the same root defect: the
original design used presence/absence in `requested_reviewers` as the sole signal for
both reviewer *identity* and every state transition, when that set changes for at
least three unrelated reasons (the reviewer responded; their prior review was
invalidated by our own push-tracking and awaits re-request; an operator actually
pulled the request) — and conflated all three into one "declare withdrawn" rule.

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
  the decline path (behavior 8) and by §2.2's push-triggered phase-resolver arm, which
  gives that reviewer an actual path to re-request.
- **P2 (standard pass):** a reactivated (re-requested) reviewer whose prior state was
  `DECLINED` stayed permanently declined. Fixed, at the time, by an "any
  `declined_reason`" reactivation rule — which round 2 then found unsafe.

**Round 2 — GLM-5.2 review** (`openrouter-claude-subagent`, run against the
round-1-revised spec, explicitly instructed not to restate round 1's findings) found
that the round-1 fix for its own P2 finding was itself broken, plus three further gaps:

- **Critical:** the "any `declined_reason`" reactivation rule (round 1's P2 fix)
  defeats `evaluate_reviewer_timeouts`'s no-start timeout — a timeout-declined
  reviewer was never removed from GitHub's `requested_reviewers` (the timeout makes no
  GH call), so their continuous presence reads as "reappeared" every poll, reactivating
  them within the same cycle the decline happened. Verified directly against
  `quiescence.py`'s `_decline` (pure state mutation, no GH call) before accepting this
  finding. Fixed by narrowing reactivation to `declined_reason=="request-withdrawn"`
  only (§2.1.2, behavior 14) — the one reason that is itself defined by an observed
  absence, making a later reappearance a genuine transition.
- **Medium:** a `QUIESCED` PR never re-evaluates when a reviewer is newly requested or
  reactivated with no push involved — only `external_push`/`new_item` reopened it.
  Fixed by §2.2's new unconditional `QUIESCED`/`reviewers_gate_open` arm (behavior 13).
- **Medium:** a reviewer seeded purely from `raw_reviews` (a drive-by review, never
  formally requested) got `required=True` under the original blanket rule, letting an
  uninvited chatty commenter block quiescence indefinitely. Fixed by §2.1.1's
  requested-only `required` rule (behavior 15).
- **Medium:** the existing `_REFRESHABLE`/`_REFRESHABLE_STATUSES` sets treat any
  `DECLINED` reviewer as refreshable regardless of reason, so a push-triggered
  `rereview_pr` would re-request a deliberately `request-withdrawn` reviewer — silently
  overriding an operator action. Verified directly against both frozensets
  (`predicates.py:25-27`, `rereview.py:38`) before accepting this finding. Fixed by
  change C (§2) — the shared `reviewer_needs_refresh` predicate (behavior 16).
- Four **low**-severity findings (a mislabeled first-sight `timeout-stalled` on a
  backdated `COMMENTED` seed; the §2.2 pseudocode passing `state` where the real
  signature takes scalars; unacknowledged `_pr_is_merged`/`_ingest_items` return-shape
  changes; imprecise wording equating `_rereview_guard` with
  `has_required_reviewers_to_refresh`) are folded into §2.1–§2.2's current wording and
  §4's plumbing note directly; none required a distinct fix beyond stating the design
  precisely.

## Continuations

- none — this spec is the deliverable for agents-config-abn9.8.51. (agents-config-abn9.8.52,
  Codex bot support, is an existing sibling bead this work unblocks, not a new
  continuation to mint.)
