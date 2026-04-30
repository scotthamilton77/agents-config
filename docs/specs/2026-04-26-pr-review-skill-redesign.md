# bl3: Revisit wait-for-pr-comments / resolve-pr-comments against beads workflow

**Bead:** `agents-config-bl3` (P1, feature)
**Deliverable type:** spec / design decision
**Status:** spec landed 2026-04-26 — implementation tracked in follow-up bead.

## Naming decision (taken 2026-04-26)

| Skill | Name | Decision |
|---|---|---|
| Skill A | `wait-for-pr-comments` | **KEEP CURRENT NAME.** Aggressive frontmatter rewrite handles Pain Point #2 discoverability for Skill A's expanded scope. Decision rationale: cost-vs-clarity tradeoff favors keeping the name operators already learned (file churn cost is real; new keyword-rich frontmatter covers discoverability). |
| Skill B | `resolve-pr-comments` → **`reply-and-resolve-pr-threads`** | **RENAMED.** Original name's keyword gap was Pain Point #2's primary instance; new name surfaces both verbs ("reply", "resolve"). |

The spec text below sometimes references `respond-to-pr-feedback` as a hypothetical Skill A rename — read those as `wait-for-pr-comments` (the kept name). All references to `reply-and-resolve-pr-threads` are correct.

---

## Glossary

