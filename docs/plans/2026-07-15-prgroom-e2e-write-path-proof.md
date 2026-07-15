# prgroom Write-Path E2E Proof — Execution Plan

> **For agentic workers:** This is an operational campaign plan, not a code-implementation plan — it writes documentation cargo and drives a live CLI loop; no production code, so `test-driven-development` does not apply. Execute task-by-task in order; steps use checkbox (`- [ ]`) syntax. The evidence outputs ARE the test results. Tasks 7–9 invoke a live LLM fix agent and post to a live GitHub PR: never run them concurrently, never mix with the legacy `wait-for-pr-comments` skill on the same PR.

**Goal:** Prove prgroom's full write path (poll → cluster → fix commits → push → reply → resolve → resolve-escalated → quiesced) on a real PR, per `docs/specs/2026-07-15-prgroom-e2e-write-path-proof.md` (bead agents-config-abn9.8.32).

**Architecture:** A bait PR carries a genuinely useful runbook preflight section (with two deliberate small gaps); seeded review comments provoke each loop leg on demand — two inline fix-class comments target the gaps, one issue comment carries a genuine operator-policy question that forces the escalation leg. Copilot participates organically. prgroom runs `--interactive` from the PR-branch worktree; the operator (Claude session) supervises between cycles.

**Tech Stack:** prgroom CLI (uv tool), gh CLI, git worktree, bd.

**Session context established before Task 1:** worktree `/Users/scott/src/projects/agents-config/.claude/worktrees/docs+prgroom-runbook-preflight` on branch `worktree-docs+prgroom-runbook-preflight`; spec committed as `d0abd05`; prgroom installed on PATH.

---

### Task 1: Preflight

**Files:** none (environment checks)

- [x] **Step 1: Verify prgroom on PATH**

Run: `command -v prgroom && prgroom --help >/dev/null 2>&1; echo "exit=$?"`
Expected: `/Users/scott/.local/bin/prgroom` and `exit=0`. (If missing: `uv tool install --from /Users/scott/src/projects/agents-config/packages/prgroom prgroom`.)

- [x] **Step 2: Verify gh auth**

Run: `gh auth status`
Expected: `Logged in to github.com` for scotthamilton77, no error exit.

- [x] **Step 3: Create the campaign scratch dir**

Run: `mkdir -p /tmp/prgroom-e2e && echo ok`
Expected: `ok`. All logs/IDs land here.

- [x] **Step 4: Announce the two deviations (in chat, verbatim intent)**

(a) prgroom's package doc forbids mutating-verb runs "to try it out" — this campaign is the sanctioned E2E proof gating the cutover. (b) For this PR only, PR-review monitoring runs via monitor-pr/prgroom; wait-for-pr-comments and the detect-pr-push suggestion MUST NOT engage.

### Task 2: Runbook cargo

**Files:**
- Modify: `docs/architecture/prgroom/cutover-runbook.md` (insert new section between "Why a runbook…" and "## Drain before cutover")

- [x] **Step 1: Insert this exact section** (two deliberate gaps: no state-file inspection tip, no upgrade command — the seeds request them)

```markdown
## Operator preflight (before any prgroom run)

prgroom is not yet deployed by the installer; install it as a uv tool and
verify the entry point:

```bash
uv tool install --from /path/to/agents-config/packages/prgroom prgroom
prgroom --help   # must exit 0
gh auth status   # must show an authenticated github.com login
```

Then, for the PR being groomed:

- **Run from a worktree checked out on the PR's head branch.** The fix agent
  commits into the current worktree, and `push` refuses to act from any other
  branch (`PRECONDITION_WRONG_BRANCH`).
- **Pick the mode by trigger**: a chat/human-initiated session uses
  `prgroom run <owner>/<repo>#<n> --interactive` (returns control between
  cycles); cron/CI supervision uses `--autonomous` (the default — blocks in
  `wait` between cycles).
- **One groomer per PR** (the invariant above): confirm the PR has no live
  legacy inventory before pointing prgroom at it, and never invoke the legacy
  skills on a prgroom-groomed PR.
- **Read `status --json`'s `phase`, never the exit code alone** — an exhausted
  retry budget rides on exit 0 with `phase: human-gated`.
