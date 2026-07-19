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

Add one new private step to `poll_pr` (`lifecycle/poll.py`) that reconciles
`state.reviewers` against the PR resource's `requested_reviewers` array on **every
poll** — not bootstrap-only. `poll_pr` already fetches `pulls/{n}` for `_pr_is_merged`
(`poll.py:180-183`); this reuses that same payload rather than issuing a new GET.

Three sub-decisions, each made with you this session:

1. **Reconcile every poll, not just at bootstrap.** A reviewer requested after the PR's
   first poll (a co-reviewer added later) is a real case with no other code path to
   catch it, and `poll_pr` already re-derives everything else (items, CI, SHA
   attribution) fresh every cycle — bootstrap-only would be the odd one out.
2. **A reviewer removed from `requested_reviewers` without ever reviewing is immediately
   marked `DECLINED` (`declined_reason="request-withdrawn"`)** — not left to expire via
   `evaluate_reviewer_timeouts`, and not dropped from the dict. GitHub itself says the
   request is gone; waiting out `review_start_timeout`/`review_finish_timeout` for a
   request that no longer exists would block quiescence for no reason, and dropping the
   entry would lose the `declined_at`/`declined_reason` history `status --json` and the
   operator may want. A reviewer already in a terminal status (`REVIEW_FOUND`,
   `DECLINED`) is left untouched by this path — a real verdict, or an already-recorded
   decline, is not overwritten just because GitHub stopped listing a now-resolved
   request.
3. **`requested_teams` is read but not expanded or seeded — out of scope.** GitHub's
   REST payload gives team objects (slug only); expanding to individual members needs a
   separate Teams API call, and GitHub review attribution is always by individual user
   login, never by team — a team-keyed `ReviewerState` couldn't resolve against real
   review data anyway. This is a distinct, separable feature (own API cost, own identity
   question) left for a follow-on bead if a real repo needs it.

### Seeding a newly-seen reviewer

For each `login` present in `requested_reviewers` but absent from `state.reviewers`:

```python
ReviewerState(
    identity=login,
    kind=<BOT if the user object looks like a bot, else HUMAN>,
    status=ReviewerStatus.REQUESTED,   # not NOT_REQUESTED
    required=True,                     # GH already deciding to request it is the only
                                        # "required" signal prgroom has (§3 below)
    last_request_at=now,
)
```

`status=REQUESTED` (not `NOT_REQUESTED`) matters mechanically:
`rereview_pr`'s `_REFRESHABLE` set is `{NOT_REQUESTED, DECLINED}`
(`lifecycle/rereview.py:38`) — seeding as `REQUESTED` means a reviewer GitHub already
asked (which is exactly what "present in `requested_reviewers`" means) is not
immediately re-asked via the remove/re-add dance on the very poll that discovers them.

Bot/human classification mirrors the pinned check in `human_review.py:88-98`
(`user.type == "Bot"`, `login` ending in `[bot]` as a defensive fallback for payloads
that omit `type`) but operates directly on the `requested_reviewers` user object rather
than a wrapping review object — a 3-line local predicate in `poll.py`, not a
cross-module import of a private helper (`_is_bot` stays `lifecycle/human_review.py`
internal; duplicating the one-line check avoids a private cross-module coupling for
something this small).

### Withdrawing a reviewer

For each existing `state.reviewers` entry whose login is **absent** from this poll's
`requested_reviewers` and whose `status` is not already in `{REVIEW_FOUND, DECLINED}`:
set `status=DECLINED`, `declined_at=now`, `declined_reason="request-withdrawn"`. This
reuses the same field-mutation shape as `quiescence.py`'s existing `_decline()`
(`quiescence.py:138-141`) but is written as its own 3-line block in `poll.py` rather than
importing that private helper across modules — same reasoning as the classification
predicate above.

### Placement in `poll_pr`

The reconciliation call sits in the existing `pr = _gh_get(gh, ref,
f"{base}/pulls/{ref.number}")`-adjacent flow (today folded into `_pr_is_merged`,
`poll.py:180-183`) — refactored so the raw PR resource is fetched once and both
`merged` and the reviewer reconciliation read from it, **before** `_ingest_items` /
`_observe_engagement` run. Ordering it first means a reviewer requested and reviewed
within the same poll window (a fast bot reviewer) is seeded in time for
`_observe_engagement` to observe their activity on that same cycle, rather than needing
a second poll to notice them at all.

`_reconcile_reviewers(state, pr, *, now) -> bool` returns whether anything changed, the
same contribution-to-`activity` shape every other poll sub-step already uses
(`_ingest_items`'s `new_items`, `_ci_state`'s comparison, `_apply_sha_attribution`'s
`external_push`).

## 3. What "required" means here

There is no config surface for a required-reviewer allowlist today (grepped
`config.py` — nothing). The only signal prgroom has for "should this reviewer block
quiescence" is GitHub's own requested-reviewers list, so every seeded `ReviewerState`
gets `required=True` uniformly. If a future need arises to mark some requested
reviewers as optional (an allowlist config key, say), that is a separate, additive
change — this bead does not block it and does not attempt to anticipate its shape.

## 4. Out of scope

- `requested_teams` expansion (§2.3) — follow-on bead if needed.
- Any config surface for reviewer requiredness — none exists; not invented here.
- Changes to `rereview_pr`, `_g_reviewers`, `_observe_engagement`, or
  `evaluate_reviewer_timeouts` — all four already do the right thing once the dict is
  non-empty; this bead is purely additive to `poll.py`.
