# prgroom Disposition Contract — per-item exposure and merge-guard consumption

**Status:** Draft (pending review)
**Beads:** agents-config-abn9.8.27 (per-item disposition surface), agents-config-abn9.8.13.1 (merge-guard consumption + seam repair). One spec, two beads — edits here affect both; each bead's AC section is separate (§9).
**Related:** agents-config-abn9.8.28 produces the `posted_reply_ids` field this contract defines (§5); agents-config-abn9.8.26 owns the `decided_by` provenance fix this contract's field semantics depend on (§3.3); agents-config-abn9.8.31 is adjudicated in §8; `docs/architecture/review-merge-policy/design.md` reserves the clearance hook this spec implements (its "design-reserved and not yet implemented" eligibility-predicate row); `2026-06-20-prgroom-fix-verify-subsystem.md` §6.3 is a sibling additive envelope extender (§7).

## 1. Problem

Three defects/gaps, all verified against current `main`:

1. **Store split.** merge-guard's `untriaged_feedback` blocker (`check-merge-eligibility.sh`, the inventory-union block) reads terminal dispositions and posted-reply exclusions ONLY from the legacy `~/.claude/state/pr-inventory/` files and their `.replyids` sidecars. prgroom persists PR state at `$XDG_STATE_HOME/prgroom/` (fallback `~/.local/state/prgroom/`). A prgroom-groomed PR therefore can never clear the blocker through prgroom's own triage — live-reproduced on PR #211, where prgroom correctly dispositioned Copilot's review_summary as skipped and merge-guard kept blocking anyway.
2. **Dead seam.** The eligibility script's existing prgroom integration invokes `prgroom status --json` with **no PR argument**, but the `status` verb requires a positional PR ref (`owner/repo#n` or URL). The call always fails, `2>/dev/null` swallows the usage error, and `prgroom_available` has never been `true` in production. The two aggregate-boolean blockers (`prgroom_blocker`, `prgroom_error`) are dead code today.
3. **Rollup-only envelope.** `status --json` exposes `items_summary` counts and four `merge_gates` booleans, never per-item state. The review-merge policy design explicitly reserves "a per-item prgroom disposition as an alternative clearance source" and notes it is not yet implemented. This spec implements that reservation.

## 2. Decision

**prgroom remains the sole owner of its state schema; the contract is versioned JSON over the CLI.** `prgroom status --json` gains an `items[]` array (§3). merge-guard's `untriaged_feedback` blocker unions prgroom's terminal-clean dispositions and posted-reply IDs as an **additional** exclusion source alongside the legacy inventory union, which stays intact until the Phase-1 cutover retires it (§4). Fail-closed semantics are preserved throughout: prgroom data only ever *adds* exclusions, never removes one, and its absence reproduces today's behavior exactly.

Rejected alternatives:

- **Shared contract library/file both pipelines write** — three writers, a migration of a skill already slated for retirement (the Phase-1/Phase-2 cutover beads), and a second source of truth inside prgroom that will drift from its store.
- **merge-guard reconstructs dispositions from GitHub live state** — GitHub has no disposition object; a skipped/deferred decision is not inferable from GH, and author-login exclusion is banned by policy ("never excluded by author login"). Retained only as a narrowed resilience follow-on (§8).
- **prgroom writes the legacy inventory format** — chains prgroom to a dying schema through a lossy 7→3 disposition mapping. Pure debt.

## 3. The `items[]` contract

### 3.1 Shape

`status --json` gains a top-level `items` array, one element per persisted `ReviewItem`, serialized as a **deliberate projection** (not a full state dump — `body_excerpt`, `rationale`, `commits`, and cluster bookkeeping stay private):

```json
{
  "phase": "quiesced",
  "items_summary": { "…": "unchanged" },
  "merge_gates": { "…": "unchanged" },
  "items": [
    {
      "kind": "review_summary",
      "gh_id": "3141592653",
      "thread_id": "",
      "author": "copilot-pull-request-reviewer[bot]",
      "disposition": {
        "kind": "skipped",
        "decided_at": "2026-07-03T14:07:11Z",
        "decided_by": "claude sonnet"
      },
      "replied": true,
      "resolved": false,
      "posted_reply_ids": ["4875007359"]
    },
    {
      "kind": "issue_comment",
      "gh_id": "2718281828",
      "thread_id": "",
      "author": "reviewer-human",
      "disposition": null,
      "replied": false,
      "resolved": false,
      "posted_reply_ids": []
    }
  ]
}
```