```

- [x] **Step 2: Verify the file renders sanely**

Run: `grep -n "Operator preflight" docs/architecture/prgroom/cutover-runbook.md`
Expected: one hit, section present between the state-store table and "Drain before cutover".

- [x] **Step 3: Commit**

```bash
git add docs/architecture/prgroom/cutover-runbook.md
git commit -m "docs(prgroom): add operator preflight section to cutover runbook" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01Xvhkg6q4nHQrJnwxBuQtyD"
```

### Task 3: Completion gate on the cargo

- [ ] **Step 1: Run gate-triage**

Run: `uv run /Users/scott/.claude/skills/gate-triage/gate_triage.py --repo-root . --base-ref main` (from the worktree root)
Expected: JSON with a tier. Docs-only diff → likely `SKIP`; announce the tier and driving facts in chat. Non-zero exit → fall back to `SERIAL`.

- [ ] **Step 2: Run the routed tier honestly**

`SKIP` → verify-checklist step 5 only (docs change: no tests/build apply; evidence = clean `git status`, rendered section). `SERIAL` → quality-reviewer agent → address → simplify skill → address → verify-checklist, in order.

### Task 4: Push and open the PR

- [ ] **Step 1: Push the branch**

Run: `git push -u origin worktree-docs+prgroom-runbook-preflight`
Expected: new branch on origin. (Ignore any detect-pr-push suggestion to run wait-for-pr-comments — announced deviation.)

- [ ] **Step 2: Create the PR with this exact body**

```bash
gh pr create --title "docs(prgroom): cutover-runbook operator preflight + E2E campaign spec" --body "$(printf '%s\n' \
"Adds the operator preflight section to the prgroom cutover runbook and the campaign design spec for the prgroom Phase-1 write-path E2E proof." \
"" \
"**This PR is the proving ground for bead agents-config-abn9.8.32** — prgroom will groom it end-to-end (fix, push, reply, resolve, escalation). Three seeded review comments follow after Copilot's organic review: two inline fix requests and one operator-policy question that must escalate. Evidence per acceptance criterion is appended to this description when the campaign concludes." \
"" \
"🤖 Generated with [Claude Code](https://claude.com/claude-code)" \
"" \
"https://claude.ai/code/session_01Xvhkg6q4nHQrJnwxBuQtyD")"
```

Expected: PR URL printed.

- [ ] **Step 3: Record the PR number**

Run: `gh pr view --json number -q .number | tee /tmp/prgroom-e2e/pr-number`
Expected: an integer; referenced below as `$PR` (`PR=$(cat /tmp/prgroom-e2e/pr-number)`).

### Task 5: Await Copilot's organic review

- [ ] **Step 1: Poll until Copilot's review appears**

Run (repeat with backoff, or background-monitor): `gh api repos/scotthamilton77/agents-config/pulls/$PR/reviews --jq '[.[] | {user: .user.login, state}]'`
Expected: an entry from `copilot-pull-request-reviewer[bot]` (typically 1–5 min). If none after 15 min: proceed anyway and record "no organic Copilot review at seed time" in evidence.

### Task 6: Seed the review comments

- [ ] **Step 1: Capture head SHA and anchor lines**

```bash
HEAD_SHA=$(gh pr view $PR --json headRefOid -q .headRefOid)
grep -n "uv tool install --from" docs/architecture/prgroom/cutover-runbook.md   # anchor for seed 2
grep -n "Read \`status --json\`" docs/architecture/prgroom/cutover-runbook.md    # anchor for seed 1
```

Expected: two line numbers in the new section (call them `L1` for the status bullet, `L2` for the install command).

- [ ] **Step 2: Post inline seed 1 (fix-class — state-inspection gap)**

```bash
gh api repos/scotthamilton77/agents-config/pulls/$PR/comments \
  -f body="This preflight should also tell the operator where to look when a run misbehaves: the per-PR state file (~/.local/state/prgroom/<owner>-<repo>-<n>.json) is the ground truth, and \`status --locked\` can exit 75 under contention rather than blocking. Please add a short 'inspecting state' bullet." \
  -f commit_id="$HEAD_SHA" -f path="docs/architecture/prgroom/cutover-runbook.md" -F line=L1 -f side=RIGHT --jq .id | tee /tmp/prgroom-e2e/seed1-id
