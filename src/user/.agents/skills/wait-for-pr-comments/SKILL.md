---
name: wait-for-pr-comments
description: >
  Use after a PR is created or updated, OR when an open PR has Copilot/human
  review feedback to respond to. Polls Copilot via background script (zero
  Anthropic tokens during the wait), classifies each comment as
  FIX/SKIP/ESCALATE, addresses every FIX item via per-comment subagents
  (which either commit a new fix or recognize the concern as already-addressed
  by an earlier commit), pushes the combined commits, then by default invokes
  `reply-and-resolve-pr-threads` to reply to every thread and resolve the
  FIXED ones. Keywords: respond, address, fix, handle, triage, classify, PR,
  review, Copilot, feedback.
---

# wait-for-pr-comments

End-to-end PR-review responder. Polls Copilot via background bash (zero
Anthropic tokens during the wait), classifies every comment as
**FIX / SKIP / ESCALATE**, dispatches a per-comment subagent for every FIX
item, pushes the combined commits, and **by default** chains
`reply-and-resolve-pr-threads` to acknowledge every thread and resolve the
FIXED ones.

The only "skip the chain" path is a Phase 5x failure that aborts before
delivery — see Phase 8 for the contract.

## When to Use

Invoke when:

- A PR was just created or updated (the `detect-pr-push.sh` hook will
  suggest this skill — see Red Flags about hook text mid-formula).
- An open PR has Copilot or human review comments waiting for response.
- A formula's `await-review` step fires (autonomous mode — see arg protocol).

Do not use when:

- PR is a draft not ready for review.
- You need to monitor multiple PRs (one PR per invocation).
- CI/CD checks are the concern, not review comments.
- PR is already merged or closed.

---

## Skill A: arg protocol

Invoked via `Skill(skill: "wait-for-pr-comments", args: "<args-string>")`.

**Recognized grammar** (regex-style; all groups optional):

```
(<integer> | <pr-url>)?  (--bead-id <token>)?  (--mode autonomous|interactive)?
```

Plus tail tokens (operator narration) that are **warned-and-ignored**.

**Parsing rules:**

| Token shape | Behavior |
|---|---|
| Truly unknown token (e.g., `be careful about formatting`) | Warn-and-ignore. Continue. |
| Recognized-but-malformed (`--mode <unknown-value>`, `--bead-id` with no value or empty value) | **Fatal startup error.** No inventory write, no work begins. |
| `--mode autonomous` without `--bead-id` | **Fatal startup error.** Hard guard at Phase 1. |

Manual operator chat invocations omit `--mode` and `--bead-id` (interactive
default). Formulas pass `--mode autonomous --bead-id {{bead-id}}` explicitly.

---

## Skill A: phases

**8 phases total** (Phase 5 has three sub-phases). Each named phase is one
named action with one defined failure mode. Unless otherwise noted, any
unrecoverable failure invokes `write-inventory.sh partial <phase-id> <path>`,
reports to the caller, and aborts (Skill B is NOT invoked on Phase 5x
failure).

### Phase 1 — Detect PR + parse args + concurrency check

1. **Parse args** per the grammar above. Apply parsing rules.
2. **Hard guard:** if `--mode autonomous`, require non-empty `--bead-id`. On
   miss → fatal startup error (`'--mode autonomous requires --bead-id'`). No
   inventory write, no work begins.
3. **Determine PR + owner/repo** from (in order):
   - Explicit positional argument (PR number or URL).
   - Current branch via `gh pr view --json number,url` (extract owner/repo
     from URL).
   - Hook-injected context (`PR activity detected: #<n>`).
   - No PR found → report error and stop.
4. **Concurrency check**: probe for a pre-existing inventory file at
   `~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json`. The SHA
   in the path is **any** SHA on disk for this PR (the prior run's
   `head_sha_after_push`); list files matching
   `~/.claude/state/pr-inventory/<owner>-<repo>-<n>-*.json`.
   - If found, read `crash_recovery` and apply the **Concurrency recovery
     branch table** (below).
   - If none found, proceed.

### Phase 2 — Poll Copilot (background script)

Background bash — zero Anthropic tokens during the wait.

1. **Quick check** whether Copilot is already a requested reviewer:
   ```
   gh api repos/<owner>/<repo>/issues/<n>/events \
     --jq '[.[] | select(
       .event == "review_requested" and
       .requested_reviewer.login and
       (.requested_reviewer.login | test("copilot"; "i"))
     )] | length'
   ```