- **formula** — TOML template under `.beads/formulas/` defining a workflow's step DAG.
- **molecule** — runtime instance of a formula (created by `bd mol pour` or `bd mol wisp`).
- **completion gate** — the `quality-reviewer` → `code-simplifier` → `verify-checklist` chain mandated by `completion-gate.md` for non-trivial subagent work.
- **FIX / SKIP / ESCALATE** — three-way classification for each PR comment (defined below).
- **`fix_outcome`** — per-FIX-item subagent return value: `committed` (new commit produced) | `already_addressed` (concern resolved by an earlier commit; no new work) | `failed` (subagent couldn't address).
- **`bd label add <id> human`** — the canonical project mechanism for flagging a bead for human attention. (NOT `bd human <id>` — `bd human` with no subcommand is the help command. The codebase folklore using `bd human <id>` as shorthand for "label and notify" is incorrect at the CLI level.)
- **Pain Point #N** — see §"Context" below.
- **Option C** — the bead notes' "consolidate both skills into a formula/molecule"; deferred in this spec.
- **AUTOMATIC list** — the action category in `delivery.md` that fires without operator authorization.
- **I3 sibling test** — `beads.md` rule: discovered work goes IN the parent epic if it would have been on the original plan; otherwise as orphan + `discovered-from` dep.

**Cross-referenced beads:** `bl3` (this bead), `lu3` (PR #11 orphaned-threads bug), `agents-config-58m` (poll-copilot stale-review bug), `agents-config-zt1` (Copilot re-request idempotency), `agents-config-bf6` (externalize long bead specs).

---

## Context

Two standalone Claude skills currently share PR-review responsibility, but the boundary is broken:

- **`wait-for-pr-comments`** owns ARRIVAL: polls Copilot via background bash (zero Anthropic tokens during the wait), then triages comments into a *three-bucket gradient* — Mechanical / Non-trivial / Ambiguous — auto-fixes Mechanical inline, hands off the rest. Hand-off only fires when something falls into Non-trivial or Ambiguous.
- **`resolve-pr-comments`** owns CLOSING: per-comment subagent dispatch for non-trivial fixes, reply to every thread, resolve only FIXED `review_thread` items via GraphQL.

**The bug** (lu3 PR #11): when everything in a Copilot review fits the Mechanical bucket, `wait-for-pr-comments` fixes inline, commits, pushes, exits — and `resolve-pr-comments` never runs. Threads sit unreplied and unresolved indefinitely.

**Pain Points** documented in the bead notes:
1. **#1** — Hand-off trigger too narrow (root of the bug above).
2. **#2** — Frontmatter keyword gaps — "reply", "resolve", "thread", "post fix confirmation" don't surface `resolve-pr-comments`.
3. **#3** — Overlapping responsibilities — both skills know how to fix; neither cleanly owns the closing-out housekeeping.
4. **#4** (Scott) — The implicit Mechanical / Non-trivial / Ambiguous gradient is the wrong primary classification.

---

## Bead question coverage

| Bead question | Answer |
|---|---|
| Should PR review response become a formula/molecule? | **Not now** (Option C deferred). |
| Skill-pair rethink — A (detector-only), B (lifecycle phase split), C (formula)? | **B** with kind-aware classification, default-on chain. Skill B has two modes: from-Skill-A and `--resume` (crash recovery). Standalone mode deferred to a follow-up bead. |
| Frontmatter rewrites with keyword coverage? | Yes — both skills get pinned frontmatter. |
| Clearly-named hand-off trigger? | Skill A's final phase is default-on invocation of Skill B; skip only on Phase 5x failure. |
| Explicit description of who owns Phase 5 reply + resolve? | Skill B owns it exclusively. |
| Per-comment step ledger? | Partial — Hand-off Contract file is a transient ledger; persistent ledger remains part of Option C (deferred). |

---

## Design

### Classification: three-way (FIX / SKIP / ESCALATE), kind-aware

Skill A classifies every comment with two orthogonal fields: a primary `classification` and a preserved `kind` from GitHub.

**`classification`** (per item, with required non-empty `rationale`):

| Value | Meaning |
|---|---|
| **FIX** | Actionable, in-scope, addressable without unilaterally making architectural decisions. The skill addresses it via a per-comment subagent. |
| **SKIP** | Out of scope, agent disagrees with rationale (defensible counterargument), or FYI/praise. Always replied with rationale. Never resolved. |
| **ESCALATE** | Requires human judgment: architectural decision, unresolvable ambiguity, or genuine disagreement worth surfacing. Mode-aware (see below). |

There is no "trivial" classification surfaced to the user. Triviality lives only inside per-comment subagents as a scoped gate decision.

**Already-addressed items are NOT a separate classification**: when the user (or a recent commit) already resolved a comment's concern, the classifier still marks it FIX. The per-comment subagent (Phase 4) reads the code, recognizes the fix is in place, and returns `fix_outcome="already_addressed"` with `fix_commit_sha=<the-existing-commit-sha>`. No new commit. Skill B's reply template handles this with "Already addressed in `<sha>`" and resolves the thread normally. This handles the "user pushed manually" use case without needing a separate mode or classification (and resolves the gap from earlier draft revisions where re-running Skill A on a manual push would dispatch bogus fix subagents).

Phase 3 enforcement: each item's `rationale` MUST be non-empty before classification is finalized. If the agent emits an empty rationale, retry the per-item classification with an explicit prompt.

Duplicate handling: multiple comments sharing a root cause and one fix → mark every duplicate FIX, set the same `fix_commit_sha`, Skill B's reply template cross-references the primary.

**`kind`** (preserved verbatim from GitHub — mirrors today's `resolve-pr-comments` Phase 1 vocabulary):

| `kind` | Source | Reply endpoint | Resolvable? |
|---|---|---|---|
| `review_thread` | GraphQL `reviewThreads.nodes` | REST `POST /repos/<o>/<r>/pulls/<n>/comments/<id>/replies` (numeric `databaseId` from `reply_to_comment_id`) | Yes — GraphQL `resolveReviewThread` mutation, only when `classification = FIX` |
| `review_summary` | GraphQL `reviews.nodes` | `gh pr comment` | No |
| `issue_comment` | REST `/issues/<n>/comments` | `gh pr comment` with cross-reference | No |

### Per-comment subagent contract

Each FIX item is dispatched to a dedicated subagent. The subagent:

1. Reads the comment + surrounding code context.
2. Decides one of three outcomes:
   - **`committed`**: implements the fix, runs verification, commits.
   - **`already_addressed`**: reads HEAD, recognizes the comment's concern has already been resolved (e.g. by an earlier commit on this branch). Returns `fix_commit_sha=<existing-sha-that-addressed-it>` discovered per the procedure below. No new commit.
   - **`failed`**: cannot address; reports reason.
3. For `committed` outcome only:
   - **Verify FIRST, commit SECOND.** Subagent does not commit until its own verify passes.
   - Verification: full gate (`quality-reviewer` → `code-simplifier` → `verify-checklist`) is mandatory unless lite-gate criteria met.
   - **Lite gate** (`verify-checklist` only): determined by a concrete eligibility self-check the subagent runs BEFORE picking gate variant:
     ```bash
     # Single-file check
     FILES=$(git diff --staged --name-only | wc -l); [ "$FILES" -eq 1 ] || GATE=full
     # Diff content check — any new control flow / imports / exports → full gate
     git diff --staged | grep -cE '^\+(import |from .* import |require\(|use |export |@import|if |for |while |switch |case |try |catch |throw |return [^;]+;)' \
       | { read N; [ "$N" -eq 0 ] || GATE=full; }
     GATE=${GATE:-lite}
     ```
     Conservative — any predicate uncertainty defaults to `full`. Subagent records its choice as `fix_gate_variant`.
   - Commits with message `fix(<scope>): <summary> (PR #<n> comment <comment_id>)`. Each subagent's commit stands alone; no squashing.
4. Reports back: `comment_id`, `fix_outcome`, `fix_summary`, `fix_commit_sha` (only for `committed` and `already_addressed`), `fix_gate_variant` (only for `committed`), verification evidence (test command + output, only for `committed`).

**`already_addressed` SHA-discovery procedure** (subagent MUST follow this priority order; do NOT default to HEAD):

1. **Diff search**: `git log --diff-filter=AM -p --follow -- <file>` — inspect commits whose diff against the comment's `original_line` removes or replaces the flagged code. If a commit's diff hunk visibly addresses the comment's stated concern, return that SHA. The subagent MUST quote the matching diff hunk in `fix_summary` for orchestrator audit.
2. **Blame fallback**: if (1) returns no candidate, run `git blame <file> -L <line>,<line>` ONLY IF the current `<file>:<line>` content visibly matches the comment's stated concern (i.e., the fix is in place). Return the blame's commit SHA.
3. **Failure**: if neither (1) nor (2) yields a defensible SHA, the comment is NOT already-addressed — return `failed` with reason `"could not locate the commit addressing this concern"`.

For comments without `path`/`line` metadata (`review_summary`, `issue_comment` referring to general design): the SHA-discovery procedure cannot apply. Such items must classify either `committed` (subagent makes a real fix) or `failed` — `already_addressed` is unavailable.

**Subagent dispatch in v1: SERIAL ONLY.** Subagents are dispatched one at a time. Parallelism (across non-overlapping files) is deferred to a follow-up bead — predicting file overlap before dispatch is a chicken-and-egg problem the v1 spec does not solve.

**Orchestrator-side enforcement** (the contract is unenforceable from prose alone, so the orchestrator audits each report):

Phase 4 captures `<phase4_baseline_sha>` at entry (`git rev-parse HEAD`). For EACH serial subagent, the orchestrator captures `<pre_subagent_sha> = git rev-parse HEAD` BEFORE dispatching, passes it to the subagent as input context, and audits AFTER the subagent reports.

After each subagent reports back, the orchestrator MUST:
- Verify the report includes a non-empty `fix_outcome`. Missing → re-classify item to ESCALATE with rationale `"subagent contract violated: no fix_outcome"`.
- For `committed` outcome:
  - Verify non-empty `verify-evidence`. Missing → ESCALATE.
  - Verify EXACTLY ONE new commit exists since `<pre_subagent_sha>`: `git rev-list <pre_subagent_sha>..HEAD --count` returns `1`, and that commit's SHA equals `fix_commit_sha`. Multiple commits or zero commits → ESCALATE with rationale `"subagent contract violated: expected exactly one commit"`.
- For `already_addressed` outcome:
  - Verify `fix_commit_sha` is reachable AND predates `<phase4_baseline_sha>` (it's an EARLIER commit, not a subagent-produced one): `git merge-base --is-ancestor <fix_commit_sha> <phase4_baseline_sha>`. Mismatch → ESCALATE.
  - Verify `fix_summary` quotes a diff hunk (string contains `+` or `-` markers) — minimal proof the subagent followed the discovery procedure rather than guessing. If the report is just prose, ESCALATE with `"subagent contract violated: already_addressed missing diff evidence"`.
- For `failed` outcome: re-classify item to ESCALATE with rationale `"subagent failed: <reason>"`.
- If a stale broken commit was made by a non-compliant subagent (committed without reporting `committed`, or committed multiple times): use `git reset --soft <pre_subagent_sha>` (preserves working tree AND staged index for inspection — `--soft` not `--mixed` to avoid cross-subagent contamination), then `git stash push --include-untracked --message "broken-subagent-<comment_id>"` to isolate the contamination from the next serial subagent. Surface the stash ref in the orchestrator's report. This is the only `git reset` invocation in the spec; no `--hard` anywhere.

### Mode-aware ESCALATE

Mode is determined by an explicit `--mode` arg.

| `--mode` value | Trigger source | Behavior on ESCALATE |
|---|---|---|
| `interactive` (default) | Operator in chat | Pause Phase 3.5; emit one batched prompt listing every ESCALATE item with rationale + summary of FIX items as sanity check. User resolves each ESCALATE → `FIX-with-direction` / `SKIP-with-rationale` / `DEFER`, AND may re-classify any FIX → SKIP/ESCALATE. Reclassifications flow into the inventory before Phase 4. |
| `autonomous` | `run-queue`, formula step, scheduled trigger | Apply `bd label add <bead-id> human` (NOT `bd human <id>` — see Glossary), then `bd update <bead-id> --append-notes "<batched-escalate-list>"` (`--append-notes` appends; `--notes` would REPLACE existing notes). Each item formatted as: `ESCALATE: <comment_id> (@<author>): <body_excerpt> — rationale: <rationale>`. Mark each ESCALATE item `escalation_filed=true` in the inventory. Continue to Phase 4 with FIX items only. |

**Hard guard at Phase 1**: `--mode autonomous` requires `--bead-id <id>` (non-empty). Absence → fatal startup error (`'--mode autonomous requires --bead-id'`); no inventory write, no work begins.

Formulas pass `--mode autonomous --bead-id {{bead-id}}` explicitly. Manual operator chat invocations omit both (interactive default).

**DEFER placement** (interactive only): apply `beads.md` I3 sibling test. Pass → `bd create --parent <parent-of-current-bead>`. Fail or no parent → orphan + `bd dep add <new-id> <bead-id> --type discovered-from`.

**Hook is interactive-default**: `detect-pr-push.sh` emits a generic suggestion. The formula's `await-review` step is the canonical autonomous entry point (it passes `--mode autonomous --bead-id` directly). Skill A has a Red Flag: *"If you see the hook's `respond-to-pr-feedback` suggestion mid-formula, use the formula's invocation (with `--mode autonomous --bead-id`), not the hook text."*

### Hand-off Contract: pinned JSON schema

Skill A writes (and Skill B reads) a JSON inventory at:

```
~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<head_sha_after_push>.json
```

Persistent location (not `/tmp`): tmpfs gets cleared on reboot. Directory created on first write (`mkdir -p`). Path includes SHA so stale files are obvious. Atomic write via `mktemp` + `mv` (same filesystem, POSIX-atomic).

**Inventory writing is a NAMED HELPER bash script** — `write-inventory.sh`, shipped alongside Skill A's polling scripts. Signature:

```bash
write-inventory.sh <state> <last_completed_phase> <inventory_json_path>
# state: complete | partial
# last_completed_phase: e.g. "5a-verify-failed", "7-write-inventory", "8-skill-b-done"
# inventory_json_path: target file path (will be written atomically via mktemp + mv)
```

Implementation: reads stdin (the inventory JSON body), uses `jq` to set `crash_recovery.skill_a_completed` and `crash_recovery.last_completed_phase`, writes to `<path>.tmp.<pid>` (mktemp), then `mv` to final path. Also runs retention housekeeping (`find ~/.claude/state/pr-inventory/ -mtime +30 -delete` — never touches files <30 days, so safe for crash recovery).

**Agent-side invocation pattern** (heredocs are sandbox-blocked per `git-commits.md`, so use a temp file):

```bash
# Build inventory JSON via jq pipeline (no heredoc), then pipe into helper:
jq -n --argjson items "<items-json>" --argjson pr "<pr-json>" \
  '{schema_version: 1, pr: $pr, polling: <polling-obj>, items: $items}' \
  > /tmp/pr-inventory-build-<n>.json
~/.claude/skills/<skill-a-dir>/write-inventory.sh complete 7-write-inventory \
  ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
  < /tmp/pr-inventory-build-<n>.json
rm -f /tmp/pr-inventory-build-<n>.json
```

`validate-inventory.sh` is invoked with a single positional path argument (no stdin):

```bash
~/.claude/skills/<skill-a-dir>/validate-inventory.sh \
  ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
  || { echo "schema validation failed"; exit 1; }
```

Pin both invocation patterns in the SKILL.md prose so the agent has a copy-pasteable template at each call site.

Called by:
- Phase 7 success path: `write-inventory.sh complete 7-write-inventory <path>`.
- Every Phase 5x failure path: `write-inventory.sh partial 5{a|b|c}-...-failed <path>`.
- Phase 8 success path: `write-inventory.sh complete 8-skill-b-done <path>`, then `unlink`.

**Schema validation is a NAMED HELPER bash script** — `validate-inventory.sh <inventory_json_path>`. Returns 0 if valid, non-zero with the violating item logged to stderr otherwise. Implementation: eight `jq` predicates, one per guard listed in §"Schema validation guards" below. Skill B Phase 0 invokes this; corrupt inventory → hard abort.

Schema (`schema_version: 1`):

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
    "skill_a_completed": true,                // false until Phase 8 succeeds
    "last_completed_phase": "8-skill-b-done"
  }
}
```

Notes:
- `review_summary` items have only `kind`, `body_excerpt`, `author`, `classification`, `rationale`, `fix_outcome`, `fix_commit_sha`, `fix_summary`, `fix_gate_variant`. No `thread_id`, `reply_to_comment_id`, `issue_comment_id`.
- The `polling.copilot_review_submitted_at` field is dropped from v1 — re-add as `schema_version: 2` when `agents-config-58m` lands a real consumer.
- `polling.copilot_status` is consumed by Skill B Phase 4 final report ("Polling outcome: <copilot_status>"); kept for that purpose.

**Schema validation guards** (Skill B Phase 0 invokes `validate-inventory.sh`):
- Reject if any item has `rationale == "" or null` (regardless of classification — SKIP rationale becomes the public reply, so empty rationale = empty PR comment).
- Reject if any item has `classification != "ESCALATE"` and `escalation_filed == true`.
- Reject if any item has `kind == "review_summary"` and any of `thread_id`/`reply_to_comment_id`/`issue_comment_id` is non-null.
- Reject if any item has `classification != "FIX"` and `fix_outcome != null` (non-FIX items must have null fix_outcome).
- Reject if any item has `classification == "FIX"` and `fix_outcome` is not one of `committed | already_addressed | failed` (Skill A Phase 7 writes only after Phase 4 completes — every FIX item must have a non-null outcome).
- Reject if any item has `fix_outcome == "committed"` and any of `fix_commit_sha`/`fix_summary`/`fix_gate_variant` is null.
- Reject if any item has `fix_outcome == "already_addressed"` and `fix_commit_sha` is null.
- Reject if JSON parse fails or `schema_version != 1`.
- On reject: log violating item to stderr; abort with no replies posted.

### Skill A: arg protocol

Invoked via `Skill(skill: "<skill-a-name>", args: "<args-string>")`.

Recognized grammar (regex-style, all groups optional):

```
(<integer> | <pr-url>)?  (--bead-id <token>)?  (--mode autonomous|interactive)?
```

Plus tail tokens (operator narration) that are warned-and-ignored.

**Parsing rules**:
- Truly unknown tokens (`be careful about formatting`): warn-and-ignore.
- Recognized-but-malformed tokens (`--mode <unknown-value>`, `--bead-id` with no value or empty value): fatal startup error.
- `--mode autonomous` without `--bead-id`: fatal startup error.

### Skill A: phases

| ID | Phase | Notes |
|---|---|---|
| 1 | Detect PR + parse args + concurrency check | Refuse if a partial inventory file exists for this PR (see Concurrency recovery branch table). Hard guards on autonomous-mode + bead-id. |
| 2 | Poll Copilot | Background script — zero-token. |
| 3 | Inventory + classify (FIX/SKIP/ESCALATE) + ESCALATE branch (Phase 3.5, mode-aware) | Each item's rationale must be non-empty (retry per-item if empty). Round counter increments at each entry to Phase 3 (initial pass = round 1; each Phase 6 → Phase 3 reentry = +1). After Phase 3, classifications are final for this round. |
| 4 | Execute every FIX (per-comment subagents per the contract) | **Capture `<baseline_sha> = git rev-parse HEAD` as Phase 4 entry step.** Dispatch subagents serially. Audit each report (per orchestrator-side enforcement). |
| 5a | Combined verification gate | Run `verify-checklist` across all `committed`-outcome subagents' work. **On failure**: `write-inventory.sh partial 5a-verify-failed <path>`; report to caller; abort. |
| 5b | Verify subagent commits exist locally | Confirm each FIX/`committed` item's `fix_commit_sha` is in `git rev-list <baseline_sha>..HEAD`. **On mismatch**: `write-inventory.sh partial 5b-commit-verify-failed <path>`; report to caller; abort. |
| 5c | Push | `git push`. **On failure**: keep local commits; `write-inventory.sh partial 5c-push-failed <path>` with `pr.head_sha_after_push = head_sha_at_inventory`; report to caller with instruction to push manually then invoke `<skill-b-name> --resume <path>`. Abort. |
| 6 | Re-poll for Copilot re-review | Existing 30s background-script window. If new review arrives, return to Phase 3 (round +1). **Cap fires when round >= 3 AND Phase 6 detects new review.** After cap: do one final Phase 3 inventory pull (no Phase 4). For round-N+1 items: classify normally (FIX/SKIP/ESCALATE per the usual rules). Then mark ONLY the FIX-classified round-N+1 items as `classification=ESCALATE, rationale="exceeded re-review round cap"` — SKIP/praise items keep their natural classification and get normal SKIP replies. This avoids posting the cap-exceeded template on harmless "LGTM" Copilot acks. If Phase 6 detects no new review (`no_rereview_started`), exit Phase 6 normally. |
| 7 | Write inventory | `write-inventory.sh complete 7-write-inventory <path>`. (Chain has not yet fired; if we crash here, recovery resumes from Phase 8 via `--from-inventory`.) |
| 8 | Invoke Skill B | Default-on. Construct args: `--from-inventory <path>` plus mode args (`--mode autonomous --bead-id <id>` if Skill A ran autonomous). Invoke via `Skill(skill: "<skill-b-name>", args: ...)`. **On Skill B success**: `write-inventory.sh complete 8-skill-b-done <path>`; then `unlink <path>` (Skill A is the file's lifecycle owner). **On Skill B failure**: leave inventory in place (last write was `last_completed_phase="7-write-inventory"`); report Skill B's error with instruction to invoke `<skill-b-name> --resume <path>` manually. |

**8 phases total** (5 has 3 sub-phases). Each named phase is one named action with one defined failure mode.

### Skill B: arg protocol

Invoked via `Skill(skill: "<skill-b-name>", args: "<args-string>")`.

Recognized grammar:
```
(--from-inventory <path>)? (--resume <path>)? (--mode autonomous)? (--bead-id <token>)?
```

**Phase 0 precedence** (resolves arg combinations):
1. `--from-inventory` and `--resume` are mutually exclusive — both passed = fatal error.
2. `--resume` (or `--from-inventory`) with no path argument = fatal error.
3. Bad JSON or missing file at the supplied path = fatal error (do NOT silently fall through).
4. `--mode autonomous` without `--bead-id` = fatal error.
5. Standalone invocation (no `--from-inventory` and no `--resume`) = fatal error in v1 (standalone mode is deferred to a follow-up bead).
6. Schema validation (`validate-inventory.sh <path>`) failure = fatal error.

### Skill B: phases (two modes)

Skill B has TWO modes selected by Phase 0:

- **From-Skill-A** (`--from-inventory`): inventory is fresh and complete. Phases 0 → 1 → 2 → 3 → 4.
- **Resume** (`--resume`): partial inventory from interrupted Skill A run. Phases 0 → 1 → 1.5 → 2 → 3 → 4.

(Standalone mode is deferred. The "I pushed manually, just close out the threads" use case is handled in v1 by re-running Skill A; the per-comment subagent recognizes already-fixed items and returns `fix_outcome="already_addressed"` with the user's commit SHA, naturally producing correct replies and resolves.)

| ID | Phase | Modes | Notes |
|---|---|---|---|
| 0 | Mode detection + schema validation | all | Apply Phase 0 precedence (above). Run `validate-inventory.sh`. On any failure: abort. |
| 1 | Read inventory | all | From-Skill-A: verify `pr.head_sha_after_push` matches `gh pr view <n> --json headRefOid`. On mismatch: run `git fetch origin <pr-branch>` and re-check up to 2 times (5s sleep between) — handles transient post-push lag. Persistent mismatch = warn + abort with operator instruction "another push happened concurrently; reconcile manually then re-invoke `<skill-b-name> --resume <path>`." Resume: read regardless of head-SHA mismatch. |
| 1.5 | Recovery triage | resume | Verify each FIX/`committed` item's `fix_commit_sha` is in PR branch history: `git fetch origin "refs/heads/<pr-branch>:refs/remotes/origin/<pr-branch>" && git merge-base --is-ancestor <sha> origin/<pr-branch>`. Items with missing-from-history SHAs prompt the user (interactive) or apply `bd label add <bead-id> human` + `bd update <bead-id> --append-notes` (autonomous): `ABANDON` → reply with SKIP rationale; `DEFER` → reply with pending-tracking template referencing a public link; `FIX-NOW` → user manually fixes, then re-runs Skill A. No unconditional "Pending — addressing in follow-up" promises. |
| 2 | Reply to every item (FIX + SKIP + ESCALATE-with-escalation_filed=true) | all | Per pinned reply text templates (below). |
| 3 | Resolve only `kind=review_thread` AND `classification=FIX` items via GraphQL `resolveReviewThread`. Never resolve SKIP or ESCALATE. | all | |
| 4 | Final report | all | Structured close-out summary including `polling.copilot_status` from inventory. **Skill B does NOT unlink the inventory** — Skill A owns the file's lifecycle (unlinks at Phase 8 success). |

### Reply text templates (PR-public — pin to avoid jargon leaks)

**No internal jargon** (`bd`, bead IDs, `ESCALATE`, `inventory`, `phase`, `crash_recovery`) appears in PR-public replies.

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

Red Flag in Skill B SKILL.md: *"Never include `bd`, bead IDs (e.g., `agents-config-xyz`), `ESCALATE`, `inventory`, `phase`, or other internal tool names in PR replies. The reply matrix templates above are the only sanctioned text. The DEFER recovery template links to public artifacts only — never to bead IDs."*

### Concurrency recovery branch table

If Skill A starts and finds a pre-existing inventory file for this PR, it consults the inventory's `crash_recovery` block:

| `skill_a_completed` | `last_completed_phase` value | Action |
|---|---|---|
| false | `5a-verify-failed`, `5b-commit-verify-failed`, `5c-push-failed` | Refuse with **Message #1** (RESUME or DISCARD) |
| true | `7-write-inventory` | Refuse with **Message #2** (FROM-INVENTORY only) |
| true | `8-skill-b-done` | Silent unlink (orphan from prior crash); proceed normally |

**Message #1**:
```
Refused to start: a partial inventory exists for PR #<n> from a prior interrupted run.
  File:           ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json
  Last phase:     <crash_recovery.last_completed_phase>
  Recovery:
    Option 1 — RESUME (preserves classifications, replies to what's complete):
      <skill-b-name> --resume <path>
      <skill-b-name> --resume <path> --mode autonomous --bead-id <bead-id>
    Option 2 — DISCARD (lose state, restart from scratch):
      rm <path> && <invoke this skill again>
```

**Message #2**:
```
Refused to start: an inventory exists for PR #<n> where Skill A completed but Skill B never ran.
  File:           ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json
  Recovery:
    <skill-b-name> --from-inventory <path>
    <skill-b-name> --from-inventory <path> --mode autonomous --bead-id <bead-id>
```

**Inventory cleanup timing**:
- At Skill A startup: housekeeping ONLY (delete files >30 days). Never touch the inventory currently being recovered.
- At Phase 8 success (after Skill B reports success): Skill A updates `last_completed_phase="8-skill-b-done"` then unlinks.
- Never at Phase 1 (the concurrency check refuses before any cleanup of current PR's files).

### Decisions

- **Two skills, not one** — honors user's "don't overload" constraint while keeping discoverable narrow Skill B (Pain Point #2).
- **Standalone Skill B mode deferred** — the "I pushed manually" use case is handled by re-running Skill A; the per-comment subagent's `already_addressed` outcome produces correct behavior without requiring a separate mode.
- **Per-subagent commits, no squashing; serial dispatch in v1** — pin commit semantics; defer parallelism to a follow-up bead because predicting file overlap before dispatch is unsolved.
- **Default-on chain in skill text, not formula DAG** — accepts skills are advisory. The fix is making the chain unconditional (Phase 8 default-on, no item-count guard).
- **Frontmatter is load-bearing for INTENT DISCOVERY but is NOT load-bearing for HAND-OFF ENFORCEMENT** (it failed in lu3). Frontmatter rewrites address Pain Point #2; Phase 8 default-on addresses the orphan-threads bug.
- **Inventory writer + validator extracted as bash helpers** — concrete shell scripts shipped with Skill A; resolves "this looks like pseudocode" criticism.
- **Skill A owns inventory lifecycle** — Skill B never unlinks.
- **`bd label add <id> human` + `--append-notes`** — corrects the project-wide folklore that `bd human <id>` adds the label.
- **`fix_outcome` field handles already-addressed items** — replaces the deferred standalone Skill B path with subagent-level recognition.
- **PR strategy: single PR** — recommended for the redesign + rename + cross-reference updates as one bead. Cross-reference diffs cluster naturally for review.

### Why NOT a formula (Option C from bead notes), for now

A formula DAG would give true structural enforcement via `bd mol next` step gates. Rejected for now: PR review is overwhelmingly same-session; a formula adds ~80 lines of TOML and another orchestration loop in `implement-bead`. If dogfooding shows recurring orphan-threads bugs, escalate to the formula split as the next iteration.

---

## Renames

| Current | Proposed | Rationale |
|---|---|---|
| `wait-for-pr-comments` | **`respond-to-pr-feedback`** | Post-redesign the skill polls + classifies + fixes + pushes + chains. "Wait" describes only polling. Cost: directory rename + cross-reference updates across **16 files** (47 individual references). Implementer should run Step 0 grep before committing to rename. |
| `resolve-pr-comments` | **`reply-and-resolve-pr-threads`** | Surfaces both verbs ("reply", "resolve") in the name — directly addresses Pain Point #2. |

If the user defers Skill A's rename, keep `wait-for-pr-comments` and aggressively rewrite frontmatter with keyword coverage.

### Pinned frontmatter `description:` text

**Skill A** (`respond-to-pr-feedback`):
> Use after a PR is created or updated, OR when an open PR has Copilot/human review feedback to respond to. Polls Copilot via background script (zero Anthropic tokens during the wait), classifies each comment as FIX/SKIP/ESCALATE, addresses every FIX item via per-comment subagents (which either commit a new fix or recognize the concern as already-addressed by an earlier commit), pushes the combined commits, then by default invokes `reply-and-resolve-pr-threads` to reply to every thread and resolve the FIXED ones. Keywords: respond, address, fix, handle, triage, classify, PR, review, Copilot, feedback.

**Skill B** (`reply-and-resolve-pr-threads`):
> Use to reply to every PR review thread and resolve the FIXED ones via GraphQL. Two modes: invoked automatically by `respond-to-pr-feedback` (`--from-inventory`), or `--resume` for crash recovery from a partial run. Does not fix code. Keywords: reply, resolve, thread, acknowledge, close out, post fix confirmation, bookkeeping, rebut, ack.

---

## Files to modify

**Implementation Step 0** — before editing anything, run:
```bash
grep -rln "wait-for-pr-comments\|resolve-pr-comments" \
  src/ README.md scripts/ docs/ 2>/dev/null
```
Reconcile against the list below. Append any unlisted files. Re-run after edits to confirm zero stale references.

**Hits in `docs/plans/` and `docs/specs/` are historical artifacts; do NOT update them — they document past states.** Add a one-line note at the top of each historical doc that references the old skill name: `> Historical — superseded by docs/specs/2026-04-26-pr-review-skill-redesign.md.`

| # | File / artifact | Action |
|---|---|---|
| 1 | `src/user/.agents/skills/wait-for-pr-comments/SKILL.md` | Rename directory if Skill A renamed. Rewrite per design: pinned frontmatter; Phase 1 (concurrency check + arg parsing + hard guards); Phase 3 (FIX/SKIP/ESCALATE + ESCALATE branch); Phase 4 (per-comment subagents serial + baseline-SHA capture + orchestrator-side enforcement); Phases 5a/5b/5c (each invoking `write-inventory.sh partial ...` on failure); Phase 6 (re-review loop with hard cap); Phase 7 (`write-inventory.sh complete 7-write-inventory ...`); Phase 8 (invoke Skill B; on success update + unlink); Hand-off Contract section; arg-protocol grammar; Reply Text linkage; Red Flag updates including hook-mid-formula flag. |
| 2 | `wait-for-pr-comments/poll-copilot-review.sh`, `poll-copilot-rereview-start.sh`, `poll-new-comments.sh`, `lib.sh` | No behavior change. If Skill A renamed, update header comments. **Verify `poll-new-comments.sh` is wired**; if dead, file follow-up bead to remove (do NOT remove in this PR). |
| 2a | **NEW** `wait-for-pr-comments/write-inventory.sh` | Bash script implementing the named helper. Signature in §"Hand-off Contract". `mktemp` + `mv` atomicity; retention housekeeping inline. |
| 2b | **NEW** `wait-for-pr-comments/validate-inventory.sh` | Bash script implementing the schema validator. Eight `jq` predicates per §"Schema validation guards"; exits 0 if valid, non-zero with violating item to stderr otherwise. |
| 3 | `wait-for-pr-comments/detect-pr-push.sh` | Update lines 22 and 34 prompt text: `"PR activity detected: #<n> (<url>). Run /<skill-a-name> to respond to and acknowledge review feedback."` (the leading `/` is a skill-name hint, not a slash-command literal — see Glossary note that follows the table). |
| 4 | `src/user/.agents/skills/resolve-pr-comments/SKILL.md` | Rename directory to `reply-and-resolve-pr-threads/` if renamed. Rewrite per design: pinned frontmatter; Phase 0 (precedence rules + invoke `validate-inventory.sh`); Phase 1 (read inventory); Phase 1.5 (resume-only triage); Phase 2 (reply per templates); Phase 3 (resolve FIX `review_thread`s); Phase 4 (report — no unlink). Reply Text Templates section. Arg-protocol grammar. Red Flag: never leak internal jargon. |
| 5 | `src/user/.claude/settings.json.template` | Line ~74 `command:` field. Update directory name if Skill A renamed. |
| 6 | `src/user/.claude/rules/delivery.md` | Step 8 rewrite: `"<skill-a-name> skill — mandatory, not optional; monitor for Copilot review, classify feedback as FIX/SKIP/ESCALATE, fix all FIX items via per-comment subagents (or recognize as already-addressed), push combined commits, then by default invoke <skill-b-name> for thread reply + resolve."` AUTOMATIC list: replace existing "Apply unambiguous PR feedback" with single bullet "Address PR review feedback (classify, fix, push, reply, resolve threads)". |
| 7 | `src/user/.claude/rules/completion-gate.md` | Line 22 references `wait-for-pr-comments`. Update if renamed. Either way append: `"(internally chains to <skill-b-name> for thread reply + resolve)"`. |
| 8 | `src/plugins/beads/.claude/rules/delivery.md` | Beads-aware addendum. Update if renaming. Add: "Skill A internally invokes Skill B by default; no separate molecule step needed." |
| 9 | `src/plugins/beads/.claude/rules/beads.md` | Line ~241 partnership allowlist. Update Skill A name if renamed; add `superpowers:reply-and-resolve-pr-threads` (Skill B's new name) below. |
| 10 | `src/plugins/beads/.beads/formulas/implement-feature.formula.toml` | `await-review` step. Update title to `"Await PR review, address feedback, and acknowledge every thread"`. Update description content. Pass `--mode autonomous --bead-id {{bead-id}}` to skill invocation. |
| 11 | `src/plugins/beads/.beads/formulas/fix-bug.formula.toml` | Same change pattern as #10. |
| 12 | `src/plugins/beads/.beads/formulas/merge-and-cleanup.formula.toml` | Line ~93 references `superpowers:wait-for-pr-comments`. Update name if renamed. **Pass `--mode autonomous --bead-id {{bead-id}}`**. Audit prose. |
| 12a | `src/plugins/beads/.beads/formulas/implement-feature.formula.toml`, `fix-bug.formula.toml`, and `src/plugins/beads/.claude/rules/beads.md` | Each contains `bd human {{bead-id}}` (or `bd human <id>` table entry) — folklore that does NOT actually add the `human` label (verified). Replace every `bd human {{bead-id}}` with `bd label add {{bead-id}} human` in the formulas. Update the `beads.md` table column "Set by" example from `bd human <id>` to `bd label add <id> human`. (This corrects the project-wide misconception while we're already touching adjacent files.) |
| 13 | `README.md` | Line ~82 currently has a SINGLE row for `wait-for-pr-comments` (verified — no `resolve-pr-comments` row exists today). Replace with TWO rows (one for renamed Skill A, ONE NEW row for Skill B — also fixes a coverage gap): `\| respond-to-pr-feedback \| Copilot-aware PR feedback handler. Polls, classifies (FIX/SKIP/ESCALATE), fixes via per-comment subagents (or recognizes already-addressed), pushes, then chains \`reply-and-resolve-pr-threads\` to acknowledge every thread. \|` and `\| reply-and-resolve-pr-threads \| Reply to every PR review thread; resolve only the FIXED ones via GraphQL. Two modes: invoked automatically by \`respond-to-pr-feedback\` or \`--resume\` for crash recovery. \|` |
| 14 | `src/user/.agents/skills/merge-guard/SKILL.md` | Three references at lines ~85, ~90, ~111. Update name if renamed. Pin wait-option text: `"Wait — I'll invoke <skill-a-name> which will poll, classify, fix, push, and chain <skill-b-name> to reply and resolve every thread."` |
| 15 | Persistent memories | If Skill A is renamed: at spec-implementation time, run `bd help remember` to discover the search command form, then search for occurrences of the old skill names and append a path-update note to each match. Do not rename memory keys. (Spec doesn't pin the exact CLI form because verifying it during implementation is one shell command.) |
| — | In-flight molecule alias | If Skill A renamed, create `src/user/.agents/skills/wait-for-pr-comments/SKILL.md` (NEW file at OLD path) containing only frontmatter + a one-line redirect: `"DEPRECATED: use respond-to-pr-feedback. Same behavior; renamed for scope clarity."` No supporting scripts. The new and old directory names are distinct — no installer collision. Verify with dry-run install. Schedule alias removal: file follow-up bead "Remove wait-for-pr-comments alias after one release cycle." Mass-migrating in-flight molecule descriptions would require `bd`-side updates to active molecule step text in the Dolt DB — risky DB writes; the alias avoids this with a single-file change. |
| — | Spec landing | Copy this plan to `docs/specs/2026-04-26-pr-review-skill-redesign.md`. **DO NOT replace the bead description** until the implementation bead closes. The bead description swap is part of the implementation bead's close-out, not this bead's. |

**Glossary note** (also goes into a new short subsection in §Decisions): The leading `/` in `/<skill-name>` (as in the hook's emitted prompt) is a heuristic skill-discovery hint that Claude's skill router resolves to a skill call. It is NOT a literal slash-command invocation (slash commands live in `commands/`, not `skills/`). The convention is preserved for continuity with existing hook output.

---

## Verification plan

This is a documentation / spec change — no tests to run. Verification by trace + one real-PR dogfood:

| # | Check | Pass criterion |
|---|---|---|
| 1 | Frontmatter discoverability | Each pinned `description:` text contains all keywords listed in §"Pinned frontmatter `description:` text". |
| 2 | Hand-off trace | Skill A Phase 8 has zero hits for "if items were skipped", "if Non-trivial items exist", "consider invoking", "you may want to". |
| 3 | Classification trace | Skill A has zero hits for `Mechanical bucket`, `Non-trivial bucket`, `Ambiguous bucket`, `three buckets`. |
| 4 | Skill B narrowness | `grep -nE 'git (commit\|push\|reset\|rebase\|merge -)' src/.../<skill-b-dir>/SKILL.md` returns zero hits. `git fetch` and `git merge-base --is-ancestor` are allowed in Phase 1.5. |
| 5 | Reply text templates | Skill B has zero hits for `bd ` (followed by space), `bd human`, `ESCALATE` (in user-facing reply context), bead-id format strings (e.g., `agents-config-xyz`); the eight pinned templates from §"Reply text templates" all present. |
| 6 | Mode-aware ESCALATE uses correct CLI | Skill A Phase 3 contains `bd label add`, `--append-notes` (not `--notes`), `--mode interactive`, `--mode autonomous`, `--bead-id`. Zero hits for `bd human <` (the broken folklore form). |
| 7 | Phase failure modes | Skill A Phases 5a/5b/5c each describe their specific failure mode + state transition + invocation of `write-inventory.sh partial ...`. |
| 8 | Concurrency & inventory cleanup | Skill A startup section describes both refusal flows per the branch table; cleanup happens at Phase 8 success only; the silent-unlink case for `8-skill-b-done` orphans is described. |
| 9 | Arg-protocol grammar | Both skills' arg-protocol sections contain the regex grammar AND the parsing rules (lenient on truly-unknown, fatal on recognized-but-malformed). |
| 10 | Cross-reference audit | `grep -rn "wait-for-pr-comments\|resolve-pr-comments" src/ README.md scripts/` returns hits only in the files in §"Files to modify" plus the alias directory (if renamed). |
| 11 | Formula coherence | `await-review` in both formulas + `check-pr-comments` in `merge-and-cleanup` all pass `--mode autonomous --bead-id {{bead-id}}`. |
| 12 | No destructive git in failure paths | Skill A's per-subagent failure path has zero hits for `git reset --hard`, `git clean -fd`. The single `git reset HEAD~1` (no `--hard`) for non-compliant subagent recovery is the only `git reset` in the spec. |
| 13 | Schema validation | Skill B Phase 0 invokes `validate-inventory.sh`; the eight guards are documented in §"Schema validation guards"; `validate-inventory.sh` exists in Skill A's directory. |
| 14 | Dispatch is serial in v1 | Skill A Phase 4 contains "serially" or "one at a time"; zero hits for `dispatching-parallel-agents` in Skill A. |
| 15 | Discoverability dogfood | In a fresh session, test prompts: "reply to PR feedback", "resolve threads on PR #N", "acknowledge Copilot review". Confirm Claude surfaces the new skill name in skill-discovery output. |
| 16 | Real-PR dogfood | First PR delivered through `implement-feature` after redesign. **PASS criterion**: zero orphaned threads on the PR (all `review_thread` items have a reply; FIX-with-`committed`-or-`already_addressed` items are resolved); zero internal-jargon strings in PR replies (no `bd `, no bead IDs, no `ESCALATE`, no `inventory`, no `phase`); `polling.copilot_status` reported correctly in Skill B's final report. **FAIL** = any criterion above missed. **On FAIL**: the implementation bead does NOT close; root-cause the failure, fix in this PR, re-dogfood. **Synthetic fallback**: if no bead-tracked PR is delivered within 5 calendar days of the redesign landing, run a synthetic dogfood — open a small no-op PR (e.g., a typo fix), let Copilot review, run Skill A end-to-end, verify PASS criteria. Synthetic PR can be closed without merging. |

---

## Sequencing for implementation

1. **Decide naming** — recommendation: rename both. Final call to user.
2. **Pre-edit grep** (Step 0) — reconcile §"Files to modify" against actual cross-references; pause if unlisted files appear.
3. **Author the helper scripts** (#2a, #2b) before Skill A's SKILL.md — Skill A's phase prose calls them by name.
4. **Skill A rewrite** (file #1 + scripts #2 + hook #3).
5. **Skill B rewrite** (file #4) — directory rename if applicable.
6. **Update rules + formulas + docs** (files #5–#15 + alias + spec landing).
7. **Verify by trace** — items 1–14.
8. **Dogfood** — verification steps 15, 16. PASS gates implementation bead close.
9. **Bead description swap** — performed by the implementation bead's close-out, not this bead's.

**PR strategy: single PR** for the redesign + rename + cross-reference updates (one bead). Cross-reference diffs cluster naturally for review.

**Size budget**: single-PR strategy holds if total diff stays under **~1,500 LoC delta**. Projected diff (existing-file LoC count + projected deltas): ~1,800 LoC across 17+ files. If implementation exceeds the budget, fall back to two-PR split: PR1 = skill rewrites + helper scripts + alias (user-facing behavior change); PR2 = cross-reference renames in formulas/rules/README/settings/merge-guard + bd-human-folklore fixes. PR1 first to land behavior change; PR2 once PR1 stable.

---

## Follow-up beads to file after this lands

- **Implementation bead** — the actual edits described above.
- **`pr-review` formula (Option C, deferred)** — if dogfooding shows recurring orphan-threads bugs OR multi-session PR monitoring becomes a real workflow.
- **Skill B standalone mode** — the user-as-classifier interactive triage path deferred from v1.
- **Phase 4 parallelism** — file-overlap heuristic for parallel subagent dispatch.
- **`poll-new-comments.sh` cleanup** — if Step 2 reveals it's dead code.
- **Remove `wait-for-pr-comments` alias** — schedule for one release cycle after the rename.
- **Cross-link with `agents-config-58m`** — schema_version: 2 adds `polling.copilot_review_submitted_at`.
- **Cross-link with `agents-config-zt1`** — Skill A's Phase 6 re-poll could remove + re-add `@copilot` reviewer.

---

## Out of scope

- Implementing the changes. This bead's deliverable is the spec; implementation is a follow-up bead.
- Changes to `wait-for-pr-comments`' polling scripts beyond (if renaming) header-comment updates.
- Authoring the optional `pr-review` formula (Option C).
- Behavior changes to `merge-and-cleanup.formula.toml` beyond rename + `--mode autonomous --bead-id` propagation + prose audit.
- Skill B standalone mode (deferred per "Decisions").
- Phase 4 parallel dispatch (deferred per "Per-comment subagent contract").