### 3.2 Field semantics

| Field | Source | Semantics |
|---|---|---|
| `kind` | `ReviewItem.kind` | `review_thread` \| `review_summary` \| `issue_comment` |
| `gh_id` | `Identity.gh_id` | **Uniform natural key**: the GitHub object's own `id` for every kind — issue-comment ID for `issue_comment`, review ID for `review_summary`, inline-comment ID for `review_thread`. `(kind, gh_id)` is the item's natural key, and it matches the keys merge-guard's live queries already use (`.id` on issue comments, `.id` on reviews). No key translation layer. |
| `thread_id` | `Identity.thread_id` | GraphQL `PRRT_*` node id; non-empty only for `review_thread` items. |
| `author` | `ReviewItem.author` | GitHub login of the item's author. Informational — consumers MUST NOT use it for exclusion (policy: exclusion by exact recorded reply ID, never author login). |
| `disposition` | `ReviewItem.disposition` | `null` when the item has not been processed (== untriaged). Otherwise `{kind, decided_at, decided_by}`. `rationale`/`commits` are deliberately omitted from the projection. |
| `disposition.kind` | `DispositionKind` | One of `fixed`, `already_addressed`, `skipped`, `deferred`, `wont_fix`, `escalated`, `failed`. |
| `disposition.decided_by` | `Disposition.decided_by` | **The agent that actually produced the decision.** See §3.3 — this semantic is load-bearing and currently mis-stamped on fallback. |
| `replied` / `resolved` | `ReviewItem` booleans | Reply posted / thread resolved, as already persisted. |
| `posted_reply_ids` | new persisted field | The GitHub comment IDs of replies **prgroom itself posted** for this item, recorded durably at post time (§5). Empty until the reply-ledger bead lands; an empty list is always safe (fewer exclusions = fail-closed). |

Durability rule: an item appears with a non-null `disposition` **only after** that disposition has been durably persisted (the store writes via `flock` + atomic rename; `status` reads are lock-free but never partial). There is no "completed pass" marker and none is needed — the legacy `skill_a_completed` guard exists because legacy inventory FIX/SKIP calls were not durable mid-run; prgroom's are.

### 3.3 `decided_by` provenance dependency

The dispatcher currently stamps `decided_by` from the **configured** primary of the fallback chain, not the link that actually produced the result. The contract's field semantic is "the actual producer"; shipping `items[]` before that fix means the envelope exports a known-wrong value. The dispatcher-observability bead (agents-config-abn9.8.26) owns the fix. Sequencing note: `items[]` MAY ship first (merge-guard does not consume `decided_by`), but telemetry consumers MUST NOT trust `decided_by` until that bead closes.

### 3.4 Envelope evolution discipline

The `items` key is **additive**: every existing envelope key (`phase`, `last_error`, `items_summary`, `merge_gates`, `human_review`, `auto_merge_eligible`) is byte-for-byte unaffected. The fix-verify subsystem spec (§6.3) proposes a sibling additive `verify` block; both extensions compose without coordination beyond "additive only, never mutate existing keys." Two naming collisions are noted for doc hygiene, not resolved here: the model-routing ladder's `escalated_to` (next model rung) and the review-feedback loop's own `disposition` vocabulary are unrelated axes that happen to share words with `disposition.kind = escalated`.

## 4. merge-guard consumption

All changes land in `check-merge-eligibility.sh`'s untriaged block and its prgroom section; the output schema (`status`, `blockers[]`, `facts`, `base_ref_oid`) is untouched — the agent-ruling path's Step-5 full-floor re-run consumes that schema and inherits this blocker's correctness unchanged.

### 4.1 Repair the seam

Invoke `prgroom status --json "${OWNER}/${REPO}#${PR}"` (the required PR-ref argument). Keep the existing guards: command-exists, non-empty output, `jq -e '.merge_gates'`. `prgroom_available` becomes meaningful for the first time; the two existing aggregate-boolean blockers start functioning as designed. (No behavior change where prgroom is absent — identical degradation.)

