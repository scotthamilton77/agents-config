# prgroom: reframe the outer PR-review cap as a retry budget

Bead: `agents-config-abn9.8.25`. Target state is pinned by the fca6.16 HLD
artifacts (`docs/architecture/prgroom/data-view.md`, `state-machine.md`): the
outer cap becomes a **PR-review retry budget** expressed with the same
vocabulary as the designed inner fix↔verify budget.

## Renames (mechanical)

| Current | Target |
|---|---|
| `ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED` | `ErrorCode.LIFECYCLE_PR_REVIEW_EXHAUSTED` |
| `PRGroomingState.round` (state JSON key `round`) | `pr_review_retries_used` |
| `PrgroomConfig.max_rounds` / `DEFAULT_MAX_ROUNDS = 3` | `pr_review_retries` / `DEFAULT_PR_REVIEW_RETRIES = 5` |
| `--max-rounds` (run verb) | `--pr-review-retries` |
| `PRGROOM_MAX_ROUNDS` | `PRGROOM_PR_REVIEW_RETRIES` |
| `.prgroom.toml` `max_rounds` | `pr_review_retries` |
| `RoutedMemory.round` (JSON key `round`) | `retry` |
| `ItemRecurrence.first_seen_round` (snapshot JSON key) | `first_seen_retry` |
| status envelope key `round` | `pr_review_retries_used` |

Precedence unchanged: flag > env > toml > default.

## Counter re-mechanization (semantic)

`pr_review_retries_used` is a **0-indexed count of fix-push retries consumed**:
the first observed review-eliciting push (by either §3.4 bootstrap path) costs
0; every subsequent review-eliciting push costs 1. Exhaustion:
`has_queued_fix_commits AND pr_review_retries_used >= pr_review_retries`.
Off-by-one pinned: default 5 retries = up to 6 review-eliciting pushes
including the initial.

§3.4 semantics preserved, shifted by one:

- **`_poll` bootstrap** (`last_poll_sha == ""`, non-empty HEAD): set
  `last_poll_sha`, leave the counter untouched (replaces `round = max(round, 1)`).
- **`_push`**: increment iff the push is not the initial observed push. The
  initial-push predicate, evaluated before mutating SHAs:
  `last_poll_sha == "" and last_pushed_head_sha == ""`.
- **`_poll` attribution** (`last_poll_sha != ""`): CLI's own push → no
  increment; external push → `+1` + reviewer flip. Unchanged.
- **Cap-reach warning** in `_push` fires when the post-increment counter
  equals the budget (was `round == max_rounds`).
- **Entry-probe re-arm** and resolver priority 1 use the new predicate + code.

## Schema

Key renames stay within `schema_version` 1 with **no migrator**: prgroom is
not yet deployed (no installer route), so no state files exist outside dev
scratch. A stray old-key file fails loud through the store's corrupt-state
path rather than silently loading wrong semantics.

## Prose

- Code docstrings/comments: retire hard-cap vocabulary in the touched modules.
- `docs/architecture/prgroom/` Status banners: flip the "built" side of the
  cap-rename caveats (counter field, error code, flag now match target); keep
  every verify-step caveat (that is bead 8.23.2, still unbuilt).
- Dated plan docs (`docs/plans/2026-05-12-prgroom-cli-design.md`) are
  point-in-time artifacts — untouched.

## Test plan (TDD)

Semantic slices get new/adjusted failing tests first; pure renames update the
existing tests as the spec, watch them fail, then rename source.

1. errors: enum member + registry prose + `BlockingErrorCodes` membership.
2. config: default 5; flag/env/toml precedence under new names.
3. state serde: `pr_review_retries_used` round-trip; bootstrap zero-value.
4. poll/push counter: bootstrap anchors 0; initial push +0; subsequent CLI
   push +1; external push +1; CLI-own-push no-count; warn at budget.
5. run/resolver: cap trips at `>= 5` queued; entry-probe re-arm on raised
   budget; escalation label predicate; status envelope key.
6. RoutedMemory/reply markers (`retry` dedup key), recurrence/snapshot
   (`first_seen_retry`).
7. Sweep: zero `LIFECYCLE_HARD_CAP_EXCEEDED` / `max_rounds` / `MAX_ROUNDS`
   references in `packages/prgroom`; `make ci-prgroom` green.