2. **Launch** `poll-copilot-review.sh` in the background. Pass
   `--skip-request-check` if step 1 returned > 0.
3. **Announce** to the user: "Copilot review monitoring is active for PR #N.
   You can keep working — I'll alert you when feedback arrives. Don't merge
   or clean up the worktree/branch yet."
4. **When the script completes**, read its stdout + check exit code:

   | Exit | Status | Action |
   |---|---|---|
   | 0 | `copilot_review_found` | Parse JSON → record `polling.copilot_status="review_found"` → Phase 3 |
   | 1 | `copilot_review_timeout` | Record `polling.copilot_status="timeout"` → still gather any human comments via `gh api .../pulls/<n>/comments` and `.../reviews`; if non-empty, classify them (Phase 3) and continue. If totally empty, jump to Phase 7 with empty `items` (Phase 8 still runs; Skill B replies to nothing and reports zeros). |
   | 2 | `copilot_not_requested` | Record `polling.copilot_status="not_requested"` → same fallback as exit 1. |
   | 3 | Error | Report stderr → abort. (No inventory written; nothing to recover.) |

While any background polling script is running and the user asks to merge,
delete the branch/worktree, or close the PR, **do NOT silently comply**.
Interject: "Copilot review monitoring is still active for PR #N. The review
could arrive any moment. Merging now means discarding that feedback. Still
want to proceed?"

### Phase 3 — Inventory + classify (FIX / SKIP / ESCALATE) + ESCALATE branch (Phase 3.5)

Build the inventory items array. Each item has both:

- **`classification`** — primary triage (FIX / SKIP / ESCALATE).
- **`kind`** — preserved verbatim from GitHub (`review_thread`,
  `review_summary`, `issue_comment`).

**Classification table:**

| Value | Meaning |
|---|---|
| **FIX** | Actionable, in-scope, addressable without unilaterally making architectural decisions. Dispatched to a per-comment subagent in Phase 4. |
| **SKIP** | Out of scope, agent disagrees with rationale (defensible counterargument), or FYI/praise. Always replied with rationale. Never resolved. |
| **ESCALATE** | Requires human judgment: architectural decision, unresolvable ambiguity, or genuine disagreement worth surfacing. Mode-aware (see below). |

**Triviality is NOT a classification.** It lives only inside per-comment
subagents as a scoped gate decision (full vs lite gate — see Per-comment
subagent contract).

**Already-addressed items are NOT a separate classification.** When a recent
commit (or the user pushing manually) already resolved the concern, mark the
item **FIX**. The Phase 4 subagent will read HEAD, recognize the fix is in
place, and return `fix_outcome="already_addressed"` with the existing commit
SHA. Skill B's reply template handles "Already addressed in `<sha>`" and
resolves the thread normally.

**Rationale enforcement**: each item's `rationale` MUST be non-empty before
the classification is finalized. If the agent emits an empty rationale,
**retry** the per-item classification with an explicit prompt. After Phase 3,
classifications are final for this round.

**Round counter**: increments on each entry to Phase 3. Initial pass = round
1. Each Phase 6 → Phase 3 reentry adds 1.

**Duplicate handling**: multiple comments sharing a root cause → mark every
duplicate **FIX**, set the same `fix_commit_sha` (set in Phase 4), and
populate `duplicate_of` on all but one. Skill B's reply template
cross-references the primary.

**Kind table** (preserved verbatim from GitHub):

| `kind` | Source | Reply endpoint (Skill B) | Resolvable? |
|---|---|---|---|
| `review_thread` | GraphQL `reviewThreads.nodes` | REST `POST /repos/<o>/<r>/pulls/<n>/comments/<id>/replies` (numeric `databaseId` from `reply_to_comment_id`) | Yes — GraphQL `resolveReviewThread`, only when `classification = FIX` |
| `review_summary` | GraphQL `reviews.nodes` | `gh pr comment` | No |
| `issue_comment` | REST `/issues/<n>/comments` | `gh pr comment` with cross-reference | No |

#### Phase 3.5 — ESCALATE branch (mode-aware)

