---
name: reply-and-resolve-pr-threads
description: >
  Use to reply to every PR review thread and resolve the FIXED ones via
  GraphQL. Two modes: invoked automatically by `wait-for-pr-comments`
  (`--from-inventory`), or `--resume` for crash recovery from a partial run.
  Does not fix code. Keywords: reply, resolve, thread, acknowledge, close
  out, post fix confirmation, bookkeeping, rebut, ack.
---

# reply-and-resolve-pr-threads

Reply to every PR review thread (FIX, SKIP, ESCALATE-with-`escalation_filed=true`) and resolve only the FIXED `review_thread`s via GraphQL `resolveReviewThread`.

**This skill does NOT fix code.** It reads a Hand-off Contract inventory written by `wait-for-pr-comments`, posts replies per pinned templates, and resolves only the threads that were actually FIXED. No `quality-reviewer`, no `simplify` skill, no `verify-checklist`, no `git commit`, no `git push`. The only allowed git invocations are `git fetch` and `git merge-base --is-ancestor` in Phase 1.5 recovery triage.

**MERGE PROHIBITION:** Resolving threads is NOT authorization to merge. The orchestrator never merges; the user does, on explicit say-so.

## Skill B: arg protocol

Invoked via `Skill(skill: "reply-and-resolve-pr-threads", args: "<args-string>")`.

**Recognized grammar** (regex-style, all groups optional except the mode-routing pair):

```
(--from-inventory <path>)? (--resume <path>)? (--mode autonomous)? (--bead-id <token>)?
```

Plus tail tokens (operator narration) that are warned-and-ignored.

**Parsing rules:**
- **Lenient (warn-and-ignore):** truly unknown tokens that look like narration (`be careful about formatting`, `please use the inventory at the usual place`).
- **Fatal startup error (recognized-but-malformed):**
  - `--from-inventory` or `--resume` with no value or empty value
  - `--mode` with any value other than `autonomous`
  - `--bead-id` with no value or empty value

**Phase 0 precedence rules** (resolves arg combinations — applied in order):

1. `--from-inventory` and `--resume` are mutually exclusive — both passed = fatal error.
2. `--resume` (or `--from-inventory`) with no path argument = fatal error.
3. Bad JSON or missing file at the supplied path = fatal error (do NOT silently fall through).
4. `--mode autonomous` without `--bead-id` = fatal error.
5. Standalone invocation (no `--from-inventory` and no `--resume`) = fatal error in v1 (standalone mode is deferred to a follow-up bead).
6. Schema validation (`validate-inventory.sh <path>`) failure = fatal error.

On any fatal error: emit a one-line diagnostic naming the rule violated, abort. No replies posted. No inventory writes.

## Skill B: phases (two modes)

Two modes are selected by Phase 0:

- **From-Skill-A** (`--from-inventory <path>`): inventory is fresh and complete. Phases `0 → 1 → 2 → 3 → 4`.
- **Resume** (`--resume <path>`): partial inventory from an interrupted `wait-for-pr-comments` run. Phases `0 → 1 → 1.5 → 2 → 3 → 4`.

Standalone mode is deferred to a follow-up bead.

### Phase 0 — Mode detection + schema validation

Apply the six Phase 0 precedence rules above. After mode is resolved, run schema validation against the supplied path:

```bash
~/.claude/skills/wait-for-pr-comments/validate-inventory.sh \
  <inventory-path> \
  || { echo "schema validation failed"; exit 1; }
```

`validate-inventory.sh` exits 0 if valid, non-zero with the violating item logged to stderr otherwise. On non-zero: abort with no replies posted. The nine guards the validator enforces are documented in §"Schema validation guards" below — they are the contract this skill assumes is honored before Phase 1 begins.

### Phase 1 — Read inventory + verify head SHA

Read the JSON inventory at the supplied path. Pin the inventory's `pr.owner`, `pr.repo`, `pr.number`, `pr.head_sha_after_push`, `polling.copilot_status`, and `items[]` array.

**Head-SHA verification** (from-Skill-A mode only):

```bash
ACTUAL_SHA=$(gh pr view <pr.number> --repo <pr.owner>/<pr.repo> --json headRefOid --jq .headRefOid)
[ "$ACTUAL_SHA" = "<pr.head_sha_after_push>" ] || RETRY=1
```

On mismatch: run `git fetch origin <pr-branch>` and re-check up to **2 times**, with a **5s sleep** between attempts. This handles transient post-push lag from GitHub's mirror replication.

If the mismatch persists after retries: warn and abort with the operator instruction:

