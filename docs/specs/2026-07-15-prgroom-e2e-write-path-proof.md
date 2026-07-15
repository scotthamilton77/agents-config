# prgroom Phase-1 E2E Write-Path Proof — Campaign Design

- **Date:** 2026-07-15
- **Status:** Approved (Scott, 2026-07-15)
- **Bead:** agents-config-abn9.8.32
- **Gates:** agents-config-abn9.8.20 (destructive Phase-1 cutover) — this campaign is proof 1 of the ≥3 real-PR proofs the cutover runbook's readiness gate requires

## Goal

Prove prgroom's write path end-to-end on a real PR, driven via the monitor-pr skill: poll → cluster → fix (agent commits) → push → reply → resolve, plus the human-gated escalation leg cleared via `resolve-escalated`, ending in a terminal phase (`quiesced` or `merged`).

## Non-goals

- Re-validating the read-only contracts (poll, `status --json` envelope, `PRECONDITION_NO_STATE`, dispositions) — validated live on PRs #181 and #211.
- The destructive cutover itself (retiring wait-for-pr-comments) — owned by the cutover bead, which stays gated until the readiness gate's ≥3 proofs exist.
- Fixing prgroom defects discovered mid-campaign — the campaign halts and files them; it does not patch around the tool under test.

## Decisions

- **Proving ground:** a purpose-built bait PR on `scotthamilton77/agents-config` carrying genuinely useful cargo, so the merged artifact has standalone value.
- **Cargo:** an operator preflight/invocation section added to `docs/architecture/prgroom/cutover-runbook.md`, closing a real gap: prgroom is not on PATH after a clean install, and neither the runbook nor the monitor-pr skill documents installation, invocation directory, or the run preconditions. This spec rides the same PR.
- **Item provocation:** clean cargo plus seeded review comments — no deliberate flaws in content. Two inline review comments (fix-class, `REVIEW_THREAD` items — the kind the resolve step can thread-resolve) and one issue comment carrying a genuine operator-policy question (escalation-class). prgroom's poll ingests items from all authors (`_ingest_items` applies no author filter; only its own posted-reply IDs are excluded), so operator-authored seeds are first-class review items.
- **Copilot:** involved, not disabled. Copilot exercises machinery seeds cannot: `review_summary` dispositions, the `rereview` verb (re-requesting stale required reviewers), reviewer-engagement tracking, and the quiescence timers. Its re-review rounds also live-validate the posted-reply ledger (own replies excluded from re-ingestion) and the check-runs CI derivation on this Actions-only repo.
- **Terminal goal:** drive to `quiesced`, then hand off to normal merge-guard delivery under the repo's rule-based merge-authorization policy. No per-PR merge checkpoint is added.
- **Fix chain:** shipped defaults untouched — primary `claude` opus[1m] at xhigh effort with `--permission-mode dontAsk --allowedTools "Read Edit Write Bash(git *)"`, fallback `codex` gpt-5.6-terra. The proof targets the default path; overriding it would weaken the claim.

## Campaign phases

### 1. Preflight

- `uv tool install --from packages/prgroom prgroom`; verify `prgroom --help` exits 0.
- `gh auth status` green.
- No prior prgroom state for the PR (new PR; state bootstraps on first poll).
- Two announced deviations: (a) the prgroom package doc forbids mutating-verb runs against live PRs "to try it out" — this campaign is the sanctioned E2E proof that the cutover is gated on; (b) for this PR only, PR-review monitoring runs via monitor-pr/prgroom instead of wait-for-pr-comments; the legacy skill and the detect-pr-push hook suggestion must not engage (double-posting risk).

### 2. Cargo