If any item is classified ESCALATE, branch on mode (see **Mode-aware
ESCALATE** below). Interactive pauses for one batched prompt; autonomous
files via `bd label add <bead-id> human` + `bd update <bead-id>
--append-notes "<batch>"` and continues. After the branch returns,
re-merge any user reclassifications into the inventory before Phase 4.

### Phase 4 — Execute every FIX (per-comment subagents)

1. **Capture baseline SHA**: `<phase4_baseline_sha> = git rev-parse HEAD`.
   Stash in skill state for Phase 5b verification.
2. **Dispatch SERIALLY** — one subagent at a time. Parallelism is deferred
   to a follow-up bead (file-overlap prediction is unsolved in v1).
3. For each FIX item:
   - Capture `<pre_subagent_sha> = git rev-parse HEAD` BEFORE dispatch.
   - Pass `<pre_subagent_sha>` to the subagent as input context.
   - Subagent runs the **Per-comment subagent contract** (below).
   - **Audit the report** using **Orchestrator-side enforcement** (below).
     Any audit violation re-classifies the item to ESCALATE with rationale
     `"subagent contract violated: ..."`.

After all FIX items processed, the inventory carries each item's
`fix_outcome`, `fix_commit_sha`, `fix_summary`, and (for `committed`)
`fix_gate_variant`.

### Phase 5a — Combined verification gate

Run `verify-checklist` across all `committed`-outcome subagents' work.

**On failure:** build the inventory body (mirror the Phase 7 builder block —
the temp file may not exist yet at this point) and write it as `partial`:
```bash
jq -n \
  --argjson items "$ITEMS_JSON" \
  --argjson pr "$PR_JSON" \
  --argjson polling "$POLLING_JSON" \
  '{schema_version: 1, pr: $pr, polling: $polling, items: $items}' \
  > /tmp/pr-inventory-build-<n>.json

~/.claude/skills/wait-for-pr-comments/write-inventory.sh \
  partial 5a-verify-failed \
  ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
  < /tmp/pr-inventory-build-<n>.json

rm -f /tmp/pr-inventory-build-<n>.json
```
Report to caller; abort (Skill B is NOT invoked).

### Phase 5b — Verify subagent commits exist locally

Confirm each FIX/`committed` item's `fix_commit_sha` is in
`git rev-list <phase4_baseline_sha>..HEAD`.

**On mismatch:** build the inventory body (same `jq -n` block as Phase 5a)
and invoke:
```bash
~/.claude/skills/wait-for-pr-comments/write-inventory.sh \
  partial 5b-commit-verify-failed \
  ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
  < /tmp/pr-inventory-build-<n>.json

rm -f /tmp/pr-inventory-build-<n>.json
```
Report to caller; abort.

### Phase 5c — Push

Run `git push`.

**On failure:** keep local commits. Build the inventory body (same `jq -n`
block as Phase 5a) **with `pr.head_sha_after_push = head_sha_at_inventory`**
(no remote update happened), then:
```bash
~/.claude/skills/wait-for-pr-comments/write-inventory.sh \
  partial 5c-push-failed \
  ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
  < /tmp/pr-inventory-build-<n>.json

rm -f /tmp/pr-inventory-build-<n>.json
```
Report to caller with the instruction:

> "Push failed. Push manually then invoke
> `reply-and-resolve-pr-threads --resume <path>` (add `--mode autonomous
> --bead-id <id>` if applicable) to complete reply + resolve."

Abort.

### Phase 6 — Re-poll for Copilot re-review

Launch `poll-copilot-rereview-start.sh` (existing 30s background window).
If a new review arrives, return to **Phase 3 (round +1)**.

**Hard cap**: when round >= 3 AND Phase 6 detects a new review, do **one
final Phase 3 inventory pull** (no Phase 4). Classify the round-N+1 items
normally (FIX/SKIP/ESCALATE per the usual rules). Then mark **only** the
FIX-classified round-N+1 items as
`classification=ESCALATE, rationale="exceeded re-review round cap"`.
SKIP/praise items keep their natural classification and get normal SKIP
replies — this avoids posting the cap-exceeded template on harmless "LGTM"
acks.

If Phase 6 detects no new review (`no_rereview_started` exit), exit Phase 6
normally and proceed to Phase 7.

### Phase 7 — Write inventory

Build the JSON body via `jq` pipeline (NO heredoc — sandbox-blocked per
`git-commits.md`); write atomically via the helper:

```bash
jq -n \
  --argjson items "$ITEMS_JSON" \
  --argjson pr "$PR_JSON" \
  --argjson polling "$POLLING_JSON" \
  '{schema_version: 1, pr: $pr, polling: $polling, items: $items}' \
  > /tmp/pr-inventory-build-<n>.json

~/.claude/skills/wait-for-pr-comments/write-inventory.sh \
  complete 7-write-inventory \
  ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
  < /tmp/pr-inventory-build-<n>.json

rm -f /tmp/pr-inventory-build-<n>.json
```

The chain has not yet fired; if we crash here, recovery resumes from Phase
8 via `reply-and-resolve-pr-threads --from-inventory <path>`.

### Phase 8 — Invoke Skill B (default-on)

**Default-on. There is no item-count guard, no "all-clean" early exit.**
The only way to skip Phase 8 is a Phase 5x failure that already aborted.

Construct args:
- Always: `--from-inventory <path>`.
- If Skill A ran autonomous: append `--mode autonomous --bead-id <id>`.

Invoke:
```
Skill(skill: "reply-and-resolve-pr-threads", args: "--from-inventory <path> [--mode autonomous --bead-id <id>]")
```

**On Skill B success:** the inventory file already exists on disk from Phase 7.
Read it back as the helper's stdin (the helper writes via `mktemp` + `mv`, so
reading-from-and-writing-to the same path is safe — no in-place corruption):
```bash
~/.claude/skills/wait-for-pr-comments/write-inventory.sh \
  complete 8-skill-b-done \
  ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
  < ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json

rm -f ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json
```
Skill A is the file's lifecycle owner — Skill B never unlinks.

**On Skill B failure:** leave the inventory in place (last write was
`last_completed_phase="7-write-inventory"`). Report Skill B's error with the
instruction: "Invoke `reply-and-resolve-pr-threads --resume <path>`
manually (add `--mode autonomous --bead-id <id>` if applicable)."

---

## Per-comment subagent contract

Each FIX item is dispatched to a dedicated subagent. The subagent:

1. Reads the comment + surrounding code context.
2. Decides ONE of three outcomes:
   - **`committed`** — implements the fix, runs verification, commits.
   - **`already_addressed`** — reads HEAD, recognizes the comment's concern
     has already been resolved (e.g. by an earlier commit on this branch).
     Returns `fix_commit_sha=<existing-sha-that-addressed-it>` discovered
     per the procedure below. **No new commit.**
   - **`failed`** — cannot address; reports reason.

3. For `committed` outcome only:
   - **Verify FIRST, commit SECOND.** Subagent does not commit until its own
     verify passes.
   - Verification: full gate (`quality-reviewer` → `simplify` →
     `verify-checklist`) is **mandatory** unless lite-gate criteria met.
   - **Lite-gate eligibility self-check** — the subagent runs this BEFORE
     picking the gate variant. Conservative: any predicate uncertainty
     defaults to `full`.

     ```bash
     # Single-file check
     FILES=$(git diff --staged --name-only | wc -l); [ "$FILES" -eq 1 ] || GATE=full
     # Diff content check — any new control flow / imports / exports → full gate
     git diff --staged | grep -cE '^\+(import |from .* import |require\(|use |export |@import|if |for |while |switch |case |try |catch |throw |return [^;]+;)' \
       | { read N; [ "$N" -eq 0 ] || GATE=full; }
     GATE=${GATE:-lite}
     ```

     The subagent records its choice as `fix_gate_variant` (`full` or
     `lite`).
   - Commits with message `fix(<scope>): <summary> (PR #<n> comment
     <comment_id>)`. **Each subagent's commit stands alone — no squashing.**

4. **Reports back** with: `comment_id`, `fix_outcome`, `fix_summary`,
   `fix_commit_sha` (only for `committed` and `already_addressed`),
   `fix_gate_variant` (only for `committed`), and verification evidence
   (test command + output, only for `committed`).

### `already_addressed` SHA-discovery procedure

The subagent **MUST** follow this priority order. Do **NOT** default to HEAD.

1. **Diff search**: `git log --diff-filter=AM -p --follow -- <file>` —
   inspect commits whose diff against the comment's `original_line` removes
   or replaces the flagged code. If a commit's diff hunk visibly addresses
   the comment's stated concern, return that SHA. The subagent **MUST
   quote the matching diff hunk in `fix_summary`** for orchestrator audit.