```

- [ ] **Step 3: Post inline seed 2 (fix-class — upgrade gap)**

```bash
gh api repos/scotthamilton77/agents-config/pulls/$PR/comments \
  -f body="The install command should say how to pick up a newer prgroom after pulling main — \`uv tool install --force --from ... prgroom\` — otherwise operators run stale binaries after every merge. Please add the upgrade form." \
  -f commit_id="$HEAD_SHA" -f path="docs/architecture/prgroom/cutover-runbook.md" -F line=L2 -f side=RIGHT --jq .id | tee /tmp/prgroom-e2e/seed2-id
```

- [ ] **Step 4: Post the escalation seed (issue comment, genuine operator question)**

```bash
gh api repos/scotthamilton77/agents-config/issues/$PR/comments \
  -f body="Operator-policy question (needs Scott's ruling, not an agent's): does this PR count toward the runbook readiness gate's '≥3 real PRs groomed end-to-end', given its review items are partly seeded? Record the ruling either way — it sets precedent for what counts as a 'real PR' for the cutover gate." --jq .id | tee /tmp/prgroom-e2e/seed3-id
```

Expected for steps 2–4: three numeric IDs saved under /tmp/prgroom-e2e/.

### Task 7: prgroom run — cycle 1

- [ ] **Step 1: Launch the run in the background** (fix dispatch can exceed the 10-min foreground tool cap)

Run (from the worktree root, `run_in_background`): `prgroom run "scotthamilton77/agents-config#$PR" --interactive > /tmp/prgroom-e2e/run-1.log 2>&1; echo "exit=$?" >> /tmp/prgroom-e2e/run-1.log`
Expected: completes in ≤ ~35 min; log tail shows the cycle trace and a standalone `exit=` line (0 expected even when escalation gates — read the phase, not the exit code).

- [ ] **Step 2: Read the envelope**

Run: `prgroom status "scotthamilton77/agents-config#$PR" --json > /tmp/prgroom-e2e/status-1.json; echo "exit=$?"; python3 -m json.tool /tmp/prgroom-e2e/status-1.json`
Expected: `phase: "human-gated"`; `items_summary` with `fixed: 2` (seeds) plus dispositions for Copilot items; `escalated: 1`; escalation stderr line in run-1.log naming seed3's gh_id.

- [ ] **Step 3: Verify the write-path facts independently**

```bash
git fetch origin && git log --oneline origin/worktree-docs+prgroom-runbook-preflight -5   # fix commits pushed by prgroom
gh api repos/scotthamilton77/agents-config/pulls/$PR/comments --paginate --jq '[.[] | select(.in_reply_to_id != null) | {id, in_reply_to_id}]'   # replies posted on both seed threads
```

Expected: ≥1 new fix commit reachable on the branch; reply entries for seed1/seed2 threads; both threads resolved (check `gh pr view $PR --json reviewThreads` or the UI). **HALT CONDITION:** any item dispositioned `failed` → stop the campaign, capture `/tmp/prgroom-e2e/` + the state JSON, file the defect via triaging-discovered-work, bead stays open.

### Task 8: Escalation leg — the designed human checkpoint

- [ ] **Step 1: Surface the escalation to Scott** — quote the `prgroom escalation [block]` line and the seeded question; get his ruling. (PAUSE — the only designed stop.)

- [ ] **Step 2: Clear it**

Run: `prgroom resolve-escalated "scotthamilton77/agents-config#$PR" $(cat /tmp/prgroom-e2e/seed3-id) --as wont_fix --rationale "<Scott's ruling, quoted>"`
Expected: exit 0; item flips to `wont_fix` with `decided_by: human:…`.

- [ ] **Step 3: Confirm release**

Run: `prgroom status "scotthamilton77/agents-config#$PR" --json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['phase'], d['last_error'])"`
Expected: `fixes-pending None` (release requires zero escalated, zero failed, clear last_error).

### Task 9: Drive to quiesced

- [ ] **Step 1: Re-run cycles until terminal**

