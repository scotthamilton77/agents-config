# Merge-gate triage-aware thread blocker and cap-fact path repair

**Date:** 2026-07-16
**Status:** Approved (design)
**Beads:** agents-config-abn9.8.34 (unresolved_threads triage-blindness), agents-config-abn9.8.35 (bot_review_cap_exhausted dead path). One spec, two beads — each bead's AC section is separate (§9).
**Related:** `docs/architecture/review-merge-policy/design.md` eligibility-predicate rows are amended by this spec (§3); `2026-07-05-prgroom-disposition-contract.md` deliberately scopes prgroom-sourced exclusions to non-thread blockers — this spec fills the thread-level gap via the inventory union instead, and reserves the disposition `items[]` as a future additive source (§7); agents-config-abn9.8.29 (resolve()'s never-resolve-SKIP/ESCALATE policy) is deliberately unchanged — this spec removes the merge-gate pressure that made it look wrong (§7); agents-config-abn9.8.31 (shared PR-state contract library) was rejected as the fix vehicle (§2); `wait-for-pr-comments/filter-actionable-threads.sh` is the in-tree precedent for triage-filtered thread counting (§4).

## 1. Problem

Two defects in `src/user/.agents/skills/merge-guard/check-merge-eligibility.sh`, both live-reproduced on PR #256 (scotthamilton77/agents-config, 2026-07-12):

1. **Triage-blind thread blocker (agents-config-abn9.8.34).** The `unresolved_threads` blocker (lines 202–214) counts every GraphQL review thread with `isResolved == false`, with no awareness of triage classification. But the triage discipline (`wait-for-pr-comments` / `reply-and-resolve-pr-threads`, and prgroom's `resolve()` verb alike) deliberately and permanently leaves SKIP-classified threads unresolved (the SKIP reply is an argument to the reviewer, never accepted on their behalf) and ESCALATE-classified threads unresolved (a human must rule). Net effect: any PR carrying even one legitimate SKIP or ESCALATE can never pass the eligibility floor autonomously. PR #256 final state: 3 unresolved threads (2 correctly ESCALATE, 1 correctly SKIP), `untriaged_feedback_count: 0`, `bot_clean_review_at_head: true` — and a permanent `unresolved_threads` blocker.

2. **Dead cap fail-safe (agents-config-abn9.8.35).** The `bot_review_cap_exhausted` fact (lines 401–416) reads exactly one inventory path built with the **full 40-char** `HEAD_OID`. Neither live writer uses that convention: `wait-for-pr-comments/detect-pr-context.sh:85–87` truncates to **12 hex chars** (`head -c 12`, one path per head — rounds on an unchanged head reuse the same file); prgroom's `LegacyExportStore` (`prsession/legacy_export.py`) embeds the **full 40-char** SHA but carries no `polling.bot_review_cap_exhausted` field from the wait-for-pr-comments polling flow. The fact has silently read `false` in every real invocation since the integration was built — the signal meant to tell a human "the bot kept finding things past the round cap" never fires. (The PR #256 incident additionally produced an ad-hoc, session-written `…-r3.json` suffixed file; that is a manual artifact, not a writer convention — no code constructs round-suffixed filenames.) The existing test (`check-merge-eligibility_test.sh`, cap section) wrote **full-SHA fixture filenames**, reproducing the reader's wrong assumption instead of the writers' real conventions — which is why CI stayed green over a dead code path.

## 2. Decision

Four decisions, owner-ruled 2026-07-16:

1. **Amend the architecture invariant: live enumeration stays; durable terminal triage filters the result.** The current row ("prgroom state is never a substitute") conflates two properties: live *enumeration* of threads (kept — a thread opened after the last triage pass is absent from all state and must block) and a ban on *filtering* the live result against durably recorded triage (dropped — it is the deadlock). State never substitutes for the query; it only partitions the query's result.
   - *Rejected — gate stays state-blind, blocker codes split, policy layer decides:* pushes the judgment into per-repo merge-policy config, so every repo re-decides the same question; the gate still has to read triage state to split the count, so nothing is gained.
   - *Rejected — resolve SKIP threads on GitHub after posting rationale:* overturns the pinned "never resolve SKIP or ESCALATE" discipline (agents-config-abn9.8.29 territory) and accepts the agent's own argument on the reviewer's behalf; largest behavioral blast radius.

2. **Escalated threads block under their own code.** Threads durably classified ESCALATE leave the `unresolved_threads` count and surface as a distinct **`escalations_pending`** blocker that hard-blocks the eligibility floor until a human rules. No autonomous merge sails past an unanswered escalation, and the blocker output stops mislabeling why the PR is blocked. The routing keys on the ESCALATE classification alone, not on `escalation_filed`: `wait-for-pr-comments` inventories always carry `escalation_filed = true` on written ESCALATEs (`validate-inventory.sh` Guard 8 rejects anything else), while prgroom's `LegacyExportStore` legitimately omits the field (§4.3) — both shapes must land in the same honest bucket, and both hard-block either way.
   - *Rejected — filed ESCALATE stops blocking entirely* (the bead's literal fix direction): the escalation is tracked out-of-band, but nothing would then stop an autonomous merge landing before the human answers.
   - *Rejected — ESCALATE stays in the generic count:* same net block, but the gate's output stays ambiguous about why, and operators keep triaging a lie.

3. **Ground truth is the completed-inventory union.** The same glob-and-union over `~/.claude/state/pr-inventory/${OWNER}-${REPO}-${PR}-*.json` that the `untriaged_feedback` blocker already trusts, restricted to completed passes (`crash_recovery.skill_a_completed == true`), extended to `review_thread`-kind items. Both live pipelines feed it: `wait-for-pr-comments` writes it directly; prgroom writes byte-compatible files via `LegacyExportStore` (PR #274) — so the source survives the Phase-1 cutover.
   - *Rejected — wait for the disposition contract's `items[]`:* not implemented, its spec scopes exclusions to non-thread blockers, and the deadlock stays live until it ships.
   - *Rejected — layer both sources now:* the union already carries prgroom's dispositions via `LegacyExportStore`; a second read path adds surface without adding information. The `items[]` projection remains reserved as a future additive source (§7).

4. **The cap fact reads by 12-char-prefix glob (reader-side fix only).** `check-merge-eligibility.sh` matches `${OWNER}-${REPO}-${PR}-<first-12-of-HEAD_OID>*.json` and ORs the field across matches. One script changes; the glob matches both live writer conventions — 12-char (`detect-pr-context.sh`) and full-40 (`LegacyExportStore`) — and tolerates ad-hoc suffixed artifacts like the PR #256 incident file, while staying head-scoped.
   - *Rejected — writers switch to full SHA:* changes a tested convention in two writers across two pipelines.
   - *Rejected — shared path-construction helper:* structurally soundest, but gates a P1 fix on reviving the deferred agents-config-abn9.8.31.

## 3. Amended architecture rows

`docs/architecture/review-merge-policy/design.md`, eligibility-predicate table. Ship these amendments **in the implementation PR, alongside the code change** — doc and code move in lockstep; the spec PR does not touch design.md.

Replace the "No unresolved review threads (bot or human)" row's source text with:

> **Always** a live GitHub query at merge time **enumerates** every review thread — state never substitutes for enumeration: a thread opened after the last triage pass is absent from every durable record and blocks. The live unresolved set is then **partitioned** against durably recorded triage state (the completed-inventory union — same source discipline as the non-thread row below), aggregated per thread across all of the thread's recorded items: a thread whose records are all `SKIP` with replies posted is excluded (the SKIP reply is an argument to the reviewer, deliberately never resolved on their behalf); a thread with any `ESCALATE` record moves to the "No pending escalations" row; everything else — untriaged, `FIX`-but-still-unresolved, `SKIP` without a posted reply — blocks here.

Add a new row directly below it:

> | No pending escalations | Threads durably classified `ESCALATE` in the completed-inventory union surface as the `escalations_pending` blocker. Hard-blocks every autonomous merge path until a human rules; the ruling gesture is resolving the thread on GitHub (see the spec's clearing semantics). Not waivable by any merge rule. |

## 4. The `unresolved_threads` partition contract (agents-config-abn9.8.34)

### 4.1 GraphQL change

The `reviewThreads` query's node selection gains the thread id: `nodes{isResolved}` → `nodes{id isResolved}` (both the first-page and cursor-page queries). The pagination loop collects `{id, isResolved}` pairs instead of bare counts.

### 4.2 Triage record collection

From the same inventory glob the `untriaged_feedback` block already walks (`find "${HOME}/.claude/state/pr-inventory" -maxdepth 1 -name "${OWNER}-${REPO}-${PR}-*.json"`), restricted to files whose `crash_recovery.skill_a_completed == true` (terminal dispositions may only come from a completed pass — the discipline the non-thread block already enforces at its `completed_inventory_items` split):

- collect items with `kind == "review_thread"` and `thread_id != null`;
- group by `thread_id` into a **list** of records `{classification, posted_reply_id, rationale}` — one thread yields multiple records both within one inventory (a multi-comment thread produces one item per comment, all sharing the `thread_id`; see `fetch-and-normalize-comments.sh`'s per-comment item mapping) and across inventories (re-triage in later rounds);
- an unreadable or malformed file is skipped (`|| continue`), matching the existing block's tolerance — its items simply contribute nothing, which fails closed.

### 4.3 Partition ladder

Each live unresolved thread is placed by the first matching rung, evaluated over **all** of its collected records:

1. **Any record with `classification == "ESCALATE"`** → **`escalations_pending` blocker.** Covers both writer shapes: `wait-for-pr-comments` ESCALATEs (always `escalation_filed = true` — Guard 8) and prgroom `LegacyExportStore` exports, which emit only `kind`/`classification`/`fix_outcome`/`posted_reply_id` — no `escalation_filed`, no `rationale` — and collapse prgroom's ESCALATED **and DEFERRED** dispositions to `"ESCALATE"`. A deferred thread therefore also lands here, which fails toward human attention (a deferral nobody sees must not enable an autonomous merge). An ESCALATE record beats any coexisting SKIP records for the same thread: inventory files carry no reliable cross-round ordering, so failing toward human attention is the only safe tie-break; this cannot deadlock because the human's ruling gesture removes the thread from the live unresolved set entirely (§5).
2. **At least one record, and every record is `SKIP` with `posted_reply_id != null`** → **excluded**; counted in `facts.thread_triage.skip_excluded`. Every comment's concern in the thread was answered with a posted argument.
3. **Everything else** → **`unresolved_threads` blocker.** Untriaged (no record in any completed inventory, including a GraphQL node with a null/missing `id`); any `FIX` record while the thread is still unresolved (a fixed thread should have been resolved by the fix flow — an unresolved FIX is actionable); any `SKIP` lacking a posted reply (the argument never durably reached the reviewer; recoverable by re-running the reply pass).

The ladder is total and mutually exclusive by construction — every live unresolved thread lands on exactly one rung.

### 4.4 Emitted output

- `unresolved_threads` blocker fires iff rung 3 is non-empty; details string reports the blocking count with its breakdown (untriaged / unresolved-FIX / unposted-SKIP).
- `escalations_pending` blocker fires iff rung 1 is non-empty; details string lists each thread id with the recorded `rationale` (excerpted) where present — prgroom's legacy export records none today, so those entries read `(no rationale recorded)` (see Continuations).
- New fact `thread_triage`: `{live_unresolved: n, skip_excluded: n, escalations_pending: n, blocking: n}` — `live_unresolved = skip_excluded + escalations_pending + blocking` by construction.

## 5. `escalations_pending` clearing semantics

The blocker clears **only** when the thread stops being live-unresolved — i.e. a human (or a fix flow acting on the human's ruling) resolves the thread on GitHub, or the reviewer withdraws it. A later completed inventory re-classifying the thread does **not** clear it (rung 1 precedence, §4.3). This is deliberate:

- Resolution is the one ordering-free, unambiguous ruling signal — one click in the GitHub UI, and already the documented preferred recipe ("resolve rebutted threads + re-run gate").
- Unlike SKIP threads — which the discipline forbids resolving because that would accept the agent's own argument on the reviewer's behalf — an **escalated** thread's resolution is precisely the human's job. The prohibition and the clearing gesture never collide.
- Ruling "needs a fix" also converges: the fix lands, the fix flow resolves the thread, the blocker clears.

## 6. `bot_review_cap_exhausted` path repair (agents-config-abn9.8.35)

Replace the exact-path read (line 407) with a head-prefix glob:

```bash
head12="${HEAD_OID:0:12}"
bot_cap_exhausted=false
while IFS= read -r -d '' cap_file; do
    if jq -e '(.polling.bot_review_cap_exhausted // false) == true' "$cap_file" >/dev/null 2>&1; then
        bot_cap_exhausted=true
        break
    fi
done < <(find "${HOME}/.claude/state/pr-inventory" -maxdepth 1 \
         -name "${OWNER}-${REPO}-${PR}-${head12}*.json" -print0 2>/dev/null)
```

Semantics preserved and extended:

- **Head-scoped:** the 12-hex-char prefix (48 bits) keeps the original "never leak a stale `exhausted=true` from a superseded head" property; a colliding prefix across heads of one PR is negligible, and the leak direction is toward a human-attention *fact*, never toward an autonomous merge.
- **OR across matching files:** once the ask budget is spent at a head, nothing at the same head can un-spend it — any matching file reporting `true` makes the fact `true`.
- **Type-strict and fail-closed retained:** the `jq -e` typed equality stays; absent/malformed/missing-field files contribute `false`.
- **Matches both live writer conventions** — `…-<12char>.json` (detect-pr-context.sh) and `…-<40char>.json` (`LegacyExportStore`, whose full SHA begins with the same 12 chars) — **and tolerates ad-hoc suffixed artifacts** (the PR #256 incident's manually written `…-r3.json`); no writer constructs suffixed filenames, so the tolerance is robustness, not a contract.
- The comment block at lines 402–406 is rewritten to describe the prefix-glob contract (it currently warns against globbing at all — that warning was about the *unscoped* glob, which this fix still avoids).

## 7. Non-goals — deliberately unchanged

- **prgroom `resolve()` policy (agents-config-abn9.8.29):** still never GraphQL-resolves SKIP/ESCALATE threads. This spec removes the merge-gate pressure that made that policy look like a bug; 8.29's residual scope (reconciling skip/deferred/wont_fix vocabularies) is untouched.
- **`untriaged_feedback` block:** logic untouched; §4.2 reuses its source discipline, not its code path.
- **Disposition contract `items[]` (agents-config-abn9.8.27):** remains a reserved future *additive* exclusion source. Thread dispositions already reach this gate via `LegacyExportStore` → inventory union; no dependency is created.
- **prgroom rollup blockers (`prgroom_blocker` / `prgroom_error`) and the merge-authorization axis:** untouched. `escalations_pending` is an eligibility-floor blocker like any other — no merge rule can waive it.

## 8. Test plan

Extend `src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh` (existing stub harness: env-var GraphQL/REST fixtures, `FAKE_HOME` inventory dir). Behavior-level assertions on the emitted JSON only.

Partition (§4):

- `test_untriaged_thread_blocks` — unresolved thread, no inventory record → `unresolved_threads` blocker.
- `test_skip_thread_excluded` — SKIP + `posted_reply_id` in a completed inventory → no thread blocker; `facts.thread_triage.skip_excluded == 1`; overall `eligible` when nothing else blocks.
- `test_skip_without_posted_reply_blocks` — SKIP, `posted_reply_id: null` → `unresolved_threads`.
- `test_escalate_moves_to_escalations_pending` — ESCALATE record (with `escalation_filed: true`, the wait-for-pr-comments shape) → `escalations_pending`, not `unresolved_threads`.
- `test_prgroom_export_escalate` — ESCALATE record with **no** `escalation_filed` or `rationale` keys (the `LegacyExportStore` shape) → `escalations_pending`; details carry `(no rationale recorded)`.
- `test_escalate_beats_skip_for_same_thread` — one thread, ESCALATE record in one completed inventory, SKIP+posted in another → `escalations_pending`.
- `test_multi_item_thread_all_skip_excluded` — one thread, two items (two comments) in one inventory, both SKIP+posted → excluded.
- `test_multi_item_thread_mixed_blocks` — one thread, SKIP+posted item and FIX/committed item, thread still unresolved → `unresolved_threads`.
- `test_incomplete_inventory_ignored` — SKIP record only in a `skill_a_completed: false` file → `unresolved_threads` (completed-only discipline).
- `test_resolved_escalated_thread_clears` — thread resolved on GitHub, stale ESCALATE record remains → no blocker (live enumeration wins).
- `test_partition_across_pages` — SKIP-excluded thread on page 1, untriaged on page 2 → `unresolved_threads` only, counts correct.

Cap fact (§6) — fix the fixture-convention defect and pin both conventions plus suffix tolerance:

- `test_cap_true_12char_filename` — `…-<12char>.json`, `polling.bot_review_cap_exhausted: true` → fact `true` (production-convention regression pin).
- `test_cap_true_full_sha_filename` — `…-<40char>.json` → fact `true` (`LegacyExportStore` convention).
- `test_cap_true_adhoc_suffix_tolerated` — `…-<12char>-r3.json` (ad-hoc artifact shape) → fact `true`.
- `test_cap_stale_head_prefix_false` — file for a different head's prefix, `true` inside → fact `false`.
- Existing type-strict (`"true"` string), absent-field, absent-file, malformed-file cases: retained, rewritten onto the 12-char convention.

## 9. Acceptance criteria

**agents-config-abn9.8.34:**

- The partition ladder of §4.3 is implemented in `check-merge-eligibility.sh`; `escalations_pending` is emitted as a distinct blocker code; `facts.thread_triage` is emitted with the four counts.
- The two design.md row amendments of §3 land in the same PR as the code change.
- A PR in PR #256's final state (1 posted SKIP, 2 filed ESCALATEs, nothing else) reports exactly one blocker, `escalations_pending`, with both thread ids and rationales in the details; after both threads are resolved on GitHub it reports `eligible`.
- All §8 partition tests green.

**agents-config-abn9.8.35:**

- The cap fact resolves `true` through files written by `detect-pr-context.sh`'s real convention (12-char) and by `LegacyExportStore`'s (full-40), and tolerates ad-hoc suffixed filenames; stale-head files never leak; type-strict/fail-closed behavior retained.
- The test fixtures no longer use the fictional full-SHA-only convention as the sole happy path.
- All §8 cap tests green.

## Continuations

- task: `LegacyExportStore` emits `escalation_filed` and `rationale` on exported ESCALATE items — AC: prgroom-sourced ESCALATED/DEFERRED dispositions export with `escalation_filed: true` and the disposition's rationale text, so `escalations_pending` blocker details name the pending question instead of `(no rationale recorded)`; existing byte-compatibility tests extended for the two new keys.