### 4.2 Union into the exclusion sets

With `prgroom_available=true` and an `items` array present:

- `$agent_replies` += every `items[].posted_reply_ids[]` entry (all items, any disposition state — reply IDs are recorded at post time and are valid exclusions regardless of triage completion, matching the legacy partial-inventory rule).
- `$done_issue` += `gh_id` of items with `kind == "issue_comment"` AND `disposition.kind` ∈ CLEARING_SET.
- `$done_review` += `gh_id` of items with `kind == "review_summary"` AND `disposition.kind` ∈ CLEARING_SET.

**CLEARING_SET = `{fixed, already_addressed, skipped, deferred, wont_fix}`. Blocking: `{escalated, failed}` and `disposition: null`.**

This is a 1:1 realization of the policy prose ("fixed / already-addressed / skipped / deferred / won't-fix"). It is deliberately *higher-fidelity than the legacy source*: the legacy inventory classification can only express SKIP and FIX+committed/already_addressed — `deferred` and `wont_fix` are prose-only there. The prgroom source is the first implementation that can honor all five clearing kinds. `escalated`/`failed` remain blockers, consistent with the adjacent no-internal-blocker-items gate.

### 4.3 Semantics preserved

- **Fail-closed:** prgroom missing from PATH, no state file for the PR, malformed envelope, or missing `items` key → the prgroom union contributes nothing and the legacy-only behavior is bit-identical to today. A prgroom item can only *clear* a live GH item; nothing prgroom says can suppress a blocker the legacy path would raise on its own evidence, and an item present on GH but unknown to prgroom stays a blocker.
- **Not head-scoped, by design:** the untriaged check deliberately unions across the PR's full push history. prgroom's store is per-PR (slug-keyed), item identities persist across pushes — the same scope. (Contrast: the `bot_review_cap_exhausted` fact is head-exact and is explicitly out of scope, §7.)
- **Either source clears:** legacy inventory and prgroom items are a plain union; a disposition durably recorded in either is sufficient. This is what makes the three implementation beads independently shippable and the eventual legacy retirement a deletion, not a migration.

## 5. `posted_reply_ids` production (interlock with the reply-ledger bead)

This spec defines the **field contract**; agents-config-abn9.8.28 designs and implements the recording. Constraints the contract imposes on that design:

1. **Record-at-post-time durability:** the reply's GitHub comment ID must be persisted (atomic store write) in the same reply step that posted it — per-POST cadence, not per-verb-step — so a crash between POST and a later batch write cannot lose the ID. The PR #211 self-reply spiral (prgroom re-triaging its own four replies as fresh feedback) is exactly this window.
2. Patterns proven in the legacy sidecar work (PR #212) that the ledger design should adopt: fail-loud appends via explicit `if`-guards (never the RHS of `&&` under `set -e`); any idempotency/content hash must exclude the bookkeeping field itself so recording success does not change the item's identity.
3. prgroom needs **no sidecar file**: the legacy sidecar exists because legacy inventory writes were not durable; prgroom's store is. The ledger is the `posted_reply_ids` list on the item (plus, if the ledger bead finds it necessary, a PR-level list for replies that cannot be attributed to an item).

Ship order flexibility: the envelope bead may ship before the ledger bead — `posted_reply_ids: []` is valid and fail-closed. Recommended sequence: ledger → envelope → merge-guard consumption, all three before the Phase-1 end-to-end proof re-runs.

## 6. Sequencing

```
abn9.8.28 (reply ledger)      ──┐
abn9.8.27 (items[] envelope)  ──┼──▶  abn9.8.13.1 (merge-guard union + seam repair)
abn9.8.26 (decided_by fix)    ──┘         │  (26 gates only telemetry trust, not shipping)
                                          ▼
                              abn9.8.13 E2E re-run (fix→push→reply→resolve, clean)
                                          ▼
                              abn9.8.20 cutover → abn9.8.14 retirement
```

Each of 8.28 / 8.27 / 8.13.1 is independently shippable (union semantics, empty-list safety). All three land before the Phase-1 proof re-run; the destructive cutover stays gated on that proof exactly as today.

## 7. Out of scope — charted, not dropped

- **`bot_review_cap_exhausted`** stays on its head-exact legacy inventory read. It is PR-scoped re-review round bookkeeping, not a per-item disposition — it has no home in `items[]`. Full legacy-inventory retirement therefore needs a future PR-scoped surface (a `rereview` block on the envelope is the natural shape; prgroom already tracks rounds internally). Charted for the cutover epic; not this contract.
- **Stall-detection / dual-signal fields** (adversarial-QA team spec, UC3 adoption item): a real future envelope want, too undefined to reserve fields for. Watch that bead before any `items[]` v2.
- **Reconstruct-from-GitHub fallback** for merge-guard independence: see §8.
- **monitor-pr enrichment** (surfacing per-item dispositions in its reporting): free rider on this contract; no changes required, may adopt opportunistically.

## 8. Adjudication of the shared-contract bead (agents-config-abn9.8.31)

That bead proposed (a) a shared read library for the PR-state contract and (b) reconstruct-from-GitHub when the contract is absent. Ruling under this spec:

- **(a) is realized by this contract** — the agreed schema+location is prgroom's CLI JSON surface, owned by prgroom, consumed by merge-guard. No neutral library; the process boundary is the seam. This half is subsumed and closes with the consumption bead.
- **(b) survives, narrowed:** reconstruction can recover *reply-exclusion* facts (replies prgroom posted are discoverable via GH) but can never recover *dispositions* (GitHub has no disposition object) — so it is a resilience enhancement for one of the two exclusion classes, not an alternative source of the contract. The bead should be rescoped to exactly that and remain deferred.

## 9. Test plans and acceptance criteria

Both plans enumerate behaviors; implementation commits them one red-green cycle at a time (no bulk test-first). The `items[]` JSON is a serialization contract, so field names/values are pinned at the envelope boundary — that is contract-pinning, not tautology.

### 9.1 Envelope bead (agents-config-abn9.8.27) — pytest, `packages/prgroom`

Behaviors:

1. A state with one item per kind, mixed dispositions → `items[]` carries each item with `kind`, `gh_id`, `thread_id`, `author`, `replied`, `resolved` exactly as persisted.
2. An undispositioned item → `disposition: null` (never a sentinel object).
3. A dispositioned item → `disposition.kind/decided_at/decided_by` present; `rationale`/`commits`/`body_excerpt` absent from the projection.
4. `posted_reply_ids` surfaces when present on the item; absent field on old persisted state deserializes as `[]` (migration-safe).
5. All pre-existing envelope keys are unchanged for the same state (backward compatibility of `merge_gates` / `items_summary` / `auto_merge_eligible`).

AC: behaviors 1–5 covered; `make ci-prgroom` green (repo coverage floor applies); the §4.6 envelope docs in the prgroom design doc gain the `items` key.

### 9.2 Consumption bead (agents-config-abn9.8.13.1) — `check-merge-eligibility_test.sh` (extends the existing 134-assertion suite, stub/fixture pattern; prgroom stubbed as a fake binary emitting canned envelopes)

Behaviors:

1. Live `issue_comment`, prgroom disposition `fixed` → no `untriaged_feedback` blocker.
2. Same item, disposition `escalated`, `failed`, or `null` → blocker stands.
3. Dispositions `deferred` and `wont_fix` clear (the two kinds legacy cannot express — the fidelity gain is asserted, not assumed).
4. Live `review_summary` matching a prgroom `posted_reply_ids` entry → excluded as the agent's own reply.
5. prgroom absent from PATH → output identical to today's legacy-only run (byte-compare the decision JSON).
6. Malformed/empty envelope, or envelope without `items` → treated as absent (fail-closed), aggregate booleans still honored when present.
7. Union: an item cleared by legacy inventory alone and another cleared by prgroom alone → both excluded in one run.
8. The decision JSON's schema (`status`, `blockers[]`, `facts`, `base_ref_oid`) is unchanged across all above cases.
9. The script passes the PR ref to `status` (seam repair) — asserted via the stub recording its argv.

AC: behaviors 1–9 as new assertions in the existing suite, all 134 existing assertions still green; the eligibility-predicate row in `docs/architecture/review-merge-policy/design.md` is amended in place from "design-reserved, not yet implemented" to documenting the live prgroom clearance source (that design doc is evergreen; the dated 2026-07-01 plan is a historical artifact and is not edited).