2. **Blame fallback**: if (1) returns no candidate, run
   `git blame <file> -L <line>,<line>` ONLY IF the current `<file>:<line>`
   content visibly matches the comment's stated concern (i.e., the fix is in
   place). Return the blame's commit SHA.

3. **Failure**: if neither (1) nor (2) yields a defensible SHA, the comment
   is NOT already-addressed — return `failed` with reason `"could not
   locate the commit addressing this concern"`.

For comments without `path`/`line` metadata (`review_summary`, design-level
`issue_comment`): the SHA-discovery procedure cannot apply. Such items must
classify either `committed` (subagent makes a real fix) or `failed` —
`already_addressed` is unavailable.

### Orchestrator-side enforcement

The contract is unenforceable from prose alone, so the orchestrator audits
each report using the captured per-subagent baseline SHA.

After each subagent reports back, the orchestrator MUST:

- **Verify the report includes a non-empty `fix_outcome`.** Missing →
  re-classify item to ESCALATE with rationale
  `"subagent contract violated: no fix_outcome"`.

- **For `committed` outcome:**
  - Verify non-empty verification evidence. Missing → ESCALATE.
  - Verify EXACTLY ONE new commit since `<pre_subagent_sha>`:
    `git rev-list <pre_subagent_sha>..HEAD --count` returns `1`, and that
    commit's SHA equals the reported `fix_commit_sha`. Multiple or zero
    commits → ESCALATE with rationale `"subagent contract violated:
    expected exactly one commit"`.

- **For `already_addressed` outcome:**
  - Verify `fix_commit_sha` is reachable AND **predates**
    `<phase4_baseline_sha>` (it's an EARLIER commit, not a subagent-produced
    one):
    `git merge-base --is-ancestor <fix_commit_sha> <phase4_baseline_sha>`.
    Mismatch → ESCALATE.
  - Verify `fix_summary` quotes a diff hunk (string contains `+` or `-`
    markers) — minimal proof the subagent followed the discovery procedure
    rather than guessing. If the report is just prose, ESCALATE with
    `"subagent contract violated: already_addressed missing diff
    evidence"`.

- **For `failed` outcome:** re-classify item to ESCALATE with rationale
  `"subagent failed: <reason>"`.

### Non-compliant subagent recovery

If a stale broken commit was made by a non-compliant subagent (committed
without reporting `committed`, or committed multiple times):

```bash
git reset --soft <pre_subagent_sha>
git stash push --include-untracked --message "broken-subagent-<comment_id>"
```

`--soft` (not `--mixed`) preserves working tree AND staged index for
inspection and avoids cross-subagent contamination. The stash isolates the
contamination from the next serial subagent. Surface the stash ref in the
orchestrator's report.

**This is the ONLY `git reset` invocation in the spec. No `--hard`
anywhere.**

---

## Mode-aware ESCALATE

**Mode is determined by the explicit `--mode` arg. The arg is
authoritative.** Do not infer mode from invocation context.

| `--mode` value | Trigger source | Behavior on ESCALATE |
|---|---|---|
| `interactive` (default) | Operator in chat | Pause Phase 3.5; emit ONE batched prompt listing every ESCALATE item with rationale + a summary of FIX items as a sanity check. The user resolves each ESCALATE → `FIX-with-direction` / `SKIP-with-rationale` / `DEFER`, AND may re-classify any FIX → SKIP/ESCALATE. Reclassifications flow into the inventory before Phase 4. |
| `autonomous` | `run-queue`, formula step, scheduled trigger | Apply `bd label add <bead-id> human` (NOT `bd human <id>` — see Red Flags), then `bd update <bead-id> --append-notes "<batched-escalate-list>"` (`--append-notes` appends; `--notes` would REPLACE existing notes). Each item formatted as: `ESCALATE: <comment_id> (@<author>): <body_excerpt> — rationale: <rationale>`. Mark each ESCALATE item `escalation_filed=true` in the inventory. Continue to Phase 4 with FIX items only. |

**Hard guard at Phase 1**: `--mode autonomous` requires `--bead-id <id>`
(non-empty). Absence → fatal startup error
(`'--mode autonomous requires --bead-id'`); no inventory write, no work
begins.

### DEFER placement (interactive only)

Apply `beads.md` I3 sibling test:

- **Pass** (would have been on the parent epic's original plan) →
  `bd create --parent <parent-of-current-bead>`.
- **Fail or no parent** → orphan + `bd dep add <new-id> <bead-id>
  --type discovered-from`.

### Hook is interactive-default

`detect-pr-push.sh` emits a generic suggestion suitable for chat. The
formula's `await-review` step is the canonical autonomous entry point — it
passes `--mode autonomous --bead-id` directly. **See Red Flags about hook
text mid-formula.**

---

## Hand-off Contract: pinned JSON schema

Skill A writes (and Skill B reads) a JSON inventory at:

```
~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<head_sha_after_push>.json
```

Persistent location — **NOT `/tmp`** (tmpfs gets cleared on reboot).
Directory created on first write (`mkdir -p`). Path includes SHA so stale
files are obvious. Atomic write via `mktemp` + `mv` (same filesystem,
POSIX-atomic) — handled by `write-inventory.sh`.

### Schema (`schema_version: 1`)

```jsonc
{
  "schema_version": 1,
  "pr": {
    "owner": "...",
    "repo": "...",
    "number": 123,
    "head_sha_at_inventory": "abc123...",
    "head_sha_after_push": "def456..."     // == at_inventory if no fixes; updated to actual head after Phase 5c push success
  },
  "polling": {
    "copilot_status": "review_found" | "timeout" | "not_requested"  // consumed by Skill B Phase 4 final report only
  },
  "items": [
    {
      "kind": "review_thread" | "review_summary" | "issue_comment",
      "thread_id": "..." | null,
      "reply_to_comment_id": 12345 | null,
      "issue_comment_id": 67890 | null,
      "is_outdated": false,
      "author": "copilot" | "<github-login>",
      "body_excerpt": "first 200 chars of comment body",
      "classification": "FIX" | "SKIP" | "ESCALATE",
      "escalation_filed": false,             // ESCALATE only
      "rationale": "...",                    // required, non-empty
      "fix_outcome": "committed" | "already_addressed" | "failed" | null,  // FIX only; null until subagent reports
      "fix_commit_sha": "def456..." | null,  // FIX only; new commit (committed) or referenced existing commit (already_addressed)
      "fix_summary": "..." | null,           // FIX only
      "fix_gate_variant": "full" | "lite" | null,  // FIX/committed only
      "duplicate_of": "<thread_id|issue_comment_id>" | null
    }
  ],
  "crash_recovery": {
    "skill_a_completed": true,                // true once Phase 7 writes "complete" (and remains true through Phase 8); false only on Phase 5x partial-write
    "last_completed_phase": "8-skill-b-done"
  }
}
```

**Notes:**

- `review_summary` items have only `kind`, `body_excerpt`, `author`,
  `classification`, `rationale`, `fix_outcome`, `fix_commit_sha`,
  `fix_summary`, `fix_gate_variant`. **No** `thread_id`,
  `reply_to_comment_id`, `issue_comment_id` (validation guard 3 enforces
  this).
- `polling.copilot_review_submitted_at` is dropped from v1 — re-add as
  `schema_version: 2` when `agents-config-58m` lands a real consumer.
- `polling.copilot_status` is consumed by Skill B Phase 4 final report
  ("Polling outcome: <copilot_status>"); kept for that purpose.

### Helper-script invocation patterns

**Heredocs are sandbox-blocked** per `git-commits.md`. Use a temp file +
`jq` pipeline; pipe into the helper.

**Write inventory** (called from Phases 7 success, every 5x failure, and
Phase 8 success):

```bash
jq -n \
  --argjson items "$ITEMS_JSON" \
  --argjson pr "$PR_JSON" \
  --argjson polling "$POLLING_JSON" \
  '{schema_version: 1, pr: $pr, polling: $polling, items: $items}' \
  > /tmp/pr-inventory-build-<n>.json

~/.claude/skills/wait-for-pr-comments/write-inventory.sh \
  <state> <last_completed_phase> \
  ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
  < /tmp/pr-inventory-build-<n>.json

rm -f /tmp/pr-inventory-build-<n>.json
```

`<state>` is `complete` (Phase 7, Phase 8 success) or `partial` (Phase 5x
failures). `<last_completed_phase>` is one of `5a-verify-failed`,
`5b-commit-verify-failed`, `5c-push-failed`, `7-write-inventory`,
`8-skill-b-done`.

**Validate inventory** — Skill B Phase 0 invokes this; pinned here so the
agent has a copy-pasteable template:

```bash
~/.claude/skills/wait-for-pr-comments/validate-inventory.sh \
  ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
  || { echo "schema validation failed"; exit 1; }
```

Returns 0 if valid, non-zero with the violating item logged to stderr.

---

## Schema validation guards

`validate-inventory.sh` runs these nine guards (Skill B Phase 0 invokes it;
corrupt inventory → hard abort with no replies posted):

1. **Schema parse + version** — JSON parses and `schema_version == 1`.
2. **Rationale non-empty** — every item has a non-empty `rationale`
   (regardless of classification — SKIP rationale becomes the public reply,
   so empty rationale = empty PR comment).
3. **`escalation_filed` only on ESCALATE** — reject if any item has
   `classification != "ESCALATE"` and `escalation_filed == true`.
4. **`review_summary` IDs null** — reject if any item has
   `kind == "review_summary"` and any of `thread_id` /
   `reply_to_comment_id` / `issue_comment_id` is non-null.
5. **Non-FIX → null `fix_outcome`** — reject if any item has
   `classification != "FIX"` and `fix_outcome != null`.
6. **FIX → valid `fix_outcome`** — reject if any item has
   `classification == "FIX"` and `fix_outcome` is not one of
   `committed | already_addressed | failed` (Phase 7 writes only after
   Phase 4 completes — every FIX item must have a non-null outcome).
7. **`committed` requires all fields** — reject if any item has
   `fix_outcome == "committed"` and any of `fix_commit_sha` / `fix_summary`
   / `fix_gate_variant` is null.
8. **`already_addressed` requires SHA** — reject if any item has
   `fix_outcome == "already_addressed"` and `fix_commit_sha` is null.
9. **ESCALATE must be filed** — reject if any item has
   `classification == "ESCALATE"` and `escalation_filed != true`.
   Interactive Phase 3.5 reclassifies ESCALATEs to FIX/SKIP/DEFER before
   write; autonomous Phase 3.5 sets `escalation_filed=true`. An unfiled
   ESCALATE at write time means a Skill A bug — Skill B would otherwise
   silently skip it without a reply.

On reject: log violating item to stderr; abort with no replies posted.

---

## Concurrency recovery branch table

If Phase 1's concurrency check finds a pre-existing inventory file for this
PR, consult the inventory's `crash_recovery` block:

| `skill_a_completed` | `last_completed_phase` value | Action |
|---|---|---|
| `false` | `5a-verify-failed`, `5b-commit-verify-failed`, `5c-push-failed` | Refuse with **Message #1** (RESUME or DISCARD) |
| `true` | `7-write-inventory` | Refuse with **Message #2** (FROM-INVENTORY only) |
| `true` | `8-skill-b-done` | **Silent unlink** (orphan from prior crash); proceed normally |

**Message #1** (partial inventory; Skill A interrupted):

```
Refused to start: a partial inventory exists for PR #<n> from a prior interrupted run.
  File:           ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json
  Last phase:     <crash_recovery.last_completed_phase>
  Recovery:
    Option 1 — RESUME (preserves classifications, replies to what's complete):
      reply-and-resolve-pr-threads --resume <path>
      reply-and-resolve-pr-threads --resume <path> --mode autonomous --bead-id <bead-id>
    Option 2 — DISCARD (lose state, restart from scratch):
      rm <path> && <invoke this skill again>
```

**Message #2** (Skill A done; Skill B never ran):

```
Refused to start: an inventory exists for PR #<n> where Skill A completed but Skill B never ran.
  File:           ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json
  Recovery:
    reply-and-resolve-pr-threads --from-inventory <path>
    reply-and-resolve-pr-threads --from-inventory <path> --mode autonomous --bead-id <bead-id>
```

**Inventory cleanup timing:**

- At Skill A startup: housekeeping ONLY (delete files >30 days, handled
  inline by `write-inventory.sh`). Never touch the inventory currently
  being recovered.
- At Phase 8 success (after Skill B reports success): Skill A updates
  `last_completed_phase="8-skill-b-done"` then `unlink`s.
- Never at Phase 1 (the concurrency check refuses before any cleanup of the
  current PR's files).

---

## Reply text templates (referenced; Skill B owns posting)

Skill A's operator should know what's coming so the inventory carries
exactly the fields Skill B needs. **No internal jargon** (`bd`, bead IDs,
`ESCALATE`, `inventory`, `phase`, `crash_recovery`) appears in PR-public
replies.

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

---

## Hook auto-trigger

A PostToolUse hook script (`detect-pr-push.sh`) watches for:

- `gh pr create` with a PR URL in stdout.
- `git push` on a branch with an open PR.

When matched, it emits a generic chat-style suggestion. The hook
**suggests** invocation — it does not force it. User retains control.
Configuration lives in `settings.json.template` under `hooks.PostToolUse`.

---

## Red Flags

If you catch yourself doing any of these, STOP — you are deviating from the
process.

| Rationalization | Why it's wrong |
|---|---|
| "I'll skip the acknowledge step since I auto-fixed everything" | Phase 8 is **default-on**. There is no item-count guard. Even an all-fixed inventory must be handed to `reply-and-resolve-pr-threads` so threads get replied + resolved. The orphan-threads bug (lu3) was caused by exactly this rationalization. |
| "If you see the hook's `/wait-for-pr-comments` suggestion mid-formula, just paste it" | Use the formula's invocation (with `--mode autonomous --bead-id`), NOT the hook text. The hook is interactive-default; the formula's `await-review` step is the canonical autonomous entry point. |
| "I'll use `bd human <id>` to flag this" | **`bd human <id>` is a no-op help command.** It does not add the `human` label. Use `bd label add <id> human` followed by `bd update <id> --append-notes "..."`. |
| "I'll dispatch the FIX subagents in parallel — they look independent" | v1 is **serial only**. File-overlap prediction is unsolved; parallelism is deferred to a follow-up bead. |
| "The subagent's `already_addressed` report just says 'fixed earlier' — close enough" | Reject. The subagent MUST quote a diff hunk in `fix_summary` (audit guard). Re-classify to ESCALATE with `"subagent contract violated: already_addressed missing diff evidence"`. |
| "A subagent committed twice — I'll just keep both commits" | Audit guard violated (`expected exactly one commit`). Re-classify to ESCALATE; if commits are stale/broken, `git reset --soft <pre_subagent_sha>` + `git stash push --include-untracked` to isolate. **Never `git reset --hard`.** |
| "I'll let the agent write its own classification rationale, blank if needed" | Empty rationale is rejected by validation guard 1 (SKIP rationale becomes the public reply). Retry per-item classification with an explicit prompt until rationale is non-empty. |
| "Phase 5a verify failed but the fixes look fine — push anyway" | No. 5x failures abort the chain. Invoke `write-inventory.sh partial 5a-verify-failed <path>` and report. Skill B is NOT invoked on Phase 5x failure. |
| "I'll keep polling past the 30s re-review window" | Fixed window is fixed. Exit Phase 6 normally and proceed to Phase 7. |
| "I'll merge while the polling script is still running" | Don't. Issue the guard warning; the review could arrive any moment. |
| "I'll classify already-addressed items as their own bucket" | Already-addressed is NOT a classification. Classify FIX; the per-comment subagent returns `fix_outcome="already_addressed"` with the existing commit SHA. |
| "Round 4 of re-review is fine, Copilot's just being thorough" | Hard cap fires when round >= 3 AND a new review arrives. Mark FIX-classified round-N+1 items as `ESCALATE` with rationale `"exceeded re-review round cap"`. |
| "I'll inline `--mode autonomous` from the hook text" | The hook does not pass `--mode`. Autonomous mode is set ONLY by formulas (which also pass `--bead-id`). If you're invoking from chat, leave it interactive. |
| "Skill B failed but I'll unlink the inventory anyway" | No. On Skill B failure, leave the inventory in place. Skill A only unlinks after `write-inventory.sh complete 8-skill-b-done` succeeds. |
| "I'll keep the squashed commits clean — combine all subagent fixes into one" | Each subagent's commit stands alone. **No squashing.** Commit message format pinned: `fix(<scope>): <summary> (PR #<n> comment <comment_id>)`. |

---

## Related Skills

- **[`reply-and-resolve-pr-threads`](../reply-and-resolve-pr-threads/SKILL.md)**
  — Skill B. Reply to every PR review thread; resolve only the FIXED ones via
  GraphQL. Two modes: `--from-inventory` (invoked automatically at Phase 8)
  or `--resume` for crash recovery from a partial Skill A run. Does not fix
  code.
