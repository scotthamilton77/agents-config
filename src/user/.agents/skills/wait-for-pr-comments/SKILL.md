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
model: sonnet[1m]
effort: medium
---

<!--
Provenance pointer: pushback discipline for the per-comment subagent and
the orchestrator-side classifier lives in
`references/handling-feedback.md`. Amalgamated from
oss-snapshots/superpowers/receiving-code-review/SKILL.md at commit
f2cbfbe (v5.1.0). Tracked under bead agents-config-cx6.7.11.
-->

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

**9 phases total** (Phase 5 has three sub-phases). Each named phase is one
named action with one defined failure mode. Unless otherwise noted, any
unrecoverable failure invokes `write-inventory.sh --state partial --phase <phase-id> --output <path>`,
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
5. **Resolve the review policy** (Axis 1 decides whether and what to poll):
   ```bash
   POLICY_JSON=$(python3 "${CLAUDE_SKILL_DIR}/../merge-guard/resolve_policy.py" \
     --project-config "<repo-root>/project-config.toml" \
     --labels "<comma-separated bead labels, or empty>")
   ```
   (`--labels`: in `--mode autonomous`, `bd label list <bead-id> --json | jq -r 'join(",")'`;
   interactive without a bead → `""`.)
   - Resolver exit 1 → fatal startup error; report the resolver's stderr
     verbatim. A repo with an invalid review policy must not silently poll
     under a different one.
   - python3 (>= 3.11) or the resolver missing → proceed with the built-in
     default policy (bot expected / explicit merge) and say so — identical to
     this skill's historical behavior.
   - **`bot_review_expected == false` and `human_approvers_required == 0`**:
     nothing is expected — SKIP Phase 2 entirely (no polling) and proceed
     directly to Phase 3 to inventory any already-present feedback. Do NOT
     emit a human-handoff status: nothing human is expected; whether a merge
     may proceed is merge-guard's question, not this skill's.
   - **`bot_review_expected == false` but `human_approvers_required > 0`**:
     skip Copilot polling (Phase 2); inventory + triage existing feedback
     (Phases 3-8); at Phase 9, end with the terminal status
     "awaiting human review (<n> approval(s) required)" — parked, not
     blocking, not an error.
   - **`bot_review_expected == true`**: run Phase 2 as written. On
     `copilot_review_timeout`, the timeout ends the wait — it never counts as
     a review having happened (merge-guard's in-flight gate makes the same
     call independently at merge time).

### Phase 2 — Poll Copilot (background script)

Background bash — zero Anthropic tokens during the wait.

1. **Quick check** whether Copilot is already a requested reviewer (a
    Copilot-specific convenience glance to decide `--skip-request-check`; the
    launched script in step 3 does the authoritative policy-allowlist matching,
    so this substring probe need not generalize to non-Copilot bots). This
    glance is only relevant for request-based bots (Copilot) — comment-triggered
    bots (e.g. Codex) are never added as a requested reviewer, so the script
    itself auto-skips its requested-reviewer precondition when the resolved
    policy's `bot_reviewers` includes a comment-triggered identity; the caller
    need not special-case that here:
    ```
    gh api repos/<owner>/<repo>/issues/<n>/events \
      --jq '[.[] | select(
        .event == "review_requested" and
        .requested_reviewer.login and
        (.requested_reviewer.login | test("copilot"; "i"))
      )] | length'
    ```
2. **Capture** `<polling_since_timestamp> = $(date -u +%Y-%m-%dT%H:%M:%SZ)`.
    This timestamp anchors the stale-cache guard for re-review rounds.