> `Another push happened concurrently; reconcile manually then re-invoke reply-and-resolve-pr-threads --resume <inventory-path>.`

**Resume mode skips head-SHA verification entirely** — the inventory is known to be partial; the head SHA is reconciled in Phase 1.5 per-item.

### Phase 1.5 — Recovery triage (resume only)

Skipped in from-Skill-A mode. In resume mode, walk every FIX item with `fix_outcome = "committed"` and verify its `fix_commit_sha` is in the PR branch's history:

```bash
git fetch origin "refs/heads/<pr-branch>:refs/remotes/origin/<pr-branch>"
git merge-base --is-ancestor <fix_commit_sha> origin/<pr-branch>
```

For each item where the SHA is **not** an ancestor of `origin/<pr-branch>` (i.e., never made it to the remote), prompt for triage:

**Interactive mode** — emit a single batched prompt listing every missing-SHA item:

```
Recovery triage for PR #<n>:
  <comment_id> (@<author>): <body_excerpt>
    fix_commit_sha=<sha> is NOT in origin/<pr-branch>.
    Choose: ABANDON | DEFER | FIX-NOW
```

**Autonomous mode** — file via `bd label add <bead-id> human` + `bd update <bead-id> --append-notes "<batched-list>"`, then default each missing-SHA item to `DEFER` for reply purposes.

**Action per choice:**

| Choice | Action |
|---|---|
| `ABANDON` | Re-classify item to SKIP. The reply uses the SKIP template with the user's rationale (collected at the prompt). Do NOT resolve. |
| `DEFER` | Mark item for the recovery-DEFER reply template. Operator must supply a public-tracking link (GitHub issue, PR cross-reference, or public comment permalink). Bead IDs are forbidden in the link. Do NOT resolve. |
| `FIX-NOW` | Operator manually fixes outside this skill, then re-invokes `wait-for-pr-comments` for the PR. Skill B exits cleanly without posting replies for that item. |

There is no unconditional "Pending — addressing in follow-up" promise. Every recovery reply links to a public artifact or carries a SKIP rationale.

Items whose `fix_commit_sha` IS an ancestor of `origin/<pr-branch>` proceed to Phase 2 unchanged.

### Phase 2 — Reply to every item