Worktree on the PR head branch (prgroom's push refuses otherwise: `PRECONDITION_WRONG_BRANCH`). Write the runbook preflight section; run the completion gate honestly (docs-only change; gate-triage sets the tier). Commit, push, open the PR with a description that declares the proving-ground purpose and the seeded comments to come.

### 3. Seeding

After Copilot's organic first review lands, post under the operator's login via `gh`:

- Inline comment 1 (fix-class): request a short "inspecting state" tip — where the per-PR state file lives (the ground truth for a misbehaving run) and that `status --locked` exits 75 under contention rather than blocking.
- Inline comment 2 (fix-class): request the upgrade form of the install command (`uv tool install --force --from ... prgroom`), so an operator picks up a newer prgroom after pulling main instead of running a stale binary.
- Issue comment (escalation-class): a genuine operator-policy question — does this PR count toward the readiness gate's "≥3 real PRs groomed clean", given its seeded comments? Only the operator can rule; `escalated` is the correct disposition even with full context.

Record all three comment IDs.

### 4. The run

From the worktree root: `prgroom run scotthamilton77/agents-config#<n> --interactive`, then `prgroom status <ref> --json` after each cycle. Exit codes are captured standalone, never through a pipeline. Expected first cycle: poll ingests all items → cluster → fix dispatch commits locally → push → reply → thread-resolve → end-of-cycle resolver sees the escalated item → phase `human-gated`, with the two fixes already pushed, replied, and resolved. Copilot re-review rounds on pushed commits are normal grooming cycles. Decisions read the envelope's `phase`, never the exit code alone.

### 5. Escalation leg

`prgroom resolve-escalated <ref> <gh_id> --as wont_fix --rationale "<operator ruling>"` (issue-comment seed leaves no unresolved thread behind). Release requires zero `escalated` items, zero `failed` items, and a clear `last_error`; then re-run `prgroom run <ref> --interactive` and drive to `quiesced`.

### 6. Merge and closeout

At `quiesced`: verify the legacy inventory export exists (`~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<head_sha>.json` plus `.replyids` sidecar) — the merge-guard integration path, live. Then merge-guard as normal delivery under the rule-based policy. Evidence snippets (per the map below) go onto the PR description and the bead's notes. Close the bead; record that this is proof 1 of the ≥3 the readiness gate requires.

### 7. Failure handling

- Any fix item lands `failed` → halt the campaign, capture the state JSON and logs, file the defect through the discovered-work discipline, leave the bead open. No hand-fixing around prgroom.
- Terminal exits (77 user-terminal, 2 precondition, 65 contract, 78 state) → stop and diagnose; no blind retries.
- Exit 75 (transient) → bounded retry; the occurrence itself is evidence for the transient-retry criterion.
- Orphan-commit stash isolation fires → inspect the stash, capture evidence, file the defect.
- Copilot re-review marathon → pause and consult the operator.
- Rollback: close the PR unmerged, discard the worktree; seeded comments remain as honest history.

## Acceptance-criteria evidence map

| Bead criterion | Evidence artifact |
|---|---|
| Full loop driven via monitor-pr | `run` / `status --json` outputs per cycle |
| All fix-class items land committed, not failed | `items_summary` disposition counts + reachable commit SHAs on the branch |
| Human-gated escalation exercised and cleared | escalation stderr line, `resolve-escalated` output, phase release to `fixes-pending` |
| Terminal phase reported | `status --json` with `phase` ∈ {quiesced, merged} |
| Transient-retry path | observed exit-75 handling, or an explicit "not encountered" record |
| Evidence recorded | PR description + bead notes carry the snippets above |

## Risks

- **Fix agent dispositions a seeded fix-class item as `skipped`/`wont_fix` instead of fixing it** (disposition choice is LLM judgment). Mitigation: seeds are worded as small, unambiguous, actionable requests. If skipped anyway, that is honest loop behavior, not a `failed` regression — record it, and re-seed a clearer request if the committed-fix criterion still lacks coverage.
- **Copilot marathon** — bounded by pause-and-consult.
- **Coarse write grant** (`Bash(git *)` permits more than commit) — bounded by worktree isolation and by reviewing the full diff before merge.
- **Wall-clock** — quiescence timers (review-finish 15m, idle 10m) and up to 30-minute fix budgets make multi-hour elapsed time normal; interactive mode returns control between cycles.

## Continuations

Candidates to triage through the discovered-work discipline when this PR merges (verify none is already tracked before filing):

- prgroom's per-repo agent-chain configuration is inert: the CLI loads the chain without the repo config path, so `[agents.cluster]`/`[agents.fix]` TOML overrides and the `--cluster-model`/`--fix-model` flags have no effect.
- Installer adoption of prgroom's install lifecycle (likely belongs under the milestone's install epic).
- Proofs 2 and 3 of the readiness gate ride future organic PRs — no new bead; the cutover bead's gate already encodes the requirement.