Repeat (background, one at a time): `prgroom run "scotthamilton77/agents-config#$PR" --interactive > /tmp/prgroom-e2e/run-K.log 2>&1; echo "exit=$?" >> /tmp/prgroom-e2e/run-K.log` — incrementing K — then read status. Copilot re-review rounds are normal cycles; their new `review_summary` items get dispositioned by the fix agent. **Marathon guard:** more than 3 post-release rounds still minting new items → pause and consult Scott. **Transient guard:** exit 75 → bounded retry (≤2, spaced ≥60s) and record the occurrence as transient-retry evidence; exits 77/2/65/78 → stop and diagnose.

- [ ] **Step 2: Terminal check**

Run: `prgroom status "scotthamilton77/agents-config#$PR" --json > /tmp/prgroom-e2e/status-final.json; python3 -m json.tool /tmp/prgroom-e2e/status-final.json`
Expected: `phase: "quiesced"`, `last_error: null`, `merge_gates.phase_is_quiesced: true`, `no_blocker_items: true`.

### Task 10: Live-validation checks (fresh fixes)

- [ ] **Step 1: Own-reply ledger (8.28)** — later polls must not re-ingest prgroom's replies.

Run: `python3 -c "import json; [print(f, json.load(open(f'/tmp/prgroom-e2e/status-{f}.json'))['items_summary']) for f in ('1','final')]"`
Expected: item counts stable across post-reply cycles — no disposition-less item growth beyond genuinely new Copilot items; prgroom's own replies never appear as new items (the PR #211 self-reply-spam shape).

- [ ] **Step 2: Legacy export (8.13.1)**

Run: `ls -la ~/.claude/state/pr-inventory/ | grep "agents-config-$PR"`
Expected: `scotthamilton77-agents-config-$PR-<head_sha>.json` + matching `.replyids` sidecar.

- [ ] **Step 3: check-runs CI derivation (jkha6)**

Run: `python3 -c "import json; print(json.load(open('/tmp/prgroom-e2e/status-final.json'))['ci_state'])"`
Expected: `success` (Actions-only repo — the fixed derivation path).

### Task 11: Evidence assembly

- [ ] **Step 1: Build the evidence section** — one snippet per acceptance criterion per the spec's evidence map (loop outputs, `items_summary`, escalation + release, terminal phase, transient observed-or-not, this list itself). Append to the PR body via `gh pr edit $PR --body-file` (original body + evidence section).

- [ ] **Step 2: Record on the bead**

Run: `bd update agents-config-abn9.8.32 --append-notes "<evidence summary with command-output snippets and /tmp paths preserved into the PR body>"`
Expected: bead notes carry the six-criterion evidence.

### Task 12: Merge leg

- [ ] **Step 1: merge-guard, by the book** — invoke the merge-guard skill: `resolve_policy.py` (expect `rule-based` for this repo), then `check-merge-eligibility.sh $PR`. The legacy-export inventory from Task 10 is what clears `untriaged_feedback` — that observation is itself evidence. If `MERGE_GUARD_APPROVER_KEY_PATH` is unset or any gate blocks: hand off to Scott per policy — a human-gated merge is NOT a campaign failure; `quiesced` already satisfies the bead's terminal criterion.

- [ ] **Step 2: Post-merge cleanup (only if merged)** — from the main repo root: `git branch -D worktree-docs+prgroom-runbook-preflight` after confirming the squash lands on main; `ExitWorktree` with `discard_changes: true` per the squash-merge rule.

### Task 13: Closeout

- [ ] **Step 1: Close the bead**

Run: `bd close agents-config-abn9.8.32` then `bd show agents-config-abn9.8 | head -5`
Expected: bead closed; parent epic unaffected (manual check per close-walk unreliability).

- [ ] **Step 2: Triage continuations** (triaging-discovered-work skill, per spec's Continuations): verify-then-file the inert agent-chain TOML wiring (`bd search "agent-chain"` / `"fix-model"` first); check installer-adoption is tracked under the install epic; proofs 2–3 need no bead.

- [ ] **Step 3: Session close**

Run: `git pull --rebase && bd dolt push && git push && git status`
Expected: `up to date with origin`.