3. **Launch** `poll-copilot-review.sh --owner "$OWNER" --repo "$REPO" --pr "$PR"
    --timeout-seconds <resolved_policy.bot_inactivity_timeout_seconds>
    --bot-reviewers "$(jq -c '.bot_reviewers' <<<"$POLICY_JSON")"` in the
    background (both values come from the policy resolved in Phase 1 step 5;
    timeout defaults to 1200 when the resolver's built-in default applies).
    Omitting `--timeout-seconds` silently falls back to the script's own 600s
    default, so always pass it explicitly. `--bot-reviewers` aligns polling to
    the exact bot identities the merge gate trusts, generalizing detection
    beyond Copilot; omit it only when running the script standalone, where it
    falls back to a Copilot-substring match.
    Pass `--skip-request-check` if step 1 returned > 0.
    In re-review context (round ≥ 2), also pass
    `--since-timestamp <polling_since_timestamp>` so the script rejects
    reviews that predate this run.
4. **Announce** to the user: "Copilot review monitoring is active for PR #N.
   You can keep working — I'll alert you when feedback arrives. Don't merge
   or clean up the worktree/branch yet."
5. **When the script completes**, read its stdout + check exit code:

   | Exit | Status | Action |
   |---|---|---|
   | 0 | `copilot_review_found` | Parse JSON → record `polling.copilot_status="review_found"` → Phase 3 |
    | 1 | `copilot_review_timeout` | Record `polling.copilot_status="timeout"` → still gather any human comments via `gh api .../pulls/<n>/comments` and `.../reviews`; if non-empty, classify them (Phase 3) and continue. If totally empty, jump to Phase 7 with empty `items` (Phase 8 still runs; Skill B replies to nothing and reports zeros; Phase 9 final check still runs). |
   | 2 | `copilot_not_requested` | Record `polling.copilot_status="not_requested"` → same fallback as exit 1. |
   | 3 | Error | Report stderr → abort. (No inventory written; nothing to recover.) |

While any background polling script is running and the user asks to merge,
delete the branch/worktree, or close the PR, **do NOT silently comply**.
Interject: "Copilot review monitoring is still active for PR #N. The review
could arrive any moment. Merging now means discarding that feedback. Still
want to proceed?"

### Phase 3 — Inventory + classify (FIX / SKIP / ESCALATE) + ESCALATE branch (Phase 3.5)

**Before classifying any item, load `references/handling-feedback.md`**
via the `Read` tool. The file sits next to this SKILL.md in the
installed skill directory (e.g. `~/.claude/skills/wait-for-pr-comments/references/handling-feedback.md`
in Claude installs; resolve the equivalent path for the active tool).
The seven patterns there — no performative agreement, restate, verify
against the codebase, push back with reasoning, ask before assuming,
YAGNI grep, blast-radius check — gate every FIX/SKIP/ESCALATE decision.
Classifications made without that discipline produce wrong-direction
fixes and empty SKIP rationales.

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
| `review_summary` | REST `/pulls/<n>/reviews`, unfiltered — bot or human | `gh pr comment` | No |
| `issue_comment` | REST `/issues/<n>/comments` | `gh pr comment` with cross-reference | No |

`review_summary` items are built by the orchestrator from a **fresh,
unfiltered fetch of every review on the PR** —
`gh api repos/<owner>/<repo>/pulls/<n>/reviews` — **not**
`poll-copilot-review.sh`'s `reviews[]` output, which is filtered to
Copilot's own bot reviews for polling purposes only and would silently drop
human review bodies from the inventory. One item per review with a
non-empty body, **bot or human**: set `review_id` from the review's numeric
`.id`, `author` from `.user.login`, `body_excerpt` from the first 200 chars
of `.body`. A human reviewer's summary flows through the same FIX/SKIP/ESCALATE
triage as Copilot's.

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
   - **Construct an explicit absolute report path** for the subagent:
     - In a beads workflow (step-bead ID available):
       `<repo-root>/.beads/worker-audit/<step-bead-id>/pr-comment-fixer-team.json`
     - Otherwise (standalone PR review, no beads context):
       `${TMPDIR:-/tmp}/pr-comment-fixer-<comment-id>.json` (temporary; not guaranteed to persist across system cleanup or reboots)
   - **Dispatch with an explicit `opus` model** (do NOT inherit orchestrator):
     ```
     Agent({
       subagent_type: "pr-comment-fixer-team",
       model: "opus",
       prompt: <task-spec>
     })
     ```
     The `<task-spec>` MUST pass: `comment_id`, `comment_thread_id`,
     comment `body`, the code-location (file + line(s) + any anchor
     metadata), the repo path, the absolute report path constructed
     above, and the **fully-expanded absolute path** to the
     pushback-discipline reference doc — `handling-feedback.md` next to
     this SKILL.md in the installed skill directory (e.g.
     `~/.claude/skills/wait-for-pr-comments/references/handling-feedback.md`).
     **Do NOT pass a literal `${CLAUDE_SKILL_DIR}/...` string** — the
     subagent has no shell context to expand it. The worker reads the
     reference doc FIRST, then classifies (FIX/SKIP/ESCALATE), takes
     action (committed/already_addressed/failed/escalated), and writes a
     `pr-comment-fix-report-v1` JSON report to the absolute report path.

     The orchestrator runs on `sonnet[1m]`; the FIX subagent MUST run on
     `opus` so fix correctness is not regressed by the orchestrator's lower
     tier. See Red Flags.
   - Subagent runs the **Per-comment subagent contract** (below).
   - **Audit the report** using **Orchestrator-side enforcement** (below).
     Any audit violation re-classifies the item to ESCALATE with rationale
     `"subagent contract violated: ..."`.

After all FIX items processed, the inventory carries each item's
`fix_outcome`, `fix_commit_sha`, `fix_summary`, and (for `committed`)
`fix_gate_variant`.

### Phase 5a — Combined verification gate

Run `verify-checklist` across all `committed`-outcome subagents' work.

**On failure:** build the inventory body and write it as `partial`:
```bash
${CLAUDE_SKILL_DIR}/build-inventory-body.sh \
  --items "$ITEMS_FILE" --pr "$PR_FILE" --polling "$POLLING_FILE" \
  > /tmp/pr-inventory-build-<n>.json

${CLAUDE_SKILL_DIR}/write-inventory.sh \
  --state partial \
  --phase 5a-verify-failed \
  --output ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
  < /tmp/pr-inventory-build-<n>.json

rm -f /tmp/pr-inventory-build-<n>.json
```
Report to caller; abort (Skill B is NOT invoked).

### Phase 5b — Verify subagent commits exist locally

Confirm each FIX/`committed` item's `fix_commit_sha` is in
`git rev-list <phase4_baseline_sha>..HEAD`.

**On mismatch:** build the inventory body (same `build-inventory-body.sh` invocation as Phase 5a)
and invoke:
```bash
${CLAUDE_SKILL_DIR}/write-inventory.sh \
  --state partial \
  --phase 5b-commit-verify-failed \
  --output ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
  < /tmp/pr-inventory-build-<n>.json

rm -f /tmp/pr-inventory-build-<n>.json
```
Report to caller; abort.

### Phase 5c — Push

Run `git push`.

**On success (agent-ruling repos only):** the pushed fix commits moved the PR
head, so the head-keyed merge-judge provenance sidecar no longer matches. If the
resolved policy is `rule-based`/`agent-ruling`, re-record provenance for the new
head — enumerating every `base..head` commit — so agent-ruling can still
authorize after this iteration. Best-effort and out of band: a failure here must
NOT block the chain; its absence simply forces a later `abstain` (fail-closed).
```bash
if [ "$(jq -r '.merge_rule' <<<"$POLICY_JSON")" = "agent-ruling" ]; then
  NEW_HEAD=$(git rev-parse HEAD)
  BASE_REF=$(gh pr view "$PR" --repo "$OWNER/$REPO" --json baseRefName --jq .baseRefName)
  # The base tip must be present locally to enumerate base..head (a minimal
  # checkout may lack origin/$BASE_REF). Only proceed on a SUCCESSFUL fetch — a
  # failed fetch would leave FETCH_HEAD stale/absent and enumerate the wrong
  # commit set. On fetch failure, skip the record (fail-closed: no sidecar → the
  # judge later abstains).
  if git fetch --quiet origin "$BASE_REF"; then
    # ONE --commit per commit in FETCH_HEAD(base)..$NEW_HEAD — the gate needs an
    # entry for EVERY commit, not just the tip. PRECONDITION: run this blanket
    # first-hand record ONLY when THIS session authored every base..head commit
    # (its own branch plus its own fix commits). Set SESSION_FAMILY to the
    # running agent's family. If the branch carries commits from another family
    # (merged-in work, a different model's commits), do NOT run this block —
    # first-hand-attesting a commit you did not author mis-attests it and can
    # defeat the cross-model guard. Correctly re-attesting a mixed-authorship
    # branch (derive each commit's family from its trailers, carry prior
    # attestations across the moved head) needs a dedicated helper (planned);
    # until then a mixed branch is left unrecorded and the judge abstains.
    SESSION_FAMILY=""  # REQUIRED — set to the running agent's own family, one of:
                       # anthropic openai google human. Left empty, the record
                       # below is skipped and the judge abstains (fail closed).
    COMMIT_ARGS=()
    while read -r sha; do
      COMMIT_ARGS+=(--commit "${sha}:${SESSION_FAMILY}:first-hand")
    done < <(git rev-list "FETCH_HEAD..${NEW_HEAD}")
    # Record only when the family is set AND commits were enumerated. An unset
    # family or an empty list skips the record (fail-closed: no sidecar → the
    # judge later abstains) rather than writing an invalid or empty attestation.
    if [ -n "$SESSION_FAMILY" ] && [ "${#COMMIT_ARGS[@]}" -gt 0 ]; then
      python3 "${HOME}/.claude/skills/merge-guard/record_provenance.py" \
        --owner "$OWNER" --repo "$REPO" --pr "$PR" --head-sha "$NEW_HEAD" \
        "${COMMIT_ARGS[@]}" \
        --recorded-by "wait-for-pr-comments" || true
    fi
  fi
fi
```

**On failure:** keep local commits. Build the inventory body (same `build-inventory-body.sh` invocation as Phase 5a) **with `pr.head_sha_after_push = head_sha_at_inventory`**
(no remote update happened), then:
```bash
${CLAUDE_SKILL_DIR}/write-inventory.sh \
  --state partial \
  --phase 5c-push-failed \
  --output ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
  < /tmp/pr-inventory-build-<n>.json

rm -f /tmp/pr-inventory-build-<n>.json
```
Report to caller with the instruction:

> "Push failed. Push manually then invoke
> `reply-and-resolve-pr-threads --resume <path>` (add `--mode autonomous
> --bead-id <id>` if applicable) to complete reply + resolve."

Abort.

### Phase 6 — Re-poll for Copilot re-review

**On entry**, seed the working silent-ask counter/exhausted flag from the
head-exact prior inventory (same head — a genuinely new fix commit gets a
fresh file and starts at 0; a merge-guard-driven re-invocation on an
unchanged head reuses this file and accumulates):
```bash
prior=$(jq -c '{c:(.polling.rereview_round_count // 0), e:(.polling.bot_review_cap_exhausted // false)}' \
  "$HOME/.claude/state/pr-inventory/<owner>-<repo>-<n>-<head_sha_after_push>.json" 2>/dev/null || echo '{"c":0,"e":false}')
```
`$prior` (`{c, e}`) is the baseline both hooks below pass as
`--prior-count`/`--prior-exhausted` to `compute-rereview-polling.sh`, and `e`
is the "before" value for each hook's false → true `PushNotification` check.
Neither hook passes `--silent-cap` — the silent re-request cap is locked at
the helper's default (1) per spec decision, not a per-repo config knob.

1. **Capture** `<rereview_since_timestamp> = $(date -u +%Y-%m-%dT%H:%M:%SZ)`
   **before** issuing the re-review request in step 2. The downstream `--after`
   (step 3) and `--since-timestamp` (step 4) filters require the bot signal to be
   strictly later than this value, so capturing it first bounds the prior round
   without excluding a fast Codex response that lands while `request-rereview.sh`
   is still returning (or in the same API-timestamp second). Capturing it after
   the dispatch would discard that valid `+1` or marker comment as stale and
   count the ask as a timeout.

2. **Trigger a fresh review cycle** (idempotency guard). Assemble the
   do-not-relitigate context from the current round's already-classified
   inventory items before dispatching — every FIX item contributes its
   `fix_commit_sha` as `detail`; every SKIP item contributes its `rationale`
   as `detail`, classified `REBUT` when the rationale is a substantive
   disagreement with the finding (the "agent disagrees with rationale,
   defensible counterargument" case from the classification table above) and
   `SKIP` otherwise (out of scope, FYI/praise) — this REBUT/SKIP split is a
   judgment call made when writing each item's `rationale`, not a separate
   inventory field:
   ```bash
   disposition_table=$(jq -c '[.items[] | select(.classification == "FIX" or .classification == "SKIP") |
     if .classification == "FIX"
     then {finding: .body_excerpt, classification: "FIX", detail: .fix_commit_sha}
     else {finding: .body_excerpt, classification: "SKIP", detail: .rationale}
     end]' "$HOME/.claude/state/pr-inventory/<owner>-<repo>-<n>-<head_sha_after_push>.json")
   # Re-tag any SKIP entries that are substantive rebuttals to "REBUT" by hand
   # (or via a review of each item's rationale) before dispatching, per the
   # split above.

   ${CLAUDE_SKILL_DIR}/request-rereview.sh \
     --owner "$OWNER" --repo "$REPO" --pr "$PR" \
     --bot-reviewers "$(jq -c '.bot_reviewers' <<<"$POLICY_JSON")" \
     --disposition-table "$disposition_table" \
     --since-sha "<phase4_baseline_sha>"
   # exit 0 when at least one ask succeeded; exit 1 when none did
   ```
   `--bot-reviewers` dispatches on each policy-trusted identity's own
   mechanism (the `remove-reviewer` + `add-reviewer` pair for Copilot, an
   `@codex review` issue comment for Codex) instead of always performing the
   Copilot-only dance — omitting it would leave a Codex-reviewed repo's
   re-review ask reaching nobody. (`--add-reviewer` alone is idempotent and
   silently does nothing, which is why the helper still pairs it with
   `--remove-reviewer` for Copilot.) `--disposition-table` and `--since-sha`
   are Codex-only do-not-relitigate context — they render into the `@codex
   review` comment as a structured markdown table plus a "focus on commits
   since `<sha>`" line, and are silently ignored by the Copilot mechanism.
   Confirmed across PR #317 and PR #331: a bare re-ask makes Codex re-cite
   settled findings every round, while a structured disposition table
   (including an explicit REBUT) produced zero re-raises.

3. **Launch** `poll-copilot-rereview-start.sh --owner "$OWNER" --repo "$REPO" --pr "$PR" --after <rereview_since_timestamp>` (80s max window:
   20s pre-sleep + 6 × 10s polls). This detects the `copilot_work_started`
   event that follows the fresh `review_requested`.

4. **If** `copilot_work_started` detected, launch `poll-copilot-review.sh
   --owner "$OWNER" --repo "$REPO" --pr "$PR"
   --skip-request-check --since-timestamp <rereview_since_timestamp>
   --bot-reviewers "$(jq -c '.bot_reviewers' <<<"$POLICY_JSON")"`
   to await the actual review. The `--since-timestamp` guard prevents the
   stale-cache bug where the script returns the prior round's review instead
   of the new one; `--bot-reviewers` keeps re-review detection aligned to the
   same policy allowlist used in Phase 2.

5. **If** a new review arrives, return to **Phase 3 (round +1)**.

**Hard cap**: when round >= 6 AND Phase 6 detects a new review, do **one
final Phase 3 inventory pull** (no Phase 4). Classify the round-N+1 items
normally (FIX/SKIP/ESCALATE per the usual rules). Then mark **only** the
FIX-classified round-N+1 items as
`classification=ESCALATE, rationale="exceeded re-review round cap"`.
SKIP/praise items keep their natural classification and get normal SKIP
replies — this avoids posting the cap-exceeded template on harmless "LGTM"
acks.

This chatty-bot cap also sets the persisted `bot_review_cap_exhausted` fact
(it reads the existing in-memory `round`; it does **not** touch
`rereview_round_count` — a review arrived, so this is not a silent ask):
```bash
result=$(${CLAUDE_SKILL_DIR}/compute-rereview-polling.sh \
  --prior-count "$(jq -r '.c' <<<"$prior")" \
  --prior-exhausted "$(jq -r '.e' <<<"$prior")" \
  --event chatty-cap)
jq -c --argjson r "$result" '. + $r' "$POLLING_FILE" > "${POLLING_FILE}.tmp" \
  && mv "${POLLING_FILE}.tmp" "$POLLING_FILE"
```
`$POLLING_FILE` stays a **path** throughout — read its current content, merge
`$result` in, write back to the same path (atomically, via temp + `mv`).
Never reassign `POLLING_FILE` itself to hold JSON text; every downstream call
(Phase 5a, Phase 7) passes it to `build-inventory-body.sh --polling`, which
requires a real file (`-f` check).

If this is the trigger that flips `bot_review_cap_exhausted` from `false`
(`$prior`'s `e`) to `true` (`$result`'s value), fire exactly one
`PushNotification` telling the human the retry window closed for this
PR/head — do not fire again on later invocations once it is already `true`.

If Phase 6 detects no new review (`no_rereview_started` exit), compute the
updated silent-ask counter and merge it into `POLLING_FILE` before exiting
Phase 6 normally and proceeding to Phase 7:
```bash
result=$(${CLAUDE_SKILL_DIR}/compute-rereview-polling.sh \
  --prior-count "$(jq -r '.c' <<<"$prior")" \
  --prior-exhausted "$(jq -r '.e' <<<"$prior")" \
  --event silent)
jq -c --argjson r "$result" '. + $r' "$POLLING_FILE" > "${POLLING_FILE}.tmp" \
  && mv "${POLLING_FILE}.tmp" "$POLLING_FILE"
```
Same path-preserving merge-and-write-back as the chatty-cap hook above — never
reassign `POLLING_FILE` to hold JSON text. Same false → true transition check: if this
silent exit is what flips `bot_review_cap_exhausted` from `false`
(`$prior`'s `e`) to `true` (`$result`'s value), fire exactly one
`PushNotification`. Both fields are persisted via the normal Phase 7 write
(`POLLING_FILE` flows into `build-inventory-body.sh --polling`).

### Phase 7 — Write inventory

Build the inventory body via helper and write atomically:

```bash
${CLAUDE_SKILL_DIR}/build-inventory-body.sh \
  --items "$ITEMS_FILE" --pr "$PR_FILE" --polling "$POLLING_FILE" \
  > /tmp/pr-inventory-build-<n>.json

${CLAUDE_SKILL_DIR}/write-inventory.sh \
  --state complete \
  --phase 7-write-inventory \
  --output ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
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
Write the intermediate completion marker so recovery knows Skill B ran:
```bash
${CLAUDE_SKILL_DIR}/write-inventory.sh \
  --state complete \
  --phase 8-skill-b-done \
  --output ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
  < ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json
```
Then proceed to Phase 9.

**On Skill B failure:** leave the inventory in place (last write was
`last_completed_phase="7-write-inventory"`). Report Skill B's error with the
instruction: "Invoke `reply-and-resolve-pr-threads --resume <path>`
manually (add `--mode autonomous --bead-id <id>` if applicable)."

---

### Phase 9 — Final unresolved-threads verification

After Skill B completes, verify no review threads were missed before
considering the await-review step done.

**Why filter against the inventory.** SKIP and ESCALATE threads are
intentionally never resolved (SKIP replies argue the reviewer's point;
ESCALATE awaits human judgment). Without filtering, any SKIP/ESCALATE
thread keeps the unresolved count > 0 forever and Phase 9 re-loops
infinitely (3→4→5→6→7→8→9→3→…). The round cap does not save this path
because the cap fires only when Phase 6 detects a new review, which it
won't on a pure re-classification loop.

1. **Query** for all unresolved, non-outdated review threads (pagination handled internally):
   ```bash
   ${CLAUDE_SKILL_DIR}/count-unresolved-threads.sh \
     --owner "$OWNER" --repo "$REPO" --pr "$PR"
   # stdout: {count: N, thread_ids: ["<graphql-thread-id>", ...]}
   ```
2. **Filter** the result against the inventory to exclude threads the
   current round classified SKIP or ESCALATE (intentionally unresolved).
   Only genuinely actionable threads remain — unresolved FIX items whose
   resolution didn't take, or threads not in the inventory at all (new
   comments posted after Skill A's Phase 3 fetch):
   ```bash
   ${CLAUDE_SKILL_DIR}/count-unresolved-threads.sh \
     --owner "$OWNER" --repo "$REPO" --pr "$PR" \
   | ${CLAUDE_SKILL_DIR}/filter-actionable-threads.sh \
     --inventory "$INVENTORY_PATH"
   # stdout: {count: N, thread_ids: [...]} — SKIP/ESCALATE excluded
   ```
3. **If count > 0**: treat as a new review round. Return to **Phase 3
   (round +1)**. Phase 3 must **re-fetch full thread details** (the Phase 9
   query's `comments` preview is for triage only; the canonical source for
   inventory construction remains the same Phase 3 fetch paths used in round 1).
4. **If count == 0**: write final completion state and RETAIN the file:
   ```bash
   ${CLAUDE_SKILL_DIR}/write-inventory.sh \
     --state complete \
     --phase 9-final-check-done \
     --output ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
     < ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json
   ```
   Do NOT delete the inventory. Completed inventories are the durable triage
   record the merge-eligibility floor's untriaged-non-thread-feedback check
   unions across pushes (`check-merge-eligibility.sh` globs
   `<owner>-<repo>-<n>-*.json`) — possibly in a later session. The >30-day
   pruning in `write-inventory.sh` is the only deletion. Skill A remains the
   file's lifecycle owner — Skill B never unlinks.
5. **Terminal status:** if the resolved policy has `human_approvers_required > 0`
   and that many distinct current approvals have not arrived, report
   "awaiting human review (<n> required)" as the terminal status. Otherwise
   report the normal completion summary. Never report a human-handoff status
   when nothing human is expected.

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
   (test command + output, only for `committed`). See **Subagent report
   schema** below for the authoritative contract; the orchestrator validates
   every report via `audit-subagent-report.sh`.

### Subagent report schema

The per-comment fix subagent returns a JSON report. The orchestrator validates
every report via `audit-subagent-report.sh` (exit 2 on schema violation, exit
1 on audit violation). This is the **authoritative contract**:

```yaml
fields:
  comment_id:      string  (required)
  fix_outcome:     enum    (required) [committed | already_addressed | failed | deferred | escalated | abandoned]
  fix_summary:     string  (required)
  fix_commit_sha:  string  (required when fix_outcome in {committed, already_addressed})
  fix_gate_variant: enum   (required when fix_outcome == committed) [lite | full]
  verification_evidence:
    test_command:  string  (required when fix_outcome == committed)
    output:        string  (required when fix_outcome == committed)
```

Schema mismatches → `audit-subagent-report.sh` exits 2 with
`{field, message}` on stdout. Audit mismatches (SHA missing in worktree, SHA
not an ancestor of the post-fix HEAD) → exit 1 with `{violation, rationale}`.

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
| `autonomous` | `run-queue`, formula step, scheduled trigger | Apply `bd label add <bead-id> human` (NOT `bd human <id>` — see Red Flags), then `bd update <bead-id> --append-notes "<batched-escalate-list>"` (see beads rules §Notes vs Comments). Each item formatted as: `ESCALATE: <comment_id> (@<author>): <body_excerpt> — rationale: <rationale>`. Mark each ESCALATE item `escalation_filed=true` in the inventory. Continue to Phase 4 with FIX items only. |

**Hard guard at Phase 1**: `--mode autonomous` requires `--bead-id <id>`
(non-empty). Absence → fatal startup error
(`'--mode autonomous requires --bead-id'`); no inventory write, no work
begins.

### DEFER placement (interactive only)

Use the `triaging-discovered-work` skill before filing or deferring the item. Do not
duplicate or bypass that contract here.

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
    "copilot_status": "review_found" | "timeout" | "not_requested",  // consumed by Skill B Phase 4 final report only
    "rereview_round_count": 0,           // silent-ask count on current head, default 0
    "bot_review_cap_exhausted": false    // default false
  },
  "items": [
    {
      "kind": "review_thread" | "review_summary" | "issue_comment",
      "thread_id": "..." | null,
      "reply_to_comment_id": 12345 | null,
      "issue_comment_id": 67890 | null,
      "review_id": 301 | null,                 // review_summary only: REST review .id — its stable cross-inventory identity
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
      "duplicate_of": "<thread_id|issue_comment_id>" | null,
      "posted_reply_id": 777001 | null       // written by Skill B's post-replies.sh at post time; read by check-merge-eligibility.sh to exclude the agent's own replies from the untriaged-feedback check
    }
  ],
  "crash_recovery": {
    "skill_a_completed": true,                // true once Phase 7 writes "complete" (and remains true through Phase 9); false only on Phase 5x partial-write
    "last_completed_phase": "9-final-check-done"
  }
}
```

**Notes:**

- `review_summary` items have `kind`, `review_id`, `body_excerpt`, `author`,
  `classification`, `rationale`, `fix_outcome`, `fix_commit_sha`,
  `fix_summary`, `fix_gate_variant`. `review_id` is **required** — it is the
  REST review's numeric `.id`, the item's stable identity for the
  cross-push triage union in `check-merge-eligibility.sh`. **No**
  `thread_id`, `reply_to_comment_id`, `issue_comment_id` (validation guard 3
  enforces both).
- `polling.copilot_review_submitted_at` is dropped from v1 — re-add as
  `schema_version: 2` when `agents-config-58m` lands a real consumer.
- `polling.rereview_round_count` / `polling.bot_review_cap_exhausted` are
  additive at v1 (actively consumed by `check-merge-eligibility.sh`); when
  `agents-config-58m` bumps to `schema_version: 2`, they fold into the v2
  doc alongside `copilot_review_submitted_at`.
- `polling.copilot_status` is consumed by Skill B Phase 4 final report
  ("Polling outcome: <copilot_status>"); kept for that purpose.

### Helper-script invocation patterns

**Heredocs are sandbox-blocked** per `claude-sandbox.md`. Use a temp file +
`jq` pipeline; pipe into the helper.

**Write inventory** (called from Phases 7 success, every 5x failure, and
Phase 8 success):

```bash
${CLAUDE_SKILL_DIR}/build-inventory-body.sh \
  --items "$ITEMS_FILE" --pr "$PR_FILE" --polling "$POLLING_FILE" \
  > /tmp/pr-inventory-build-<n>.json

${CLAUDE_SKILL_DIR}/write-inventory.sh \
  --state <state> \
  --phase <last_completed_phase> \
  --output ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
  < /tmp/pr-inventory-build-<n>.json

rm -f /tmp/pr-inventory-build-<n>.json
```

`<state>` is `complete` (Phase 7 or Phase 9 success) or `partial` (Phase 5x
failures). `<last_completed_phase>` is one of `5a-verify-failed`,
`5b-commit-verify-failed`, `5c-push-failed`, `7-write-inventory`,
`8-skill-b-done`, `9-final-check-done`.

**Detect PR context** (Phase 1):

```bash
${CLAUDE_SKILL_DIR}/detect-pr-context.sh [--pr <n-or-url>]
# stdout: {pr_number, owner, repo, inventory_path, concurrency_state}
```

**Fetch + normalize comments** (Phase 3 inventory build):

```bash
${CLAUDE_SKILL_DIR}/fetch-and-normalize-comments.sh \
  --owner "$OWNER" --repo "$REPO" --pr "$PR"
# stdout: JSON array of normalized items (kind, thread_id, body_full, ...)
```

**Audit a per-comment subagent's report** (Phase 4, after each FIX subagent):

```bash
${CLAUDE_SKILL_DIR}/audit-subagent-report.sh \
  --pre-sha "$PRE_SHA" \
  --baseline-sha "$BASELINE_SHA" \
  --report "$REPORT_FILE" \
  --worktree-root "$WT_ROOT"
# NOTE: --report takes a FILE PATH containing the subagent's JSON report,
# not inline JSON. ($REPORT_FILE is a path on disk.)
# exit 0 = pass; exit 1 = audit violation {violation,rationale};
# exit 2 = schema violation {field,message}
```

**Build inventory body** (Phases 5a / 5b / 5c / 7 / 8):

```bash
${CLAUDE_SKILL_DIR}/build-inventory-body.sh \
  --items "$ITEMS_FILE" \
  --pr "$PR_FILE" \
  --polling "$POLLING_FILE" \
  > /tmp/pr-inventory-build-<n>.json
```

**Request a bot re-review** (Phase 6 — per-bot dispatch on the policy's
`bot_reviewers` allowlist, not just the legacy Copilot remove+add pair):

```bash
${CLAUDE_SKILL_DIR}/request-rereview.sh \
  --owner "$OWNER" --repo "$REPO" --pr "$PR" \
  --bot-reviewers "$(jq -c '.bot_reviewers' <<<"$POLICY_JSON")"
```

**Count unresolved threads** (Phase 9 — replaces the inline GraphQL block):

```bash
${CLAUDE_SKILL_DIR}/count-unresolved-threads.sh \
  --owner "$OWNER" --repo "$REPO" --pr "$PR"
# stdout: {count: <n>, thread_ids: [...]}
```

**Filter actionable threads** (Phase 9 — excludes SKIP/ESCALATE from the
re-loop trigger):

```bash
${CLAUDE_SKILL_DIR}/count-unresolved-threads.sh \
  --owner "$OWNER" --repo "$REPO" --pr "$PR" \
| ${CLAUDE_SKILL_DIR}/filter-actionable-threads.sh \
  --inventory "$INVENTORY_PATH"
# stdout: {count: <n>, thread_ids: [...]} — SKIP/ESCALATE excluded
```

**Validate inventory** — Skill B invokes this twice (Phase 0 with `--phase 0`
pre-render; Phase 2 with the default `--phase 2` post-render). Skill A does not
call it. Pinned here so the agent has a copy-pasteable template:

```bash
${CLAUDE_SKILL_DIR}/validate-inventory.sh \
  --inventory ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
  || { echo "schema validation failed"; exit 1; }
```

Returns 0 if valid, non-zero with the violating item logged to stderr.

---

## Schema validation guards

`validate-inventory.sh` runs these ten guards, numbered to match the
`# Guard N:` comments in the script. Skill B invokes it twice — `--phase 0`
before `render-reply-bodies.sh` runs (guards 0–8), then the default `--phase 2`
after render (all ten, adding guard 10). The numbering skips 9 — an earlier
schema-sanity guard now absorbed into guard 0. Corrupt inventory → hard abort
with no replies posted:

- **Guard 0 — schema parse + version** — JSON parses and `schema_version == 1`.
- **Guard 1 — rationale non-empty** — every item has a non-empty `rationale`
  (regardless of classification — SKIP rationale becomes the public reply,
  so empty rationale = empty PR comment).
- **Guard 2 — `escalation_filed` only on ESCALATE** — reject if any item has
  `classification != "ESCALATE"` and `escalation_filed == true`.
- **Guard 3 — `review_summary` IDs** — reject if any item has
  `kind == "review_summary"` and either any of `thread_id` /
  `reply_to_comment_id` / `issue_comment_id` is non-null, or `review_id`
  is null.
- **Guard 4 — non-FIX → null `fix_outcome`** — reject if any item has
  `classification != "FIX"` and `fix_outcome != null`.
- **Guard 5 — FIX → valid `fix_outcome`** — reject if any item has
  `classification == "FIX"` and `fix_outcome` is not one of
  `committed | already_addressed | failed` (Phase 7 writes only after
  Phase 4 completes — every FIX item must have a non-null outcome).
- **Guard 6 — `committed` requires all fields** — reject if any item has
  `fix_outcome == "committed"` and any of `fix_commit_sha` / `fix_summary`
  / `fix_gate_variant` is null.
- **Guard 7 — `already_addressed` requires SHA** — reject if any item has
  `fix_outcome == "already_addressed"` and `fix_commit_sha` is null.
- **Guard 8 — ESCALATE must be filed** — reject if any item has
  `classification == "ESCALATE"` and `escalation_filed != true`.
  Interactive Phase 3.5 reclassifies ESCALATEs to FIX/SKIP/DEFER before
  write; autonomous Phase 3.5 sets `escalation_filed=true`. An unfiled
  ESCALATE at write time means a Skill A bug — Skill B would otherwise
  silently skip it without a reply.
- **Guard 10 — replyable has `reply_body`** (`--phase 2` only) — reject if any
  FIX, SKIP, or filed-ESCALATE item has a null/empty `reply_body`. This guard
  runs only after `render-reply-bodies.sh` (Skill B's helper, in
  `reply-and-resolve-pr-threads/`) populates the field, so `--phase 0`
  (pre-render, on the raw inventory) skips it. **Skill A never populates
  `reply_body` — rendering is Skill B's job.** If the render helper looks
  "missing" from `wait-for-pr-comments/`, it isn't broken; it lives in Skill
  B's directory. Stop and check the boundary before working around it.

On reject: log violating item to stderr; abort with no replies posted.

---

## Concurrency recovery branch table

If Phase 1's concurrency check finds a pre-existing inventory file for this
PR, consult the inventory's `crash_recovery` block:

| `skill_a_completed` | `last_completed_phase` value | Action |
|---|---|---|
| `false` | `5a-verify-failed`, `5b-commit-verify-failed`, `5c-push-failed` | Refuse with **Message #1** (RESUME or DISCARD) |
| `true` | `7-write-inventory` | Refuse with **Message #2** (FROM-INVENTORY only) |
| `true` | `8-skill-b-done`, `9-final-check-done` | **Retained triage record** (completed run) — do NOT unlink; proceed normally. The eligibility floor reads these files. |

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
- At Phase 9 success (after final unresolved-threads check passes): Skill A
  updates `last_completed_phase="9-final-check-done"` and **retains the
  file** — completed inventories are the durable triage record consumed by
  `check-merge-eligibility.sh`'s non-thread-feedback check, unioned across
  the PR's full push history.
- Never at Phase 1 (the concurrency check refuses before any cleanup of the
  current PR's files; completed files found there are retained records, not
  orphans).
- The only deletion anywhere is the >30-day pruning.

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
| "Phase 5a verify failed but the fixes look fine — push anyway" | No. 5x failures abort the chain. Invoke `write-inventory.sh --state partial --phase 5a-verify-failed --output <path>` and report. Skill B is NOT invoked on Phase 5x failure. |
| "I'll keep polling past the re-review window" | Phase 6 uses a fixed 80s max window (20s pre-sleep + 6 × 10s polls). Do not extend ad-hoc. If Copilot has not started by then, exit Phase 6 normally and proceed to Phase 7. |
| "I'll merge while the polling script is still running" | Don't. Issue the guard warning; the review could arrive any moment. |
| "I'll classify already-addressed items as their own bucket" | Already-addressed is NOT a classification. Classify FIX; the per-comment subagent returns `fix_outcome="already_addressed"` with the existing commit SHA. |
| "Round 7 of re-review is fine, Copilot's just being thorough" | Hard cap fires when round >= 6 AND a new review arrives. Mark FIX-classified round-N+1 items as `ESCALATE` with rationale `"exceeded re-review round cap"`. |
| "I'll inline `--mode autonomous` from the hook text" | The hook does not pass `--mode`. Autonomous mode is set ONLY by formulas (which also pass `--bead-id`). If you're invoking from chat, leave it interactive. |
| "Skill B failed but I'll unlink the inventory anyway" | No. Never unlink the inventory — on Skill B failure OR success. Completed inventories are the durable triage record the merge-eligibility floor unions across pushes; the >30-day pruning in `write-inventory.sh` is the only deletion. |
| "I'll keep the squashed commits clean — combine all subagent fixes into one" | Each subagent's commit stands alone. **No squashing.** Commit message format pinned: `fix(<scope>): <summary> (PR #<n> comment <comment_id>)`. |
| "I'll let the per-comment fix subagent inherit the orchestrator's model" | Wrong. The orchestrator runs `sonnet[1m]` (this skill's frontmatter). Inheriting means the fix subagent ALSO runs on `sonnet[1m]`, which regresses fix correctness — `wait-for-pr-comments` is the cheap triage tier; **fix work needs `opus`**. The Phase 4 `Agent({...})` dispatch MUST set `model: "opus"` explicitly. |

---

## Related Skills

- **[`reply-and-resolve-pr-threads`](../reply-and-resolve-pr-threads/SKILL.md)**
  — Skill B. Reply to every PR review thread; resolve only the FIXED ones via
  GraphQL. Two modes: `--from-inventory` (invoked automatically at Phase 8)
  or `--resume` for crash recovery from a partial Skill A run. Does not fix
  code.