- agents-config-abn9.8.52 (Codex bot support) — this bead unblocks it but does not
  implement per-bot re-review mechanism selection or reaction-based clean-pass
  detection.

## 5. Test plan and acceptance criteria

Extends `tests/unit/test_lifecycle_poll.py`, which already has a fake `GhCli` builder
(`_gh()`) queuing REST responses in `poll_pr`'s exact call order, plus reviewer
fixtures (`_required_reviewer`, `_requested_at`) already shaped as `ReviewerState`
dicts.

New behaviors:

1. First-seen reviewer is seeded: `_gh(requested_reviewers=["alice"])` against an
   otherwise-empty `state.reviewers` → after `poll_pr`, `state.reviewers["alice"]`
   exists with `status=REQUESTED`, `required=True`, `kind=HUMAN`,
   `last_request_at==now`.
2. Bot classification: a `requested_reviewers` user object with `type="Bot"` (or a
   `[bot]`-suffixed login, no `type` field) seeds `kind=BOT`.
3. Already-known reviewer is left alone: a reviewer already in `state.reviewers` with a
   non-default `last_request_at`/`status` and still present in `requested_reviewers` →
   unchanged (no reset, no duplicate).
4. Withdrawn non-terminal reviewer auto-declines: a `REQUESTED`/`IN_PROGRESS`/
   `NOT_REQUESTED` reviewer absent from this poll's `requested_reviewers` → flips to
   `DECLINED`, `declined_reason="request-withdrawn"`.
5. Withdrawn terminal reviewer is untouched: a `REVIEW_FOUND` or already-`DECLINED`
   reviewer absent from `requested_reviewers` → status, `declined_reason` (if any)
   unchanged.
6. `requested_teams` is read and ignored: a payload carrying `requested_teams` but no
   matching `requested_reviewers` entry does not seed anything from the team array.
7. Reconciliation contributes to `activity`: a poll that seeds or declines at least one
   reviewer advances `last_activity_at`; a poll where the reviewer set is unchanged
   does not (mirrors the existing no-noise pattern in `_observe_engagement`).
8. Seed-then-engage in one poll: a reviewer newly present in `requested_reviewers` AND
   whose terminal review appears in the same poll's `reviews` response → both fire
   within the one `poll_pr` call (seeded as `REQUESTED`, then flipped to
   `REVIEW_FOUND` by the existing `_observe_engagement`), proving the ordering
   decision in §2.

**Existing-test ripple** (mechanical — `_gh()` gains a `requested_reviewers: list[str]
| None = None` parameter defaulting to an empty GitHub array; every existing call site
that pre-seeds a **non-terminal** reviewer via `_required_reviewer(ReviewerStatus.
REQUESTED)` / `_required_reviewer(ReviewerStatus.NOT_REQUESTED)` / `_requested_at(...)`
and then calls `poll_pr` must also pass `requested_reviewers=["copilot"]` (the
fixtures' shared login) to its `_gh(...)` call, or the new withdrawal path force-declines
that reviewer before the test's own engagement/timeout assertion gets to run.
Call sites seeding only `REVIEW_FOUND` reviewers need no change — terminal statuses are
protected from withdrawal by design (§2.2)). Enumerate the exact call sites during
implementation with
`grep -n "_required_reviewer(ReviewerStatus.REQUESTED\|_required_reviewer(ReviewerStatus.NOT_REQUESTED\|_requested_at(" tests/unit/test_lifecycle_poll.py`
— a spot-check this session found at least `test_requested_reviewer_past_start_timeout_auto_declines`
(`test_lifecycle_poll.py:923`) and every `_requested_at(...)`-based engagement test
(`test_lifecycle_poll.py:500-624` region) as certain hits.

**AC (agents-config-abn9.8.51):** behaviors 1–8 covered, one red-green cycle each; the
existing-test ripple applied in full; `make ci-prgroom` green from the package
worktree root. Restated against the bug report: `state.reviewers` is non-empty after a
real poll wherever GitHub reports pending review requests; `rereview_pr` has required
reviewers to act on; `_g_reviewers` evaluates over real entries instead of vacuously
passing; `ReviewerKind.BOT` and `is_bot` in the `status --json` envelope carry real
data.

## 6. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` GitHub's `requested_reviewers` array is a complete, current snapshot of
  pending review requests on every `pulls/{n}` read (no pagination needed — GitHub does
  not paginate this sub-array; unlike the issue comments / reviews / review-comments
  collections, which do need `--paginate`, per `poll.py`'s existing docstring at
  lines 19-22).
- `ASSUMPTION:` `required=True` for every seeded reviewer is correct with no config
  surface to override it (§3) — if a real repo later wants an optional-reviewer
  concept, that is new, additive config, not a revision of this bead's seeding logic.
- `ASSUMPTION:` Duplicating the 3-line bot-classification and decline-mutation logic
  locally in `poll.py`, rather than importing `human_review._is_bot` /
  `quiescence._decline` across module boundaries, is the right call at this size — both
  are private, one-purpose helpers whose cross-module reuse would trade a few
  duplicated lines for a coupling neither module's docstring currently advertises.
  Revisit only if a third seeding-adjacent site needs the same logic.

## Continuations

- none — this spec is the deliverable for agents-config-abn9.8.51. (agents-config-abn9.8.52,
  Codex bot support, is an existing sibling bead this work unblocks, not a new
  continuation to mint.)