Walk `items[]`. Reply to every FIX item, every SKIP item, and every ESCALATE item with `escalation_filed = true`. (ESCALATE items with `escalation_filed = false` shouldn't appear — `validate-inventory.sh` would have rejected them — but if they do, skip them.)

Endpoint by `kind`:

| `kind` | Reply endpoint |
|---|---|
| `review_thread` | `gh api repos/<pr.owner>/<pr.repo>/pulls/<pr.number>/comments/<reply_to_comment_id>/replies -F body="..."` |
| `review_summary` | `gh pr comment <pr.number> --body "..."` (reference the review author/`submittedAt` in the body) |
| `issue_comment` | `gh pr comment <pr.number> --body "..."` (cross-reference `<issue_comment_id>` permalink in the body) |

Reply body text is taken **only** from the pinned reply matrix in §"Reply text templates" below — no improvisation. **Substitute angle-bracket placeholders** (`<fix_commit_sha>`, `<fix_summary>`, `<rationale>`, `<linked-comment-permalink>`, `<public-tracking-link>`) with the inventory item's field values BEFORE posting — never post raw template text with literal angle brackets to a PR.

### Phase 3 — Resolve only FIX `review_thread`s

GraphQL mutation, variable-bound:

```bash
gh api graphql -f query='
  mutation($id:ID!){
    resolveReviewThread(input:{threadId:$id}){
      thread{ isResolved }
    }
  }' -F id=<thread_id>
```

**Resolve target set:** items with `kind == "review_thread"` AND `classification == "FIX"` AND a non-null `fix_outcome` (i.e., `committed` or `already_addressed`). All four conditions must hold.

**Never resolve:**
- `classification == "SKIP"` — the reviewer decides whether to accept the rationale
- `classification == "ESCALATE"` — the human owns the resolution
- `kind == "review_summary"` or `kind == "issue_comment"` — there is no thread to resolve; the GraphQL mutation will error

If a resolve call fails (network, permissions, thread already resolved): log the failure, continue with the rest. Phase 4 reports each failure individually.

### Phase 4 — Final report

Emit a structured close-out summary:

```markdown
## PR Thread Reply + Resolve Complete

**PR:** #<pr.number> — <pr.owner>/<pr.repo>
**Head SHA at reply time:** `<pr.head_sha_after_push>`
**Polling outcome:** <polling.copilot_status>

### Summary
- Items replied: <n>
- Threads resolved: <n>
- Resolve failures: <n>
- Recovery DEFER items: <n>
- Recovery ABANDON items: <n>

### Per-item status
- **@<author>** (`<kind>`, comment <id>): <classification> → reply posted [yes|no], resolved [yes|no|n/a]
```

**Skill B does NOT unlink the inventory** — `wait-for-pr-comments` (Skill A) owns the file's lifecycle. Skill A unlinks at its own Phase 8 success after Skill B reports success. Touching the file here would race Skill A's bookkeeping.

## Reply text templates

PR-public text. **No internal jargon** (`bd`, bead IDs, `ESCALATE`, `inventory`, `phase`, `crash_recovery`, `fix_outcome`) appears in any reply.

| State | Reply template |
|---|---|
| FIX, `fix_outcome=committed` | `Fixed in <fix_commit_sha>. <fix_summary>` |
| FIX, `fix_outcome=already_addressed` | `Already addressed in <fix_commit_sha>.` (the SHA is the existing commit the subagent identified) |
| FIX, duplicate of `<other>` | `Fixed via the change addressing <linked-comment-permalink>.` |
| SKIP | `<rationale>` (the rationale is user-facing, written for the reviewer) |
| ESCALATE + autonomous (`escalation_filed=true`) | `Captured for follow-up; will respond on a later push to this PR or in a related issue.` |
| ESCALATE + cap-exceeded (`rationale="exceeded re-review round cap"`) | `Round limit reached on this PR; deferring further iterations to a human reviewer.` |
| Recovery — DEFER (`--resume` user chose DEFER) | `Tracking in <public-tracking-link>.` (must be a public URL — GitHub issue, PR cross-reference, or public comment permalink. Bead IDs are forbidden.) |
| Recovery — ABANDON (`--resume` user chose ABANDON) | Use SKIP template with the user's rationale. |

## Schema validation guards

`validate-inventory.sh` (shipped with `wait-for-pr-comments`) enforces these nine guards. Skill B Phase 0 invokes the validator and aborts on any failure. The guards exist so Phase 2/3 can trust the inventory shape:

1. **Non-empty rationale** — reject if any item has `rationale == "" or null`. Rationale is user-facing for SKIP replies; an empty rationale would post an empty PR comment.
2. **`escalation_filed` only on ESCALATE** — reject if any item has `classification != "ESCALATE"` and `escalation_filed == true`.
3. **`review_summary` has no thread/comment IDs** — reject if any item has `kind == "review_summary"` and any of `thread_id`/`reply_to_comment_id`/`issue_comment_id` is non-null.
4. **Non-FIX items have null `fix_outcome`** — reject if any item has `classification != "FIX"` and `fix_outcome != null`.
5. **FIX items have a valid `fix_outcome`** — reject if any item has `classification == "FIX"` and `fix_outcome` is not one of `committed | already_addressed | failed`. (Skill A only writes the inventory after Phase 4 completes; every FIX item must have a non-null outcome.)
6. **`committed` outcome carries SHA + summary + gate variant** — reject if any item has `fix_outcome == "committed"` and any of `fix_commit_sha`/`fix_summary`/`fix_gate_variant` is null.
7. **`already_addressed` outcome carries SHA** — reject if any item has `fix_outcome == "already_addressed"` and `fix_commit_sha` is null.
8. **ESCALATE must be filed** — reject if any item has `classification == "ESCALATE"` and `escalation_filed != true`. Skill A's interactive Phase 3.5 reclassifies ESCALATEs to FIX/SKIP/DEFER before write; autonomous Phase 3.5 sets `escalation_filed=true`. An unfiled ESCALATE at write time means a Skill A bug — without this guard, Skill B would silently skip the item without a reply.
9. **Schema sanity** — reject if JSON parse fails or `schema_version != 1`.

On reject: validator logs the violating item to stderr; Skill B aborts with no replies posted.

## Concurrency recovery

When invoked via `--resume <path>`, Phase 1.5 fires. The inventory's `crash_recovery.last_completed_phase` value tells Phase 1.5 what state Skill A left the world in:

| `last_completed_phase` | What happened | Phase 1.5 behavior |
|---|---|---|
| `5a-verify-failed` | Combined verification gate failed in Skill A. Local commits exist but were never pushed. | Walk every FIX/`committed` item; their `fix_commit_sha`s are unlikely to be in `origin/<pr-branch>`. Most items will hit the ABANDON/DEFER/FIX-NOW prompt. Operator may have manually pushed since the crash — the `git merge-base --is-ancestor` probe is the source of truth, not the phase label. |
| `5b-commit-verify-failed` | Subagent reported a commit SHA that wasn't in `git rev-list <baseline>..HEAD`. Inventory contents are suspect for that item; others may be fine. | Same per-item probe. Items with valid SHAs in `origin/<pr-branch>` proceed. Bogus-SHA items hit the prompt. |
| `5c-push-failed` | Verification passed; combined push failed (auth, network, non-fast-forward). Local commits exist; remote does not have them. | Same per-item probe. If operator pushed manually after the crash, every item's SHA will now be an ancestor and Phase 1.5 emits no prompts. |
| `7-write-inventory` | Skill A completed end-to-end successfully but Skill B never ran (crash between Phase 7 write and Phase 8 invoke). | Should have come in via `--from-inventory`, not `--resume` — but if `--resume` is used here, the per-item probe will pass cleanly because the push succeeded; Phase 1.5 emits no prompts. |
| `8-skill-b-done` | Both skills already ran to completion. Inventory is an orphan that Skill A failed to unlink. | Phase 1.5 still runs the per-item probe; expects every SHA to be present. Operator should have invoked Skill A (which silently unlinks `8-skill-b-done` orphans), not Skill B. Phase 4 reports the situation; do nothing destructive. |

Phase 1.5's behavior is driven by the per-item `git merge-base --is-ancestor` probe, not by trusting the phase label. The label is a hint about what to expect, not a mandate.

## Red Flags

If you catch yourself doing any of these, STOP — you are deviating from the contract.

| Rationalization | Why it's wrong |
|---|---|
| "I'll write a richer reply explaining the fix in detail" | The reply matrix is pinned. Any phrasing not in the matrix risks leaking internal jargon or making promises the orchestrator can't keep. Use the templates verbatim. |
| "I'll resolve the SKIP threads since I replied with rationale" | SKIP replies are arguments to the reviewer, not closure. Resolving on their behalf erases their voice. **Never resolve SKIP or ESCALATE — only `kind=review_thread` AND `classification=FIX`.** |
| "I'll resolve the `review_summary` items too — they're closed in my mind" | `review_summary` and `issue_comment` have no resolve API; the GraphQL mutation errors. Resolve only `kind=review_thread`. |
| "I'll mention the bead ID so reviewers can track it" | **Never include `bd`, bead IDs (e.g., `agents-config-xyz`), `ESCALATE`, `inventory`, `phase`, or other internal tool names in PR replies.** The reply matrix templates above are the only sanctioned text. |
| "DEFER reply: I'll link the bead ID since it's public-ish" | **The DEFER recovery template links to public artifacts only — never to bead IDs.** GitHub issue / PR cross-reference / public comment permalink only. |
| "Standalone mode is fine for one-off invocations" | **Standalone invocation (no `--from-inventory` and no `--resume`) is fatal in v1.** Standalone mode is deferred to a follow-up bead. |
| "I'll unlink the inventory at Phase 4 to be tidy" | **Skill B does NOT unlink the inventory — Skill A owns the file's lifecycle.** Touching the file here races Skill A's bookkeeping. |
| "I'll add a `git commit` for the recovery DEFER tracking link" | Skill B does NO git mutations. The only allowed git is `git fetch` and `git merge-base --is-ancestor` in Phase 1.5. No `git commit`, `git push`, `git rebase`, `git merge`, `git reset`. |
| "I'll dispatch a subagent to address the missing-SHA item myself" | Skill B does NO fixing. Recovery triage routes to ABANDON / DEFER / FIX-NOW; FIX-NOW means the operator re-runs `wait-for-pr-comments`. |
| "I'll silently swallow recognized-but-malformed args (`--mode foo`)" | Recognized-but-malformed args are fatal startup errors. Silent fall-through hides operator typos. |
| "Head-SHA mismatch — I'll just retry forever" | Two retries with 5s sleep, then abort. Persistent mismatch means a concurrent push; the operator must reconcile and re-invoke with `--resume`. |
| "Schema validation failed but most items look fine — I'll post replies for those" | Validation failure aborts everything. No replies posted. The validator runs once, before Phase 1, for a reason. |

## Related Skills

- **`wait-for-pr-comments`** (Skill A) — runs FIRST. Polls Copilot, classifies (FIX/SKIP/ESCALATE), dispatches per-comment subagents, pushes combined commits, writes the inventory, then invokes this skill by default with `--from-inventory`. Owns the inventory file's full lifecycle (creation, partial-write on failure, unlink at Phase 8 success).
- **`verify-checklist`** — NOT used by this skill. The combined verification gate runs in `wait-for-pr-comments` Phase 5a before the inventory is written.
